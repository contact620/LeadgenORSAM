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
from enrichers.retry import retry_api_call, AuthError
from processors.coherence import CoherenceResult, check_site_coherence, names_match, strip_www

logger = logging.getLogger(__name__)

# Sites blocked when picking company website
_BLOCKED_DOMAINS = {
    "linkedin.com", "facebook.com", "twitter.com", "instagram.com",
    "youtube.com", "wikipedia.org", "glassdoor.com", "indeed.com",
    "crunchbase.com", "bloomberg.com", "forbes.com", "x.com",
}


# ── Serper.dev (LinkedIn search via Google index) ──────────────────────────────

SERPER_URL = "https://google.serper.dev/search"


_serper_disabled = False


def _reset_state():
    """Reset module state between pipeline runs."""
    global _serper_disabled
    _serper_disabled = False


def _serper_search(query: str) -> list[str]:
    """Search via Serper.dev (Google wrapper) with retry. Returns list of result URLs."""
    global _serper_disabled
    if config._is_placeholder(config.SERPER_API_KEY) or _serper_disabled:
        return []

    def _do_request():
        resp = requests.post(
            SERPER_URL,
            headers={"X-API-KEY": config.SERPER_API_KEY, "Content-Type": "application/json"},
            json={"q": query, "num": 5},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        return [r.get("link", "") for r in data.get("organic", []) if r.get("link")]

    try:
        return retry_api_call(_do_request, max_retries=3, operation_name="Serper search")
    except AuthError as e:
        _serper_disabled = True
        logger.error(f"Serper auth failed — disabled for this run: {e}")
        return []
    except Exception as e:
        logger.warning(f"Serper search failed after retries: {e}")
        return []


# ── Clearbit Autocomplete (company website) ────────────────────────────────────
# Free, no API key required. Returns company domain directly.

CLEARBIT_URL = "https://autocomplete.clearbit.com/v1/companies/suggest"


def _clearbit_domain(company: str) -> Optional[str]:
    """Look up company domain via Clearbit Autocomplete (free, no key needed) with retry."""
    def _do_request():
        resp = requests.get(
            CLEARBIT_URL,
            params={"query": company},
            timeout=8,
            headers={"User-Agent": "Mozilla/5.0"},
        )
        resp.raise_for_status()
        return resp.json()

    try:
        results = retry_api_call(_do_request, max_retries=2, operation_name=f"Clearbit ({company})")
    except Exception as e:
        logger.error(f"Clearbit lookup error for '{company}': {e}")
        return None

    for hit in results or []:
        domain = (hit.get("domain") or "").strip()
        returned_name = (hit.get("name") or "").strip()
        if not domain:
            continue
        if names_match(returned_name, company):
            return f"https://{domain}"
        logger.debug(
            f"Clearbit rejected '{returned_name}' ({domain}) for '{company}' (name mismatch)"
        )
    return None


def _ddg_search(query: str, max_results: int = 5, backend: str = "auto") -> list[str]:
    """Search DuckDuckGo with retry. Returns list of result URLs (fallback)."""
    def _do_search():
        from ddgs import DDGS
        results = DDGS().text(query, max_results=max_results, backend=backend, safesearch="off")
        return [r.get("href", "") for r in results if r.get("href")]

    try:
        return retry_api_call(_do_search, max_retries=2, operation_name="DuckDuckGo search")
    except Exception as e:
        logger.warning(f"DuckDuckGo search unavailable after retries: {e}")
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
            domain = strip_www(urlparse(url).netloc)
            if not any(b in domain for b in _BLOCKED_DOMAINS):
                return url
        except Exception:
            continue
    return None


def _find_company_website(company: str, location: str = "") -> Optional[str]:
    """Find company website: Clearbit first, Serper then DuckDuckGo as fallback."""
    website = _clearbit_domain(company)
    if website:
        logger.debug(f"Clearbit domain found for '{company}': {website}")
        return website

    # Location narrows the search and keeps homonymous foreign companies out.
    locality = (location or "").strip()
    query = f"{company} {locality} site officiel".strip() if locality else f"{company} official website"

    if not config._is_placeholder(config.SERPER_API_KEY):
        logger.debug(f"Clearbit miss for '{company}', trying Serper...")
        website = _pick_website(_serper_search(query))
        if website:
            return website

    logger.debug(f"Serper miss for '{company}', trying DuckDuckGo...")
    return _pick_website(_ddg_search(query))


_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
_TAG_RE = re.compile(r"<[^>]+>")
LIGHT_CHECK_MAX_CHARS = 1500


def _light_page_text(html: str) -> tuple[str, str]:
    """Extract (title, plain text head) from raw HTML without a parser dependency."""
    title_match = _TITLE_RE.search(html)
    title = _TAG_RE.sub(" ", title_match.group(1)).strip() if title_match else ""

    body = re.sub(r"<script[^>]*>.*?</script>", " ", html, flags=re.DOTALL | re.IGNORECASE)
    body = re.sub(r"<style[^>]*>.*?</style>", " ", body, flags=re.DOTALL | re.IGNORECASE)
    body = _TAG_RE.sub(" ", body)
    body = re.sub(r"&[a-zA-Z]+;", " ", body)
    body = re.sub(r"\s{2,}", " ", body).strip()
    return title, body[:LIGHT_CHECK_MAX_CHARS]


def verify_website(url: str, company: str, location: str) -> CoherenceResult:
    """
    Cheap homepage fetch to confirm the domain belongs to the prospect's company.

    Runs before the hit score so an unrelated site never earns its 10 points.
    A failed fetch is inconclusive, never a rejection.
    """
    if not url:
        return CoherenceResult(coherent=True, verified=False, reason="aucun site à vérifier")
    try:
        resp = requests.get(
            url,
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=8,
            allow_redirects=True,
        )
        resp.raise_for_status()
        title, text = _light_page_text(resp.text)
    except Exception as e:
        logger.debug(f"Light website check failed for {url}: {e}")
        return CoherenceResult(coherent=True, verified=False, reason="site injoignable")

    return check_site_coherence(company, location, title, text)


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

    # ── LinkedIn: skip if already scraped from Apollo ────────────────────────
    linkedin_query = f'{first} {last} {company} site:linkedin.com/in'
    if lead.get("linkedin_url"):
        logger.debug(f"LinkedIn already set from Apollo for {first} {last}: {lead['linkedin_url']}")
    else:
        lead["linkedin_url"] = None

        serper_urls = _serper_search(linkedin_query)
        lead["linkedin_url"] = _pick_linkedin_url(serper_urls)
        if lead["linkedin_url"]:
            logger.debug(f"LinkedIn (Serper) found for {first} {last}: {lead['linkedin_url']}")

        if not lead["linkedin_url"]:
            logger.debug(f"Serper miss for {first} {last}, trying DuckDuckGo...")
            ddg_urls = _ddg_search(f'{first} {last} {company} site:linkedin.com/in', max_results=5)
            lead["linkedin_url"] = _pick_linkedin_url(ddg_urls)
            if lead["linkedin_url"]:
                logger.debug(f"LinkedIn (DDG) found for {first} {last}: {lead['linkedin_url']}")
            else:
                logger.debug(f"No LinkedIn found for {first} {last}")

    time.sleep(config.REQUEST_DELAY / 2)

    # ── Website via Clearbit (+ Serper / DuckDuckGo fallback) ────────────────
    lead["website_rejected"] = None
    lead["website_check_reason"] = None
    if company:
        candidate = _find_company_website(company, lead.get("location", ""))
        if candidate:
            check = verify_website(candidate, company, lead.get("location", ""))
            lead["website_coherent"] = check.coherent
            lead["website_check_reason"] = check.reason
            if check.coherent:
                lead["website"] = candidate
                logger.debug(f"Website accepted for {company}: {candidate}")
            else:
                lead["website"] = None
                lead["website_rejected"] = candidate
                logger.info(f"Website rejected for '{company}': {candidate} — {check.reason}")
        else:
            lead["website"] = None
            lead["website_coherent"] = False
            logger.debug(f"No website found for {company}")
    else:
        lead["website"] = None
        lead["website_coherent"] = False

    time.sleep(config.REQUEST_DELAY / 2)

    return lead


def enrich_leads_google(leads: list[dict]) -> list[dict]:
    """
    Enrich a list of leads with LinkedIn URLs and company websites.
    Runs sequentially with rate limiting to avoid hitting API quotas.
    """
    total = len(leads)
    # Count LinkedIn URLs already present from Apollo before enrichment
    linkedin_from_apollo = sum(1 for l in leads if l.get("linkedin_url"))

    for i, lead in enumerate(leads, 1):
        logger.info(f"Google enrichment [{i}/{total}]: {lead.get('first_name')} {lead.get('last_name')}")
        find_linkedin_and_website(lead)

    # Summary
    linkedin_found = sum(1 for l in leads if l.get("linkedin_url"))
    linkedin_new = linkedin_found - linkedin_from_apollo
    website_found = sum(1 for l in leads if l.get("website"))
    no_linkedin = [l for l in leads if not l.get("linkedin_url")]
    no_website = [l for l in leads if not l.get("website")]

    logger.info(
        f"Google enrichment complete: "
        f"{linkedin_found}/{total} LinkedIn ({linkedin_from_apollo} from Apollo, {linkedin_new} new), "
        f"{website_found}/{total} websites"
    )
    if no_linkedin:
        names = ", ".join(f"{l.get('first_name')} {l.get('last_name')}" for l in no_linkedin[:5])
        suffix = f" (+{len(no_linkedin) - 5} others)" if len(no_linkedin) > 5 else ""
        logger.info(f"No LinkedIn found for: {names}{suffix}")
    if no_website:
        names = ", ".join(f"{l.get('company', '?')}" for l in no_website[:5])
        suffix = f" (+{len(no_website) - 5} others)" if len(no_website) > 5 else ""
        logger.info(f"No website found for: {names}{suffix}")

    rejected = [l for l in leads if l.get("website_rejected")]
    if rejected:
        logger.info(
            f"Websites rejected for incoherence: {len(rejected)} "
            f"({', '.join(l.get('company', '?') for l in rejected[:5])})"
        )

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
