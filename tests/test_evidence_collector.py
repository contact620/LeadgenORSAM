"""
Tests for enrichers/evidence_collector.py.

The critical case here is the async/sync split: `collect_evidence` (blocking)
owns and closes its own event loop, while `collect_evidence_async` (coroutine)
must be awaitable from a caller that is itself already running inside an
event loop — e.g. main.py's `run_pipeline`, driven by `asyncio.run`. Calling
`loop.run_until_complete(...)` on a *new* loop from within a coroutine already
running on another loop raises `RuntimeError: Cannot run the event loop while
another loop is running` (asyncio's reentrancy guard is thread-global, not
scoped to the loop instance). `test_async_form_is_awaitable_from_a_running_loop`
is the regression test for that: it fails if `collect_evidence_async` is ever
changed back to call `run_until_complete` internally.
"""
import asyncio
from unittest.mock import patch

import pytest

import config
from enrichers import perplexity_enricher
from enrichers.evidence_collector import collect_evidence, collect_evidence_async


def _leads(n=2):
    return [
        {"first_name": f"A{i}", "last_name": "B", "company": "Acme", "website": "https://acme.example"}
        for i in range(n)
    ]


async def _fake_scrape_hit_leads(leads):
    """Stand-in for scrapers.website_scraper.scrape_hit_leads — no network."""
    for lead in leads:
        lead["website_text"] = "Texte de site suffisant." * 20
    return leads


def _fake_enrich_ok(leads, enrich_instructions="", registry=None):
    """Stand-in for a healthy Perplexity call."""
    for lead in leads:
        lead["digital_maturity"] = "Score: 3/10"
        lead["estimated_budget"] = "10 employés"
        lead["business_signals"] = "Recrutement en cours"
    return leads


def _fake_enrich_disabled(leads, enrich_instructions="", registry=None):
    """Stand-in for a Perplexity call whose key got rejected mid-run."""
    perplexity_enricher._perplexity_disabled = True
    for lead in leads:
        lead["digital_maturity"] = None
        lead["estimated_budget"] = None
        lead["business_signals"] = None
    return leads


@pytest.fixture(autouse=True)
def _reset_perplexity_state():
    perplexity_enricher._reset_state()
    yield
    perplexity_enricher._reset_state()


def test_collect_evidence_works_from_a_synchronous_context():
    """The blocking form must be callable from plain sync code (threaded pipeline runner)."""
    with patch("scrapers.website_scraper.scrape_hit_leads", _fake_scrape_hit_leads), \
         patch("enrichers.evidence_collector.config.PERPLEXITY_API_KEY", "real-key"), \
         patch.object(perplexity_enricher, "enrich_leads_perplexity", _fake_enrich_ok):
        leads, active = collect_evidence(_leads())

    assert active == frozenset({"website", "perplexity"})
    assert all(l["website_text"] for l in leads)


def test_async_form_is_awaitable_from_a_running_loop():
    """
    Regression test: this reproduces main.py's call site — an `await` inside a
    coroutine that `asyncio.run` is already driving. Before the fix,
    evidence_collector only exposed a blocking `collect_evidence` that opened
    its own `asyncio.new_event_loop()` and called `run_until_complete` on it;
    doing that from inside a running loop raises `RuntimeError: Cannot run
    the event loop while another loop is running`. This test fails on that
    exact error if the coroutine form is removed or made to nest a loop again.
    """
    async def _driver():
        with patch("scrapers.website_scraper.scrape_hit_leads", _fake_scrape_hit_leads), \
             patch("enrichers.evidence_collector.config.PERPLEXITY_API_KEY", "real-key"), \
             patch.object(perplexity_enricher, "enrich_leads_perplexity", _fake_enrich_ok):
            return await collect_evidence_async(_leads())

    leads, active = asyncio.run(_driver())

    assert active == frozenset({"website", "perplexity"})
    assert all(l["website_text"] for l in leads)


def test_perplexity_excluded_from_active_providers_when_key_gets_rejected():
    """
    A key that authenticates but gets rejected mid-batch must not stay in the
    active set: fact_extractor would otherwise keep expecting a perplexity
    source that never delivered, capping every lead's evidence_level at "weak"
    for a provider the run never actually got to use.
    """
    with patch("scrapers.website_scraper.scrape_hit_leads", _fake_scrape_hit_leads), \
         patch("enrichers.evidence_collector.config.PERPLEXITY_API_KEY", "real-key"), \
         patch.object(perplexity_enricher, "enrich_leads_perplexity", _fake_enrich_disabled):
        leads, active = collect_evidence(_leads())

    assert active == frozenset({"website"})
    assert "perplexity" not in active


def test_perplexity_skipped_when_key_is_a_placeholder():
    with patch("scrapers.website_scraper.scrape_hit_leads", _fake_scrape_hit_leads), \
         patch("enrichers.evidence_collector.config.PERPLEXITY_API_KEY", ""):
        leads, active = collect_evidence(_leads())

    assert active == frozenset({"website"})
    assert all(l["digital_maturity"] is None for l in leads)
