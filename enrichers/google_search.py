"""
Step 3a — Serper + DuckDuckGo enricher.

Finds LinkedIn profile URL and company website for each lead.

LinkedIn search:
  Uses Serper.dev (Google Search API wrapper) as primary source.
  Falls back to DuckDuckGo if Serper is unavailable or key not set.

  Serper setup:
    1. Go to https://serper.dev → create a free account (2500 queries/month, no credit card)
    2. Copy the API key and set SERPER_API_KEY in .env

Company website search:
  Uses Clearbit Autocomplete first, DuckDuckGo as fallback (both free, no key).
"""
import logging
import re
import time
from typing import Optional
from urllib.parse import urlparse

import requests

import config

logger = logging.getLogger(__name__)

GOOGLE_SEARCH_URL = "https://customsearch.googleapis.com/customsearch/v1"

# Sites blocked when picking company website
_BLOCKED_DOMAINS = {
    "linkedin.com", "facebook.com", "twitter.com", "instagram.com",
    "youtube.com", "wikipedia.org", "glassdoor.com", "indeed.com",
    "crunchbase.com", "bloomberg.com", "forbes.com", "x.com",
}


# ── Serper.dev (LinkedIn search via Google index) ──────────────────────────────

SERPER_URL = "https://google.serper.dev/search"


def _serper_search(query: str) -> list[str]:
    """Search via Serper.dev (Google wrapper). Returns list of result URLs."""
    if not config.SERPER_API_KEY:
        return []
    try:
        resp = requests.post(
            SERPER_URL,
            headers={"X-API-KEY": config.SERPER_API_KEY, "Content-Type": "application/json"},
            json={"q": query, "num": 5},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        return [r.get("link", "") for r in data.get("organic", []) if r.get("link")]
    except requests.exceptions.HTTPError as e:
        if resp.status_code == 429:
            logger.warning("Serper rate limit hit. Waiting 60s...")
            time.sleep(60)
        else:
            logger.error(f"Serper HTTP error: {e}")
        return []
    except Exception as e:
        logger.error(f"Serper error: {e}")
        return []


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
            hit = results[0]
            domain = hit.get("domain", "")
            returned_name = hit.get("name", "").lower()
            # Validate: at least one significant word from the input must appear in returned name
            input_words = [w for w in company.lower().split() if len(w) > 3]
            if domain and input_words and any(w in returned_name for w in input_words):
                return f"https://{domain}"
            elif domain:
                logger.debug(f"Clearbit rejected '{returned_name}' for '{company}' (name mismatch)")
    except Exception as e:
        logger.error(f"Clearbit lookup error for '{company}': {e}")
    return None


def _ddg_search(query: str, max_results: int = 5, backend: str = "api") -> list[str]:
    """Search DuckDuckGo and return a list of result URLs (fallback)."""
    try:
        from duckduckgo_search import DDGS
        results = DDGS().text(query, max_results=max_results, backend=backend, safesearch="off")
        return [r.get("href", "") for r in results if r.get("href")]
    except Exception as e:
        logger.warning(f"DuckDuckGo search unavailable: {e}")
        return []


def _pick_linkedin_url(urls: list[str]) -> Optional[str]:
    """Return the first linkedin.com/in/ profile URL from a list of URLs."""
    for url in urls:
        if re.match(r"https?://(www\.)?linkedin\.com/in/", url):
            return url
    return None


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

    # Fallback: Serper
    if config.SERPER_API_KEY:
        logger.debug(f"Clearbit miss for '{company}', trying Serper...")
        urls = _serper_search(f"{company} official website")
        website = _pick_website(urls)
        if website:
            return website

    # Last resort: DuckDuckGo
    logger.debug(f"Serper miss for '{company}', trying DuckDuckGo...")
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

    # ── LinkedIn: Serper first, DuckDuckGo fallback ──────────────────────────
    linkedin_query = f'{first} {last} {company} site:linkedin.com/in'
    lead["linkedin_url"] = None

    serper_urls = _serper_search(linkedin_query)
    lead["linkedin_url"] = _pick_linkedin_url(serper_urls)
    if lead["linkedin_url"]:
        logger.debug(f"LinkedIn (Serper) found for {first} {last}: {lead['linkedin_url']}")

    if not lead["linkedin_url"]:
        logger.debug(f"Serper miss for {first} {last}, trying DuckDuckGo...")
        ddg_urls = _ddg_search(f'{first} {last} {company} site:linkedin.com/in', max_results=5, backend="html")
        lead["linkedin_url"] = _pick_linkedin_url(ddg_urls)
        if lead["linkedin_url"]:
            logger.debug(f"LinkedIn (DDG) found for {first} {last}: {lead['linkedin_url']}")
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


if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG, format="%(asctime)s [%(levelname)s] %(message)s")

    test_leads = [
        {"first_name": "Scott", "last_name": "Paschall", "job_title": "Company Owner", "company": "Custom Concrete Creations", "location": "O'Fallon, Missouri"},
        {"first_name": "Collen", "last_name": "Crosby", "job_title": "Owner", "company": "Crosby Roofing Columbia LLC", "location": "Lexington, South Carolina"},
        {"first_name": "Sandro", "last_name": "Mahler", "job_title": "Photography Teacher, Owner", "company": "CSIA", "location": "Cureglia, Switzerland"},
        {"first_name": "Arne", "last_name": "Kirchner", "job_title": "Director", "company": "Alp Financial", "location": "Lausanne, Switzerland"},
        {"first_name": "Stephane", "last_name": "Tyc", "job_title": "Co-founder", "company": "Quincy Data", "location": "Paris, France"},
    ]

    results = enrich_leads_google(test_leads)
    print("\n=== Results ===")
    for r in results:
        print(f"\n{r['first_name']} {r['last_name']} ({r['company']})")
        print(f"  LinkedIn : {r.get('linkedin_url')}")
        print(f"  Website  : {r.get('website')}")
