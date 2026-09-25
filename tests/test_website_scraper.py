"""
Tests for scrapers/website_scraper.py.

The real failure this pins (Astrak France, pilot run of 2026-08-11): a site
that is technically unreachable (DNS/timeout/connection refused/error status)
used to be indistinguishable from a site that answered 200 with an empty or
thin page. Both collapsed to `website_text = ""`, so `expected_sources`
counted the site as a silent source either way and capped the lead's
evidence_level at "weak" even when the only reason it had no text was that
the server never responded. See docs/superpowers/specs/2026-08-10-scoring-
icp-et-fiabilite-pipeline-design.md §4.2.
"""
import asyncio

import requests
from unittest.mock import patch

from enrichers.google_search import PageFetch
from scrapers.website_scraper import _html_to_text, _scrape_website, scrape_hit_leads


def _run(coro):
    return asyncio.run(coro)


class _OkResp:
    status_code = 200

    def __init__(self, text):
        self.text = text

    def raise_for_status(self):
        return None


def test_connection_error_marks_the_site_unreachable():
    with patch("scrapers.website_scraper.requests.get",
               side_effect=requests.exceptions.ConnectionError("DNS resolution failed")):
        text, unreachable = _run(_scrape_website("https://astrakgroup.fr"))
    assert text == ""
    assert unreachable is True


def test_timeout_marks_the_site_unreachable():
    with patch("scrapers.website_scraper.requests.get",
               side_effect=requests.exceptions.Timeout("timed out")):
        text, unreachable = _run(_scrape_website("https://slow.example"))
    assert text == ""
    assert unreachable is True


def test_error_status_marks_the_site_unreachable():
    class _ErrorResp:
        status_code = 500

        def raise_for_status(self):
            raise requests.exceptions.HTTPError("500 Server Error")

    with patch("scrapers.website_scraper.requests.get", return_value=_ErrorResp()):
        text, unreachable = _run(_scrape_website("https://broken.example"))
    assert text == ""
    assert unreachable is True


def test_reachable_but_empty_page_is_not_unreachable():
    """Joignable mais pauvre/vide must stay a distinct case from injoignable."""
    with patch("scrapers.website_scraper.requests.get",
               return_value=_OkResp("<html><body></body></html>")):
        text, unreachable = _run(_scrape_website("https://empty.example"))
    assert text == ""
    assert unreachable is False


def test_reachable_page_with_content_returns_text_and_not_unreachable():
    html = "<html><body><p>" + "Nous accompagnons les entreprises. " * 20 + "</p></body></html>"
    with patch("scrapers.website_scraper.requests.get", return_value=_OkResp(html)):
        text, unreachable = _run(_scrape_website("https://acme.example"))
    assert "accompagnons" in text
    assert unreachable is False


def test_no_url_at_all_is_not_unreachable():
    """A lead with no site URL never made a request — it is not a provider outage."""
    text, unreachable = _run(_scrape_website(""))
    assert text == ""
    assert unreachable is False

    text, unreachable = _run(_scrape_website(None))
    assert text == ""
    assert unreachable is False


def test_scrape_hit_leads_sets_website_unreachable_flag_per_lead():
    leads = [
        {"first_name": "A", "last_name": "B", "website": "https://down.example"},
        {"first_name": "C", "last_name": "D", "website": "https://up.example"},
        {"first_name": "E", "last_name": "F", "website": None},
    ]

    async def _fake_scrape(url):
        if url == "https://down.example":
            return "", True
        if url == "https://up.example":
            return "Texte suffisant " * 20, False
        return "", False

    with patch("scrapers.website_scraper._scrape_website", side_effect=_fake_scrape), \
         patch("scrapers.website_scraper.time.sleep", return_value=None):
        result = _run(scrape_hit_leads(leads))

    assert result[0]["website_unreachable"] is True
    assert result[0]["website_text"] == ""
    assert result[1]["website_unreachable"] is False
    assert result[1]["website_text"]
    assert result[2]["website_unreachable"] is False
    assert result[2]["website_text"] == ""


# ── Reusing the coherence-check fetch (step 3a') ─────────────────────────────

