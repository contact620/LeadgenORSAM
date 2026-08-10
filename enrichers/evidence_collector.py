"""
Step 5 — Evidence collection.

Gathers every source the scoring engine will rely on, before any judgement is
made. Returns which providers were actually active so evidence_level can adapt:
a lead must not be penalised for a provider the operator turned off.
"""
import asyncio
import logging

import config
from api.provider_status import StepOutcome

logger = logging.getLogger(__name__)


def collect_evidence(leads: list[dict], enrich_instructions: str = "", registry=None):
    """Scrape websites and query Perplexity. Returns (leads, active_providers)."""
    from scrapers.website_scraper import scrape_hit_leads
    from enrichers.perplexity_enricher import enrich_leads_perplexity

    active = {"website"}  # website scraping needs no API key

    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        leads = loop.run_until_complete(scrape_hit_leads(leads))
    finally:
        loop.close()

    scraped = sum(1 for l in leads if (l.get("website_text") or "").strip())
    logger.info(f"Evidence: {scraped}/{len(leads)} websites yielded text")
    if registry:
        registry.record(StepOutcome("website", "ok", None, scraped))

    if config._is_placeholder(config.PERPLEXITY_API_KEY):
        logger.info("PERPLEXITY_API_KEY not set — Perplexity excluded from evidence expectations.")
        for lead in leads:
            lead.setdefault("digital_maturity", None)
            lead.setdefault("estimated_budget", None)
            lead.setdefault("business_signals", None)
        if registry:
            registry.record(StepOutcome("perplexity", "skipped", "clé API absente", 0))
    else:
        leads = enrich_leads_perplexity(leads, enrich_instructions, registry=registry)
        active.add("perplexity")

    return leads, frozenset(active)
