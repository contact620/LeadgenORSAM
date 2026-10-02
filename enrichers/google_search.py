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
from dataclasses import dataclass
from html import unescape as html_unescape
from typing import Optional
from urllib.parse import urlparse

import requests

import config
from api.provider_status import ProviderRegistry, StepOutcome
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


@dataclass(frozen=True)
class SearchHit:
    """One organic Serper result, title and snippet included.

    Only `link` used to survive the call. The title and the snippet of a
    `site:linkedin.com/in` search are Google's index of the profile and of the
    person's posts — current role, employer, the headline of what they publish
    — and they were thrown away on every lead. Keeping them is free: no extra
    request, and no LinkedIn page is ever fetched (see
    scrapers/website_scraper.py, which forces linkedin_text = "" so the account
    does not get banned).
    """
    link: str = ""
    title: str = ""
    snippet: str = ""


def _serper_search(query: str) -> list[SearchHit]:
    """Search via Serper.dev (Google wrapper) with retry. Returns organic hits."""
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
        return [
            SearchHit(
                link=r.get("link") or "",
                title=(r.get("title") or "").strip(),
                snippet=(r.get("snippet") or "").strip(),
            )
            for r in data.get("organic", []) or []
            if r.get("link")
        ]

    try:
        return retry_api_call(_do_request, max_retries=3, operation_name="Serper search")
    except AuthError as e:
        _serper_disabled = True
        logger.error(f"Serper auth failed — disabled for this run: {e}")
        return []
    except Exception as e:
        logger.warning(f"Serper search failed after retries: {e}")
        return []


def _links(hits: list) -> list[str]:
    """URLs of a result list, whatever the backend returned.

    Serper yields SearchHit objects and DuckDuckGo yields bare strings; the two
    pickers below only ever need the URL.
    """
    return [h.link if isinstance(h, SearchHit) else str(h) for h in hits if h]


# Upper bound on the person material kept per lead. Google snippets run ~200
# characters each and five results are requested; the bound exists so a
# pathological answer cannot grow the fact-extraction prompt without limit.
MAX_PERSON_SNIPPET_CHARS = 2000


def person_snippets(hits: list[SearchHit], max_chars: int = MAX_PERSON_SNIPPET_CHARS) -> str:
    """Lay out the LinkedIn search results as readable source text, or "".

    Every line keeps its URL, because the fact extractor is required to source
    each fact it reports and must be able to point at the page it read.
    """
    blocks = []
    for hit in hits:
        if not isinstance(hit, SearchHit) or not (hit.title or hit.snippet):
            continue
        parts = [p for p in (hit.title, hit.snippet) if p]
        blocks.append(f"- {' — '.join(parts)} ({hit.link})")
    return "\n".join(blocks)[:max_chars]


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
        website = _pick_website(_links(_serper_search(query)))
        if website:
            return website

    logger.debug(f"Serper miss for '{company}', trying DuckDuckGo...")
    return _pick_website(_ddg_search(query))


_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
_TAG_RE = re.compile(r"<[^>]+>")

# Upper bound on the text handed to the coherence check. It used to be 1500
# characters, which stopped short of the footer where a French SME states its
# legal name — the check then reported the name as absent and rejected a
# perfectly valid site. The bound now only guards against a pathological
# page; it is not a sampling window.
MAX_PAGE_TEXT_CHARS = 200_000


def _light_page_text(html: str) -> tuple[str, str]:
    """Extract (title, full plain text) from raw HTML without a parser dependency.

    Deliberately lighter than scrapers/website_scraper.py::_html_to_text (no
    <noscript>/comment stripping): this feeds the coherence check, whose job
    is to recognise a company name wherever it appears on the page, not to
    produce clean text for a fact extractor. Do not merge the two — a name
    that only appears inside an HTML comment must keep counting as found here.

    Entities are unescaped, always after the tags are gone so that an escaped
    "&lt;script&gt;" never becomes a tag we then fail to strip. Leaving them in
    was not cosmetic: the title "SkyCrew &#8211; Fly with us" kept "8211" as a
    token, which inflated the denominator of the overlap ratio and helped push
    a legitimate domain below the acceptance threshold.
    """
    title_match = _TITLE_RE.search(html)
    title = _TAG_RE.sub(" ", title_match.group(1)) if title_match else ""
    title = re.sub(r"\s{2,}", " ", html_unescape(title)).strip()

    body = re.sub(r"<script[^>]*>.*?</script>", " ", html, flags=re.DOTALL | re.IGNORECASE)
    body = re.sub(r"<style[^>]*>.*?</style>", " ", body, flags=re.DOTALL | re.IGNORECASE)
    body = _TAG_RE.sub(" ", body)
    body = html_unescape(body)
    # Safety net for an entity html.unescape does not know; after unescape so
    # it only ever sees what is left.
    body = re.sub(r"&[a-zA-Z]+;", " ", body)
    body = re.sub(r"\s{2,}", " ", body).strip()
    return title, body[:MAX_PAGE_TEXT_CHARS]