def test_scrape_hit_leads_reuses_cached_page_fetch_without_a_new_request():
    """A lead already carrying `_page_fetch` from verify_website must not
    trigger a second download of the same homepage.

    The `html` field, not `text`, is what the short-circuit re-derives
    `website_text` from (see `_html_to_text`), so it must carry the content
    the assertion below looks for. This is an adaptation of the original
    test, which asserted on a `text` field the implementation no longer
    reads for this path — the fix here makes the cached page's `text` and
    `html` agree, matching what a real `verify_website()` call produces.
    """
    page = PageFetch(
        url="https://acme.example",
        html="<html><body>" + "Acme " * 100 + "</body></html>",
        text="Acme " * 100,
        title="Acme",
        unreachable=False,
    )
    leads = [{"first_name": "A", "last_name": "B", "website": "https://acme.example",
              "_page_fetch": page}]

    with patch("scrapers.website_scraper._scrape_website") as mock_scrape:
        result = _run(scrape_hit_leads(leads))

    mock_scrape.assert_not_called()
    assert result[0]["website_unreachable"] is False
    assert "Acme" in result[0]["website_text"]
    assert result[0]["linkedin_text"] == ""


def test_scrape_hit_leads_reuses_cached_unreachable_fetch_without_a_new_request():
    """An unreachable fetch from the coherence check must also be reused,
    not retried a second time in the same run."""
    page = PageFetch(url="https://down.example", unreachable=True)
    leads = [{"first_name": "A", "last_name": "B", "website": "https://down.example",
              "_page_fetch": page}]

    with patch("scrapers.website_scraper._scrape_website") as mock_scrape:
        result = _run(scrape_hit_leads(leads))

    mock_scrape.assert_not_called()
    assert result[0]["website_unreachable"] is True
    assert result[0]["website_text"] == ""


def test_scrape_hit_leads_fetches_normally_when_no_cached_fetch_present():
    """A lead coming from a pool created before this change has no
    `_page_fetch` and must still be scraped the old way."""
    leads = [{"first_name": "A", "last_name": "B", "website": "https://acme.example"}]

    async def _fake_scrape(url):
        return "Fresh text " * 20, False

    with patch("scrapers.website_scraper._scrape_website", side_effect=_fake_scrape) as mock_scrape, \
         patch("scrapers.website_scraper.time.sleep", return_value=None):
        result = _run(scrape_hit_leads(leads))

    mock_scrape.assert_called_once_with("https://acme.example")
    assert result[0]["website_unreachable"] is False
    assert "Fresh text" in result[0]["website_text"]


# ── Text-extraction parity between the live fetch and the cached path ───────

def test_html_to_text_strips_noscript_and_comments():
    html = (
        "<html><head><title>Acme</title></head><body>"
        "<noscript>Veuillez activer JavaScript pour consulter ce site.</noscript>"
        "<!-- internal note: do not ship -->"
        "<p>Acme est une agence e-commerce a Casablanca.</p>"
        "</body></html>"
    )
    text = _html_to_text(html)
    assert "JavaScript" not in text
    assert "internal note" not in text
    assert "Acme est une agence e-commerce a Casablanca" in text


def test_html_to_text_on_empty_string_returns_empty_string():
    assert _html_to_text("") == ""


def test_cached_and_direct_paths_produce_identical_text_for_the_same_html():
    """Regression: the short-circuit used to reuse `cached.text`, which came
    from enrichers/google_search.py's lighter extraction (no noscript/comment
    stripping). Two leads scraped through different paths could then be
    scored from different text for the same page. Both paths must now go
    through `_html_to_text` and agree byte for byte."""
    html = (
        "<html><head><title>Acme</title></head><body>"
        "<noscript>Veuillez activer JavaScript pour consulter ce site.</noscript>"
        "<!-- internal note: do not ship -->"
        "<p>Acme est une agence e-commerce a Casablanca.</p>"
        "</body></html>"
    )

    direct_text = _html_to_text(html)[:4000]

    page = PageFetch(url="https://acme.example", html=html, text="irrelevant, must be ignored",
                      title="Acme", unreachable=False)
    leads = [{"first_name": "A", "last_name": "B", "website": "https://acme.example",
              "_page_fetch": page}]
    with patch("scrapers.website_scraper._scrape_website") as mock_scrape:
        result = _run(scrape_hit_leads(leads))
    mock_scrape.assert_not_called()
    cached_text = result[0]["website_text"]

    assert cached_text == direct_text
    assert "JavaScript" not in cached_text
    assert "internal note" not in cached_text
