"""
Step 2 — Apollo.io scraper.

Strategy: launches a visible Chrome window. If Apollo shows the login page,
the user has 120 seconds to log in manually. The scraper then takes over.
No cookie injection issues — the browser behaves like a real user session.
"""
import asyncio
import logging
import os

from playwright.async_api import async_playwright, Page, BrowserContext

import config

logger = logging.getLogger(__name__)

_STEALTH_JS = """() => {
    Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
    Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
    window.chrome = { runtime: {} };
}"""

SELECTORS = {
    "next_page": [
        "button[aria-label='Next']",
        "button[data-cy='next-page']",
        "button[aria-label='Next page']",
        "button[aria-label='Go to next page']",
        "[class*='pagination'] button:last-child",
        "[class*='Pagination'] button:last-child",
    ],
}

# JavaScript extractor — Apollo uses div-based layout, contact links end with '?'
_JS_EXTRACT = """() => {
    const results = [];
    const seen = new Set();

    // Apollo: name links have href="#/contacts/{id}?..." or "#/people/{id}?..."
    const links = Array.from(document.querySelectorAll('a')).filter(a => {
        const h = a.getAttribute('href') || '';
        return (h.includes('/contacts/') || h.includes('/people/')) && h.includes('?');
    });

    for (const link of links) {
        const name = (link.textContent || '').trim();
        if (!name || name.length < 2 || seen.has(name)) continue;
        seen.add(name);

        // Strategy 1: find the table row (<tr>) containing this link
        const tr = link.closest('tr');

        // Strategy 2: walk up to find a div-based row container
        let divRow = null;
        let el = link.parentElement;
        for (let i = 0; i < 10 && el; i++) {
            // Look for a row-like container: has multiple links or has role="row"
            if (el.getAttribute('role') === 'row' ||
                el.tagName === 'TR' ||
                el.querySelectorAll('a[href*="/contacts/"], a[href*="/accounts/"], a[href*="/companies/"]').length >= 2) {
                divRow = el;
                break;
            }
            el = el.parentElement;
        }

        const row = tr || divRow || link.parentElement?.parentElement?.parentElement;
        if (!row) continue;

        const parts = name.split(' ');
        const lead = {
            first_name:   parts[0] || '',
            last_name:    parts.slice(1).join(' '),
            job_title:    '',
            company:      '',
            location:     '',
            linkedin_url: ''
        };

        // --- Extract from table cells (<td>) if in a table ---
        if (tr) {
            const cells = Array.from(tr.querySelectorAll('td'));
            const nameCell = cells.findIndex(c => c === link.closest('td') || c.contains(link));

            // Job title: typically the cell right after the name cell
            if (nameCell >= 0 && nameCell + 1 < cells.length) {
                const jt = (cells[nameCell + 1].innerText || '').trim().split('\\n')[0].trim();
                if (jt && jt.length < 120 && !jt.includes('@')) lead.job_title = jt;
            }

            // Company: cell containing an account/company link
            for (const cell of cells) {
                const compLink = cell.querySelector('a[href*="/accounts/"], a[href*="/companies/"]');
                if (compLink) {
                    lead.company = (compLink.textContent || cell.innerText || '').trim().split('\\n')[0].trim();
                    break;
                }
            }

            // If job_title still empty, try all cells for text that looks like a job title
            if (!lead.job_title) {
                for (let i = 0; i < cells.length; i++) {
                    if (i === nameCell) continue;
                    const cell = cells[i];
                    if (cell.querySelector('a[href*="/accounts/"], a[href*="/companies/"]')) continue;
                    const text = (cell.innerText || '').trim().split('\\n')[0].trim();
                    if (text && text.length > 3 && text.length < 120 &&
                        !text.includes('@') && !/^https?:/.test(text) &&
                        !text.toLowerCase().includes('no email') &&
                        !text.toLowerCase().includes('unlock') &&
                        text !== name) {
                        lead.job_title = text;
                        break;
                    }
                }
            }

            // Location: look for remaining cells with location-like text
            const SKIP = ['no email', 'unlock email', 'no phone', 'request phone', 'click to run', 'add to sequence', 'access email'];
            for (let i = nameCell + 2; i < cells.length; i++) {
                const cell = cells[i];
                if (cell.querySelector('a[href*="/accounts/"], a[href*="/companies/"]')) continue;
                const text = (cell.innerText || '').trim().split('\\n')[0].trim();
                if (!text || text.length > 60 || /^\\d+$/.test(text)) continue;
                if (SKIP.some(p => text.toLowerCase().includes(p))) continue;
                if (text.includes('@') || /^https?:/.test(text)) continue;
                if (text === lead.job_title) continue;
                lead.location = text;
                break;
            }
        }

        // --- Fallback: extract from div-based row children ---
        if (!lead.job_title || !lead.company) {
            const children = Array.from(row.children);
            const nameIdx = children.findIndex(c => c === link || c.contains(link));

            if (!lead.company) {
                const companyDiv = children.find(c =>
                    c.querySelector('a[href*="/accounts/"]') || c.querySelector('a[href*="/companies/"]')
                );
                if (companyDiv) lead.company = (companyDiv.innerText || '').trim().split('\\n')[0].trim();
            }

            if (!lead.job_title && nameIdx >= 0 && nameIdx + 1 < children.length) {
                const jt = (children[nameIdx + 1].innerText || '').trim().split('\\n')[0].trim();
                if (jt && jt.length < 120 && jt !== lead.company && !jt.includes('@')) lead.job_title = jt;
            }

            if (!lead.location) {
                const SKIP = ['no email', 'unlock email', 'no phone', 'request phone', 'click to run', 'add to sequence', 'access email'];
                for (let i = (nameIdx >= 0 ? nameIdx + 2 : 0); i < children.length; i++) {
                    const child = children[i];
                    if (child.querySelector('a[href*="/accounts/"], a[href*="/companies/"]')) continue;
                    const text = (child.innerText || '').trim().split('\\n')[0].trim();
                    if (!text || text.length > 60 || /^\\d+$/.test(text)) continue;
                    if (SKIP.some(p => text.toLowerCase().includes(p))) continue;
                    if (text.includes('@') || /^https?:/.test(text)) continue;
                    if (text === lead.job_title || text === lead.company) continue;
                    lead.location = text;
                    break;
                }
            }
        }

        // LinkedIn: look for a href containing linkedin.com/in/ within the row
        const liLink = row.querySelector('a[href*="linkedin.com/in/"]');
        if (liLink) {
            let href = liLink.getAttribute('href') || '';
            href = href.split('?')[0];
            lead.linkedin_url = href;
        }

        results.push(lead);
    }
    return results;
}"""


