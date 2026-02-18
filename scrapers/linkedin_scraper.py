"""
Step 5a — LinkedIn profile + company website scraper (for hit leads only).

LinkedIn scraping uses Playwright with session cookies to access profiles.
Website scraping uses requests with BeautifulSoup fallback.

Note: LinkedIn is the most restrictive platform. To avoid blocks:
  - Use real session cookies (li_at + JSESSIONID)
  - Keep delays between requests
  - Do not scrape too many profiles per session
"""
import asyncio
import logging
import re
import time
from typing import Optional

import requests
from playwright.async_api import async_playwright, Page

import config

logger = logging.getLogger(__name__)

# Max characters of text to pass to GPT (keep costs low)
MAX_LINKEDIN_TEXT = 3000
MAX_WEBSITE_TEXT = 2000


# ── LinkedIn scraping ─────────────────────────────────────────────────────────

async def _scrape_linkedin_profile(page: Page, linkedin_url: str) -> str:
    """Scrape a LinkedIn profile page and return its text content."""
    try:
        await page.goto(linkedin_url, wait_until="domcontentloaded", timeout=20000)
        await asyncio.sleep(3)

        # Check if we hit an auth wall / captcha
        current_url = page.url
        if "authwall" in current_url or "login" in current_url:
            logger.warning(f"LinkedIn auth wall hit for {linkedin_url}")
            return ""

        # Extract text from the main profile sections
        sections = []

        # Headline / summary
        for sel in [
            ".pv-text-details__left-panel",
            ".ph5.pb5",
            "[data-generated-suggestion-target]",
            ".artdeco-card",
        ]:
            try:
                el = page.locator(sel).first
                if await el.count() > 0:
                    text = await el.inner_text(timeout=3000)
                    sections.append(text.strip())
            except Exception:
                pass

        # Experience section
        for sel in ["#experience", "[id='experience']", "section[data-section='experience']"]:
            try:
                el = page.locator(sel).first
                if await el.count() > 0:
                    text = await el.inner_text(timeout=3000)
                    sections.append(text.strip())
                    break
            except Exception:
                pass

        # About section
        for sel in ["#about", "[id='about']"]:
            try:
                el = page.locator(sel).first
                if await el.count() > 0:
                    text = await el.inner_text(timeout=3000)
                    sections.append(text.strip())
                    break
            except Exception:
                pass

        full_text = "\n\n".join(s for s in sections if s)

        if not full_text:
            # Fallback: grab everything from <main>
            try:
                full_text = await page.locator("main").first.inner_text(timeout=5000)
            except Exception:
                full_text = await page.content()

        # Trim and clean
        full_text = re.sub(r"\n{3,}", "\n\n", full_text).strip()
        return full_text[:MAX_LINKEDIN_TEXT]

    except Exception as e:
        logger.error(f"LinkedIn scrape error for {linkedin_url}: {e}")
        return ""


async def _scrape_website(url: str) -> str:
    """Scrape a company website homepage and return visible text."""
    if not url:
        return ""
    try:
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            )
        }
        resp = requests.get(url, headers=headers, timeout=10, allow_redirects=True)
        resp.raise_for_status()
        html = resp.text

        # Simple text extraction without BeautifulSoup dependency
        # Remove scripts, styles, tags
        text = re.sub(r"<script[^>]*>.*?</script>", " ", html, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"<style[^>]*>.*?</style>", " ", text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"&[a-zA-Z]+;", " ", text)
        text = re.sub(r"\s{2,}", " ", text).strip()
        return text[:MAX_WEBSITE_TEXT]
    except Exception as e:
        logger.error(f"Website scrape error for {url}: {e}")
        return ""


async def scrape_hit_leads(hit_leads: list[dict]) -> list[dict]:
    """
    For each hit lead, scrape their LinkedIn profile and company website.
    Stores raw text in lead["linkedin_text"] and lead["website_text"].
    """
    if not hit_leads:
        return hit_leads

    li_cookies = config.load_cookies(config.LINKEDIN_COOKIES_PATH)

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],
        )
        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1440, "height": 900},
        )

        if li_cookies:
            await context.add_cookies(li_cookies)
        else:
            logger.warning(
                "No LinkedIn cookies found. LinkedIn profiles may not be accessible. "
                "Copy linkedin_cookies.json.example → linkedin_cookies.json and fill in li_at."
            )

        await context.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', { get: () => undefined });"
        )

        page = await context.new_page()
        total = len(hit_leads)

        for i, lead in enumerate(hit_leads, 1):
            name = f"{lead.get('first_name', '')} {lead.get('last_name', '')}".strip()
            logger.info(f"Scraping hit lead [{i}/{total}]: {name}")

            # LinkedIn profile
            li_url = lead.get("linkedin_url")
            if li_url:
                lead["linkedin_text"] = await _scrape_linkedin_profile(page, li_url)
                await asyncio.sleep(config.REQUEST_DELAY)
            else:
                lead["linkedin_text"] = ""

            # Company website
            website = lead.get("website")
            lead["website_text"] = await _scrape_website(website)

            await asyncio.sleep(config.REQUEST_DELAY / 2)

        await browser.close()

    logger.info(f"Scraping complete for {total} hit leads.")
    return hit_leads
