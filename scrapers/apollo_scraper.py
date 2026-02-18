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
        "button[data-cy='next-page']",
        "button[aria-label='Next page']",
        "button[aria-label='Go to next page']",
        "[class*='pagination'] button:last-child",
        "[class*='Pagination'] button:last-child",
    ],
}

# JavaScript extractor — works regardless of Apollo CSS class changes
_JS_EXTRACT = """() => {
    const results = [];
    const seen = new Set();

    // Find all person-profile links (href contains /people/ or /contacts/)
    const links = Array.from(document.querySelectorAll('a')).filter(a => {
        const h = a.getAttribute('href') || '';
        return h.includes('/people/') || h.includes('/contacts/');
    });

    for (const link of links) {
        const name = (link.textContent || '').trim();
        if (!name || name.length < 2 || seen.has(name)) continue;
        seen.add(name);

        // Walk up to the nearest row container
        const row = link.closest('tr') ||
                    link.closest('[class*="row"]') ||
                    link.closest('[class*="item"]') ||
                    link.closest('[class*="person"]');
        if (!row) continue;

        const parts = name.split(' ');
        const lead = {
            first_name: parts[0] || '',
            last_name:  parts.slice(1).join(' '),
            job_title:  '',
            company:    '',
            location:   ''
        };

        // Company: any sibling link pointing to /companies/
        const companyLink = row.querySelector('a[href*="/companies/"]');
        if (companyLink) lead.company = (companyLink.textContent || '').trim();

        // Job title + location from table cells after the name cell
        const tds = Array.from(row.querySelectorAll('td'));
        const nameIdx = tds.findIndex(td => td.contains(link));
        for (let i = nameIdx + 1; i < tds.length; i++) {
            const td = tds[i];
            if (td.querySelector('button, input, svg')) continue;
            const text = (td.innerText || '').trim().split('\\n')[0].trim();
            if (!text || text.length > 80) continue;
            if (td.querySelector('a[href*="/companies/"]')) continue; // skip company cell
            if (!lead.job_title) { lead.job_title = text; continue; }
            if (!lead.location)  { lead.location  = text; break; }
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

    try:
        leads = await page.evaluate(_JS_EXTRACT)
        if leads:
            logger.info(f"JS extraction found {len(leads)} leads on this page")
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
                await page.wait_for_load_state("networkidle", timeout=15000)
                await asyncio.sleep(config.REQUEST_DELAY)
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