def _is_login_page(url: str) -> bool:
    return any(k in url for k in ["login", "sign_in", "signin", "auth"])


async def _wait_for_login(page: Page, timeout_seconds: int = 120) -> bool:
    """
    If on login page, wait up to `timeout_seconds` for the user to log in.
    Returns True once logged in, False on timeout.
    """
    logger.info(
        f"[ACTION REQUIRED] Apollo login page detected. "
        f"Please log in manually in the browser window. "
        f"You have {timeout_seconds} seconds."
    )
    for _ in range(timeout_seconds):
        await asyncio.sleep(1)
        if not _is_login_page(page.url):
            logger.info("Login detected — continuing scraping.")
            await asyncio.sleep(3)  # let dashboard load
            return True
    return False


async def _scrape_page(page: Page) -> list[dict]:
    """Extract leads from Apollo using JavaScript — robust against CSS class changes."""
    # Wait for the page to have some content
    try:
        await page.wait_for_selector("table, [class*='contact'], [data-cy]", timeout=15000)
    except Exception:
        pass
    await asyncio.sleep(2)

    # Debug: log sample of hrefs found on the page to understand Apollo's current structure
    try:
        sample_hrefs = await page.evaluate("""() => {
            const links = Array.from(document.querySelectorAll('a'));
            return links
                .map(a => a.getAttribute('href'))
                .filter(h => h && h.length > 1)
                .slice(0, 30);
        }""")
        logger.debug(f"Sample hrefs on page: {sample_hrefs}")
        # Log hrefs that look like profile links
        profile_like = [h for h in sample_hrefs if any(k in (h or '') for k in ['/people', '/contacts', '/person', 'apollo'])]
        if profile_like:
            logger.info(f"Profile-like hrefs found: {profile_like[:5]}")
        else:
            logger.warning(f"No profile hrefs found. Sample hrefs: {sample_hrefs[:10]}")
    except Exception as e:
        logger.debug(f"Debug href scan failed: {e}")

    # Debug: log the DOM structure around the first contact link
    try:
        debug_info = await page.evaluate("""() => {
            const link = Array.from(document.querySelectorAll('a')).find(a => {
                const h = a.getAttribute('href') || '';
                return (h.includes('/contacts/') || h.includes('/people/')) && h.includes('?');
            });
            if (!link) return { found: false };
            const tr = link.closest('tr');
            const info = {
                found: true,
                name: link.textContent?.trim(),
                href: link.getAttribute('href'),
                inTable: !!tr,
                parentTag: link.parentElement?.tagName,
                grandparentTag: link.parentElement?.parentElement?.tagName,
            };
            if (tr) {
                const cells = Array.from(tr.querySelectorAll('td'));
                info.cellCount = cells.length;
                info.cellTexts = cells.map(c => c.innerText?.trim().substring(0, 80));
                info.cellHrefs = cells.map(c => {
                    const a = c.querySelector('a');
                    return a ? a.getAttribute('href')?.substring(0, 80) : null;
                });
            } else {
                let el = link.parentElement;
                for (let i = 0; i < 10 && el; i++) {
                    const childCount = el.children?.length || 0;
                    if (childCount >= 3) {
                        info.rowTag = el.tagName;
                        info.rowRole = el.getAttribute('role');
                        info.rowChildCount = childCount;
                        info.rowChildTexts = Array.from(el.children).map(c => c.innerText?.trim().substring(0, 80));
                        break;
                    }
                    el = el.parentElement;
                }
            }
            return info;
        }""")
        logger.info(f"DOM debug info: {debug_info}")
    except Exception as e:
        logger.debug(f"DOM debug failed: {e}")

    try:
        leads = await page.evaluate(_JS_EXTRACT)
        if leads:
            logger.info(f"JS extraction found {len(leads)} leads on this page")
            # Log first lead details for debugging
            if leads[0]:
                logger.info(f"First lead sample: {leads[0]}")
            return leads
    except Exception as e:
        logger.error(f"JS extraction failed: {e}")

    return []