@dataclass(frozen=True)
class PageFetch:
    """One homepage fetch, kept for every downstream consumer.

    The coherence check (step 3a') already downloads this page. Contact
    extraction (step 3d) and evidence collection (step 5) used to download it
    again — three requests per lead for one document, three chances to be rate
    limited or to read a different version of the page than the one we scored.
    """
    url: str = ""
    html: str = ""
    text: str = ""
    title: str = ""
    unreachable: bool = False


def verify_website(url: str, company: str) -> tuple[CoherenceResult, PageFetch]:
    """
    Cheap homepage fetch to confirm the domain belongs to the prospect's company.

    Runs before the hit score so an unrelated site never earns its 10 points.
    A failed fetch is inconclusive, never a rejection.

    Returns the coherence verdict alongside the fetched page so downstream
    consumers (contact extraction, evidence collection) can reuse it instead
    of downloading the same homepage again.
    """
    if not url:
        return (CoherenceResult(coherent=True, verified=False, reason="aucun site à vérifier"),
                PageFetch())
    try:
        resp = requests.get(
            url,
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=8,
            allow_redirects=True,
        )
        resp.raise_for_status()
        html = resp.text
        title, text = _light_page_text(html)
    except Exception as e:
        logger.debug(f"Light website check failed for {url}: {e}")
        return (CoherenceResult(coherent=True, verified=False, reason="site injoignable"),
                PageFetch(url=url, unreachable=True))

    return (check_site_coherence(company, title, text, url=url),
            PageFetch(url=url, html=html, text=text, title=title, unreachable=False))


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
    # linkedin_snippets is the indexed text harvested from the search below,
    # kept as source material on the person. It stays empty when Apollo already
    # supplied the profile URL: no search runs in that case, and the point of
    # this material is that it costs no extra call.
    lead.setdefault("linkedin_snippets", "")
    linkedin_query = f'{first} {last} {company} site:linkedin.com/in'
    if lead.get("linkedin_url"):
        logger.debug(f"LinkedIn already set from Apollo for {first} {last}: {lead['linkedin_url']}")
    else:
        lead["linkedin_url"] = None

        serper_hits = _serper_search(linkedin_query)
        # Harvested whether or not a profile URL could be picked out of them:
        # a search that returns the person's posts but no /in/ profile still
        # says what they do.
        lead["linkedin_snippets"] = person_snippets(serper_hits)
        lead["linkedin_url"] = _pick_linkedin_url(_links(serper_hits))
        if lead["linkedin_url"]:
            logger.debug(f"LinkedIn (Serper) found for {first} {last}: {lead['linkedin_url']}")

        if not lead["linkedin_url"]:
            logger.debug(f"Serper miss for {first} {last}, trying DuckDuckGo...")
            ddg_urls = _ddg_search(f'{first} {last} {company} site:linkedin.com/in', max_results=5)
            lead["linkedin_url"] = _pick_linkedin_url(_links(ddg_urls))
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
            check, page = verify_website(candidate, company)
            lead["_page_fetch"] = page
            lead["website_unreachable"] = page.unreachable
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
            lead["website_check_reason"] = "aucun site candidat trouvé"
            logger.debug(f"No website found for {company}")
    else:
        lead["website"] = None
        lead["website_coherent"] = False
        lead["website_check_reason"] = "aucun nom d'entreprise fourni"

    time.sleep(config.REQUEST_DELAY / 2)

    return lead


def enrich_leads_google(leads: list[dict], registry: ProviderRegistry | None = None) -> list[dict]:
    """
    Enrich a list of leads with LinkedIn URLs and company websites.
    Runs sequentially with rate limiting to avoid hitting API quotas.

    Records a Serper outcome on `registry`: an expired key disables LinkedIn
    search for the whole run and costs 30 hit-score points per lead, which
    used to leave a portfolio just under the threshold with nothing anywhere
    saying why.
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

    if registry:
        registry.record(_serper_outcome(len(no_linkedin), linkedin_found))

    return leads


def _serper_outcome(missing_linkedin: int, linkedin_found: int) -> StepOutcome:
    """Turn Serper's end-of-run state into a reportable outcome.

    - skipped  : no key configured; DuckDuckGo carried the searches alone.
    - degraded : the key was rejected mid-run (see _serper_disabled), so every
                 remaining LinkedIn lookup fell through to the fallback.
    - ok       : the provider answered for the whole run.
    """
    if config._is_placeholder(config.SERPER_API_KEY):
        return StepOutcome("serper", "skipped", "clé API absente", 0)
    if _serper_disabled:
        return StepOutcome(
            "serper", "degraded",
            "clé rejetée en cours de run — recherche LinkedIn repliée sur DuckDuckGo",
            missing_linkedin,
        )
    return StepOutcome("serper", "ok", None, linkedin_found)


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
