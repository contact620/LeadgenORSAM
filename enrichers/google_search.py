"""
Step 3a — Google Custom Search API + DuckDuckGo enricher.

Finds LinkedIn profile URL and company website for each lead.

LinkedIn search:
  Uses Google Custom Search JSON API (free tier: 100 queries/day).
  CSE must be configured to search linkedin.com only.

  Setup:
    1. Go to https://console.cloud.google.com/ → Enable "Custom Search API"
    2. Get an API key and set GOOGLE_API_KEY in .env
    3. Go to https://programmablesearchengine.google.com/ → Create a search engine
       Add "linkedin.com" as the site to search
    4. Copy the CX ID and set GOOGLE_CX in .env

Company website search:
  Uses DuckDuckGo (free, no API key required) as fallback since Google CSE
  no longer supports searching the entire web.
"""
import logging
import re
import time
from typing import Optional
from urllib.parse import urlparse

import requests

import config

logger = logging.getLogger(__name__)

GOOGLE_SEARCH_URL = "https://www.googleapis.com/customsearch/v1"

# Sites blocked when picking company website
_BLOCKED_DOMAINS = {
    "linkedin.com", "facebook.com", "twitter.com", "instagram.com",
    "youtube.com", "wikipedia.org", "glassdoor.com", "indeed.com",
    "crunchbase.com", "bloomberg.com", "forbes.com", "x.com",
}


# ── Google CSE (LinkedIn only) ─────────────────────────────────────────────────

def _google_search(query: str) -> list[dict]:
    """Execute a Google Custom Search query. Returns list of result items."""
    if not config.GOOGLE_API_KEY or not config.GOOGLE_CX:
        logger.warning("GOOGLE_API_KEY or GOOGLE_CX not set. Skipping Google search.")
        return []

    params = {
        "key": config.GOOGLE_API_KEY,
        "cx": config.GOOGLE_CX,
        "q": query,
        "num": 5,
    }
    try:
        resp = requests.get(GOOGLE_SEARCH_URL, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        return data.get("items", [])
    except requests.exceptions.HTTPError as e:
        if resp.status_code == 429:
            logger.warning("Google API rate limit hit. Waiting 60s...")
            time.sleep(60)
        else:
            logger.error(f"Google Search HTTP error: {e}")
        return []
    except Exception as e:
        logger.error(f"Google Search error: {e}")
        return []


def _extract_linkedin_url(items: list[dict]) -> Optional[str]:
    """Pick the first LinkedIn people profile URL from results."""
    for item in items:
        link = item.get("link", "")
        if re.match(r"https?://(www\.)?linkedin\.com/in/", link):
            return link
    return None


# ── Clearbit Autocomplete (company website) ────────────────────────────────────
# Free, no API key required. Returns company domain directly.

CLEARBIT_URL = "https://autocomplete.clearbit.com/v1/companies/suggest"


def _clearbit_domain(company: str) -> Optional[str]:
    """Look up company domain via Clearbit Autocomplete (free, no key needed)."""
    try:
        resp = requests.get(
            CLEARBIT_URL,
            params={"query": company},
            timeout=8,
            headers={"User-Agent": "Mozilla/5.0"},
        )
        resp.raise_for_status()
        results = resp.json()
        if results:
            domain = results[0].get("domain", "")
            if domain:
                return f"https://{domain}"
    except Exception as e:
        logger.error(f"Clearbit lookup error for '{company}': {e}")
    return None


def _ddg_search(query: str, max_results: int = 5) -> list[str]:
    """Search DuckDuckGo and return a list of result URLs (fallback)."""
    try:
        from duckduckgo_search import DDGS
        from duckduckgo_search.exceptions import RatelimitException
        results = DDGS().text(query, max_results=max_results)
        return [r.get("href", "") for r in results if r.get("href")]
    except Exception as e:
        logger.warning(f"DuckDuckGo search unavailable: {e}")
        return []


def _pick_website(urls: list[str]) -> Optional[str]:
    """Return the first URL that doesn't belong to a blocked domain."""
    for url in urls:
        try:
            domain = urlparse(url).netloc.lower().lstrip("www.")
            if not any(b in domain for b in _BLOCKED_DOMAINS):
                return url
        except Exception:
            continue
    return None


def _find_company_website(company: str) -> Optional[str]:
    """Find company website: Clearbit first, DuckDuckGo as fallback."""
    website = _clearbit_domain(company)
    if website:
        logger.debug(f"Clearbit domain found for '{company}': {website}")
        return website

    # Fallback: DuckDuckGo
    logger.debug(f"Clearbit miss for '{company}', trying DuckDuckGo...")
    urls = _ddg_search(f"{company} official website")
    return _pick_website(urls)


# ── Main enrichment logic ──────────────────────────────────────────────────────

def find_linkedin_and_website(lead: dict) -> dict:
    """
    Enriches a lead dict with linkedin_url and website.

    LinkedIn → Google CSE restricted to linkedin.com
    Website  → DuckDuckGo (free, no API key required)

    Args:
        lead: dict with at least first_name, last_name, company.

    Returns:
        Same dict updated with linkedin_url and website (may be None).
    """
    first = lead.get("first_name", "")
    last = lead.get("last_name", "")
    company = lead.get("company", "")

    # ── LinkedIn via Google CSE ───────────────────────────────────────────────
    linkedin_query = f'{first} {last} {company} site:linkedin.com/in'
    li_items = _google_search(linkedin_query)
    lead["linkedin_url"] = _extract_linkedin_url(li_items)
    if lead["linkedin_url"]:
        logger.debug(f"LinkedIn found for {first} {last}: {lead['linkedin_url']}")
    else:
        logger.debug(f"No LinkedIn found for {first} {last}")

    time.sleep(config.REQUEST_DELAY / 2)

    # ── Website via Clearbit (+ DuckDuckGo fallback) ─────────────────────────
    if company:
        lead["website"] = _find_company_website(company)
        if lead["website"]:
            logger.debug(f"Website found for {company}: {lead['website']}")
        else:
            logger.debug(f"No website found for {company}")
    else:
        lead["website"] = None

    time.sleep(config.REQUEST_DELAY / 2)

    return lead


def enrich_leads_google(leads: list[dict]) -> list[dict]:
    """
    Enrich a list of leads with LinkedIn URLs and company websites.
    Runs sequentially with rate limiting to avoid hitting API quotas.
    """
    total = len(leads)
    for i, lead in enumerate(leads, 1):
        logger.info(f"Google enrichment [{i}/{total}]: {lead.get('first_name')} {lead.get('last_name')}")
        find_linkedin_and_website(lead)
    return leads
