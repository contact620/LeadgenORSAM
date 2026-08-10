"""
Step 5 — Evidence collection.

Gathers every source the scoring engine will rely on, before any judgement is
made. Returns which providers were actually active so evidence_level can adapt:
a lead must not be penalised for a provider the operator turned off.

Exposes two entry points on purpose:
  - `collect_evidence_async` — a coroutine, for callers already running inside
    an event loop (e.g. the CLI's `run_pipeline`, itself driven by `asyncio.run`).
  - `collect_evidence` — a blocking wrapper that owns its own event loop, for
    synchronous callers (e.g. the threaded web pipeline runner).
Calling `loop.run_until_complete(...)` on a brand new loop from a coroutine
already running on another loop raises `RuntimeError: Cannot run the event
loop while another loop is running` — asyncio's reentrancy guard is thread-
global (`events._get_running_loop()`), not scoped to the loop instance being
started. The blocking form must therefore never be awaited from within a
running loop; the coroutine form exists precisely so callers in that
situation can `await` instead of nesting loops.
"""
import asyncio
import logging

import config
from api.provider_status import StepOutcome

logger = logging.getLogger(__name__)


async def collect_evidence_async(leads: list[dict], enrich_instructions: str = "", registry=None):
    """Coroutine form — scrape websites and query Perplexity. Returns (leads, active_providers)."""
    from scrapers.website_scraper import scrape_hit_leads
    from enrichers import perplexity_enricher

    active = {"website"}  # website scraping needs no API key

    leads = await scrape_hit_leads(leads)

    scraped = sum(1 for l in leads if (l.get("website_text") or "").strip())
    logger.info(f"Evidence: {scraped}/{len(leads)} websites yielded text")
    if registry:
        # A run with hit leads but zero usable website text is a signal worth
        # surfacing (scraper broken, sites all down/blocking) — not the same
        # as a healthy run where every site simply refused to load its text.
        website_status = "degraded" if leads and scraped == 0 else "ok"
        registry.record(StepOutcome("website", website_status, None, scraped))

    if config._is_placeholder(config.PERPLEXITY_API_KEY):
        logger.info("PERPLEXITY_API_KEY not set — Perplexity excluded from evidence expectations.")
        for lead in leads:
            lead.setdefault("digital_maturity", None)
            lead.setdefault("estimated_budget", None)
            lead.setdefault("business_signals", None)
        if registry:
            registry.record(StepOutcome("perplexity", "skipped", "clé API absente", 0))
    else:
        leads = perplexity_enricher.enrich_leads_perplexity(leads, enrich_instructions, registry=registry)
        # A key that got rejected mid-run disables Perplexity for the rest of
        # the batch (see _perplexity_disabled). Leaving "perplexity" in the
        # active set here would keep expecting a source that never delivered,
        # capping every lead's evidence_level at "weak" for a provider the
        # operator did not actually get to use.
        if not perplexity_enricher._perplexity_disabled:
            active.add("perplexity")

    return leads, frozenset(active)


def collect_evidence(leads: list[dict], enrich_instructions: str = "", registry=None):
    """Blocking form — owns an event loop, for synchronous callers."""
    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        return loop.run_until_complete(collect_evidence_async(leads, enrich_instructions, registry))
    finally:
        loop.close()
        asyncio.set_event_loop(None)
