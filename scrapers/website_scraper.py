"""
Step 5a — Company website scraper (for hit leads only).

Scrapes company websites using requests to extract text content
that will be passed to the AI enrichment step.
"""
import logging
import re
import time

import requests

import config

logger = logging.getLogger(__name__)

MAX_WEBSITE_TEXT = 2000


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
    For each hit lead, scrape their company website.
    Stores raw text in lead["website_text"].
    """
    if not hit_leads:
        return hit_leads

    total = len(hit_leads)

    for i, lead in enumerate(hit_leads, 1):
        name = f"{lead.get('first_name', '')} {lead.get('last_name', '')}".strip()
        logger.info(f"Scraping hit lead [{i}/{total}]: {name}")

        # LinkedIn text — not scraped (risk of account ban), set empty
        lead["linkedin_text"] = ""

        # Company website
        website = lead.get("website")
        lead["website_text"] = await _scrape_website(website)

        time.sleep(config.REQUEST_DELAY / 2)

    logger.info(f"Website scraping complete for {total} hit leads.")
    return hit_leads