async def _take_debug_screenshot(page: Page, name: str):
    try:
        os.makedirs("output/debug", exist_ok=True)
        await page.screenshot(path=f"output/debug/{name}.png", full_page=False)
        logger.info(f"Debug screenshot: output/debug/{name}.png")
    except Exception:
        pass


async def _go_next_page(page: Page) -> bool:
    for sel in SELECTORS["next_page"]:
        try:
            btn = page.locator(sel).first
            if await btn.count() > 0:
                if (await btn.get_attribute("disabled")) is not None:
                    return False
                if (await btn.get_attribute("aria-disabled")) == "true":
                    return False
                await btn.click()
                # Apollo is a SPA — networkidle never fires due to background polling
                # Wait for DOM + extra sleep for React re-render
                try:
                    await page.wait_for_load_state("domcontentloaded", timeout=5000)
                except Exception:
                    pass
                await asyncio.sleep(config.REQUEST_DELAY + 2)
                return True
        except Exception:
            continue
    return False


async def scrape_apollo(apollo_url: str, max_leads: int = None) -> list[dict]:
    """
    Scrape Apollo.io in a visible browser window.
    If Apollo shows the login page, the user has 120s to log in manually.
    """
    if max_leads is None:
        max_leads = config.MAX_LEADS

    all_leads: list[dict] = []
    page_num = 1

    logger.info("Launching visible browser window for Apollo scraping...")

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=False,
            args=[
                "--no-sandbox",
                "--disable-blink-features=AutomationControlled",
                "--start-maximized",
            ],
        )

        context: BrowserContext = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1440, "height": 900},
        )

        # Try to inject cookies (may or may not work depending on Apollo's detection)
        cookies = config.load_cookies(config.APOLLO_COOKIES_PATH)
        if cookies:
            try:
                await context.add_cookies(cookies)
                logger.info(f"Injected {len(cookies)} cookies")
            except Exception as e:
                logger.warning(f"Cookie injection error (will proceed anyway): {e}")

        page = await context.new_page()
        await page.add_init_script(_STEALTH_JS)

        logger.info("Opening Apollo URL...")
        await page.goto(apollo_url, wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(4)

        # If on login page — wait for manual login
        if _is_login_page(page.url):
            logged_in = await _wait_for_login(page, timeout_seconds=120)
            if not logged_in:
                await _take_debug_screenshot(page, "apollo_login_timeout")
                raise RuntimeError(
                    "Login timeout — user did not log in within 120 seconds. "
                    "Please try again and log in quickly in the browser window."
                )
            # Navigate to the target URL after login
            logger.info("Navigating to search URL after login...")
            await page.goto(apollo_url, wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(4)

        while len(all_leads) < max_leads:
            logger.info(f"Scraping page {page_num} ({len(all_leads)} leads so far)")

            page_leads = await _scrape_page(page)

            if not page_leads:
                await _take_debug_screenshot(page, f"apollo_empty_page{page_num}")
                logger.warning(f"No leads found on page {page_num}. Stopping.")
                break

            all_leads.extend(page_leads)
            logger.info(f"Page {page_num}: +{len(page_leads)} leads (total: {len(all_leads)})")

            if len(all_leads) >= max_leads:
                break

            has_next = await _go_next_page(page)
            if not has_next:
                logger.info("No more pages.")
                break

            page_num += 1
            await asyncio.sleep(config.REQUEST_DELAY)

        await browser.close()

    all_leads = all_leads[:max_leads]
    logger.info(f"Apollo scraping complete. Total leads: {len(all_leads)}")
    return all_leads


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.DEBUG, format="%(asctime)s [%(levelname)s] %(message)s")

    url = sys.argv[1] if len(sys.argv) > 1 else input("Apollo URL: ").strip()
    max_leads = int(sys.argv[2]) if len(sys.argv) > 2 else 5

    leads = asyncio.run(scrape_apollo(url, max_leads=max_leads))
    print(f"\n{len(leads)} leads scraped:")
    for l in leads:
        print(l)
