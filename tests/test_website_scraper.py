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

from scrapers.website_scraper import _scrape_website, scrape_hit_leads


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
