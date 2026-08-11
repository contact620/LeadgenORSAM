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

MAX_WEBSITE_TEXT = 4000

# Phrases that bloat the scraped text without providing business signal.
# Filtering them lets the LLM focus on the actual company description.
_NOISE_PATTERNS = [
    r"(?i)accept(er|ing)? (all )?cookies?",
    r"(?i)nous (et nos partenaires )?utilisons des cookies",
    r"(?i)this (web)?site uses cookies",
    r"(?i)privacy policy",
    r"(?i)politique de confidentialit[eé]",
    r"(?i)mentions? l[eé]gales?",
    r"(?i)conditions g[eé]n[eé]rales",
    r"(?i)tous droits r[eé]serv[eé]s?",
    r"(?i)all rights reserved",
    r"(?i)© ?\d{4}",
    r"(?i)gdpr|rgpd",
]
_NOISE_RE = re.compile("|".join(_NOISE_PATTERNS))


def _strip_noise(text: str) -> str:
    """Remove cookie banners, legal footers, and other low-signal repeats."""
    cleaned = _NOISE_RE.sub(" ", text)
    return re.sub(r"\s{2,}", " ", cleaned).strip()


async def _scrape_website(url: str) -> tuple[str, bool]:
    """Scrape a company website homepage and return (text, unreachable).

    ``unreachable=True`` means the HTTP request itself failed — network
    error, DNS failure, timeout, connection refused, or an error status via
    ``raise_for_status`` — which is a provider outage for this lead, not a
    source that spoke and had nothing to say. A page that answers 200 with
    little or no usable text is the opposite case: reachable but poor, so it
    returns ``unreachable=False`` even with empty text. Conflating the two
    used to make a lead's site an indistinguishable "no evidence" regardless
    of which one happened (see docs/superpowers/specs/2026-08-10-scoring-icp-et
    -fiabilite-pipeline-design.md §4.2).

    A lead with no URL at all is neither reachable nor unreachable — it never
    made a request — so it also returns ``unreachable=False``.
    """
    if not url:
        return "", False
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
    except requests.exceptions.RequestException as e:
        logger.error(f"Website unreachable for {url}: {e}")
        return "", True
    except Exception as e:
        logger.error(f"Website scrape error for {url}: {e}")
        return "", False

    # Simple text extraction without BeautifulSoup dependency
    # Remove scripts, styles, tags
    text = re.sub(r"<script[^>]*>.*?</script>", " ", html, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<style[^>]*>.*?</style>", " ", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<noscript[^>]*>.*?</noscript>", " ", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<!--.*?-->", " ", text, flags=re.DOTALL)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"&[a-zA-Z]+;", " ", text)
    text = re.sub(r"\s{2,}", " ", text).strip()
    text = _strip_noise(text)
    return text[:MAX_WEBSITE_TEXT], False


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
        text, unreachable = await _scrape_website(website)
        lead["website_text"] = text
        lead["website_unreachable"] = unreachable

        time.sleep(config.REQUEST_DELAY / 2)

    logger.info(f"Website scraping complete for {total} hit leads.")
    return hit_leads
