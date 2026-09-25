"""
ORSAM — B2B Lead Generation Pipeline
======================================
Nine-step pipeline. The free/paid boundary mirrors the one between
/api/scrape and /api/enrich (see api/pipeline_runner.py):
  1. Input Apollo URL              (CLI arg)
  2. Scraping Apollo                (Playwright headless)
  3. LinkedIn and website + coherence (Google Search)
  4. Site contact extraction        (free — published emails/phones)
  5. Pre-score and prioritization   (free — decides where credits go)
  6. Email cascade                  (paid — finders, priority leads only)
  7. Evidence collection            (site + Perplexity, reachable leads only)
  8. Fact extraction and ICP scoring (Claude, versioned rules)
  9. Sales angle writing            (Claude, retained leads only)

Usage:
  python main.py --url "https://app.apollo.io/#/people?..." [options]

Options:
  --url           Apollo search results URL (required)
  --output        Output CSV filename (default: leads_YYYYMMDD_HHMMSS.csv)
  --max-leads     Maximum number of leads to scrape (default: from .env / 500)
  --skip-gpt      Skip GPT enrichment (faster, cheaper)
  --no-headless   Show browser window (useful for debugging)
  --log-level     Logging level: DEBUG, INFO, WARNING (default: INFO)
"""
import argparse
import asyncio
import logging
import os
import sys
from datetime import datetime

import pandas as pd

import config
from api import quota_db
from api.pipeline_runner import _apply_suppression_filter, _dedupe_leads, _harvest_lead_contacts
from api.provider_status import ProviderFailure, ProviderRegistry
from scrapers.apollo_scraper import scrape_apollo
from enrichers.google_search import enrich_leads_google
from processors.hit_calculator import score_all_leads
from processors.prescore import apply_prescores, rank_for_spending
from lead_schema import CSV_COLUMNS

# How each provider is named to the operator in the CLI summary.
PROVIDER_LABELS = {
    "hunter": "Hunter.io (recherche et vérification d'emails)",
    "prospeo": "Prospeo (recherche d'emails)",
    "getprospect": "GetProspect (recherche d'emails)",
    "getprospect_verify": "GetProspect (vérification d'emails)",
    "serper": "Serper (recherche LinkedIn)",
    "website": "Scraping des sites web",
    "perplexity": "Perplexity (signaux business)",
    "anthropic_facts": "Extraction de faits",
    "anthropic_angles": "Rédaction des angles",
}


def setup_logging(level: str):
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
        handlers=[
            logging.StreamHandler(sys.stdout),
        ],
    )


def export_csv(leads: list[dict], output_path: str):
    """Export the full lead list to CSV with the schema from the PRD."""
    os.makedirs(config.OUTPUT_DIR, exist_ok=True)
    full_path = os.path.join(config.OUTPUT_DIR, output_path)

    df = pd.DataFrame(leads)

    # Ensure all columns exist (fill missing with None)
    for col in CSV_COLUMNS:
        if col not in df.columns:
            df[col] = None

    df = df[CSV_COLUMNS]
    df.to_csv(full_path, index=False, encoding="utf-8-sig")
    return full_path


def print_provider_health(registry: ProviderRegistry):
    """Print one line per provider that did not deliver.

    Without this, a run where Serper's key expired mid-way ends on an
    impeccable-looking summary: the missing 30 points per lead show up only as
    a low LinkedIn rate, indistinguishable from a hard search batch.
    """
    outcomes = registry.to_dict()
    impaired = {
        name: entry for name, entry in outcomes.items()
        if entry["status"] in ("failed", "degraded")
    }
    skipped = {
        name: entry for name, entry in outcomes.items()
        if entry["status"] == "skipped"
    }
    if not impaired and not skipped:
        return

    print("  " + "-" * 56)
    print("  Santé des fournisseurs :")
    for name, entry in impaired.items():
        label = PROVIDER_LABELS.get(name, name)
        state = "EN ÉCHEC" if entry["status"] == "failed" else "DÉGRADÉ"
        detail = f" — {entry['reason']}" if entry["reason"] else ""
        affected = f" ({entry['leads_affected']} lead(s) concerné(s))" if entry["leads_affected"] else ""
        print(f"    [{state}] {label}{detail}{affected}")
    for name, entry in skipped.items():
        label = PROVIDER_LABELS.get(name, name)
        detail = f" — {entry['reason']}" if entry["reason"] else ""
        print(f"    [IGNORÉ] {label}{detail}")


def print_summary(all_leads: list[dict], hit_leads: list[dict], nohit_leads: list[dict],
                  path: str, registry: ProviderRegistry | None = None,
                  pending_leads: list[dict] | None = None):
    pending_leads = pending_leads or []
    total = len(all_leads)
    print("\n" + "=" * 60)
    print("  ORSAM — PIPELINE SUMMARY")
    print("=" * 60)
    print(f"  Total leads scraped    : {total}")
    print(f"  Reachable leads        : {len(hit_leads)}")
    print(f"  Unreachable leads      : {len(nohit_leads)}")
    if pending_leads:
        print(f"  Pending quota          : {len(pending_leads)} (no provider credit left — not discarded)")
    if total:
        emails = sum(1 for l in all_leads if l.get("email"))
        linkedins = sum(1 for l in all_leads if l.get("linkedin_url"))
        phones = sum(1 for l in all_leads if l.get("phone"))
        websites = sum(1 for l in all_leads if l.get("website"))
        print(f"  Emails found           : {emails} ({100*emails//total}%)")
        print(f"  LinkedIn URLs found    : {linkedins} ({100*linkedins//total}%)")
        print(f"  Phones found           : {phones} ({100*phones//total}%)")
        print(f"  Websites found         : {websites} ({100*websites//total}%)")
        icp_hot = sum(1 for l in all_leads if l.get("icp_tier") == "hot")
        icp_warm = sum(1 for l in all_leads if l.get("icp_tier") == "warm")
        icp_cold = sum(1 for l in all_leads if l.get("icp_tier") == "cold")
        if icp_hot or icp_warm or icp_cold:
            print(f"  ICP Hot / Warm / Cold   : {icp_hot} / {icp_warm} / {icp_cold}")
        icp_disq = sum(1 for l in all_leads if l.get("icp_tier") == "disqualified")
        if icp_disq:
            print(f"  ICP disqualifiés        : {icp_disq}")
    if registry is not None:
        print_provider_health(registry)
    print(f"\n  Output file: {path}")
    print("=" * 60 + "\n")


async def run_pipeline(args):
    logger = logging.getLogger("main")
    registry = ProviderRegistry()

    # ── Validate config ───────────────────────────────────────────────────────
    missing = config.validate_config()
    if missing:
        print(f"\n[WARNING] Missing API keys: {', '.join(missing)}")
        print("Some enrichment steps will be skipped. Check your .env file.\n")

    # ── Step 1: Apollo URL ────────────────────────────────────────────────────
    apollo_url = args.url
    logger.info(f"Step 1 — Apollo URL: {apollo_url}")

    # ── Step 2: Scraping Apollo ───────────────────────────────────────────────
    logger.info("Step 2 — Scraping Apollo...")
    leads = await scrape_apollo(apollo_url, max_leads=args.max_leads)

    if not leads:
        logger.error("No leads scraped from Apollo. Check your cookies and URL. Exiting.")
        sys.exit(1)

    logger.info(f"Step 2 complete: {len(leads)} raw leads")

    # ── Step 3: LinkedIn and website + coherence ───────────────────────────────
    logger.info("Step 3 — LinkedIn et site web (Google Search)...")
    leads = enrich_leads_google(leads, registry=registry)

    # ── Step 4: site contact extraction (free) ─────────────────────
    logger.info("Step 4 — Extraction des contacts du site...")
    for lead in leads:
        _harvest_lead_contacts(lead)

    # ── Step 5: pre-score and prioritization ──────────────────────────────────────
    logger.info("Step 5 — Calcul du pre-score...")
    apply_prescores(leads)

    # ── Suppression and dedup, before any enrichment ─────────────
    leads, suppressed = _apply_suppression_filter(leads)
    if suppressed:
        logger.info(f"{len(suppressed)} lead(s) écarté(s) — liste de suppression")
    _dedupe_leads(leads, job_id=f"cli-{datetime.now().strftime('%Y%m%d%H%M%S')}")

    # ── Save intermediate CSV (all leads, before the cascade) ─────────────────
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    intermediate_filename = f"leads_intermediate_{ts}.csv"
    intermediate_path = export_csv(leads, intermediate_filename)
    logger.info(f"Intermediate CSV saved: {intermediate_path}")

    # ── Step 6: email cascade (paid) ─────────────────────────────────────────
    logger.info("Step 6 — Synchronisation des quotas fournisseurs...")
    from enrichers.providers.quota_sync import sync_all
    sync_all(registry)

    # Finder credits go to the head of the queue, not to whoever happens to be
    # scraped first (§7).
    ranked = rank_for_spending(leads)
    budget = sum(quota_db.get_quota(p)["remaining"] for p in ("prospeo", "getprospect", "hunter"))
    logger.info(f"Step 6 — Cascade email sur {len(ranked)} lead(s) (budget finders : {budget})...")
    from enrichers.email_cascade import resolve_email
    for position, lead in enumerate(ranked):
        resolve_email(lead, is_priority=position < budget, registry=registry)
    leads = ranked

    # ── Reachability: reachable / unreachable / pending_quota ─────────────────
    hit_leads, nohit_leads, pending_leads = score_all_leads(leads)
    nohit_leads = nohit_leads + suppressed

    # ── Steps 7-9: evidence, facts, ICP scoring, angles (reachable only) ────────────
    if not args.skip_gpt and hit_leads:
        logger.info(f"Step 7 — Evidence collection on {len(hit_leads)} reachable leads...")
        from enrichers.evidence_collector import collect_evidence_async
        hit_leads, active_providers = await collect_evidence_async(
            hit_leads, registry=registry
        )

        logger.info("Step 8 — Fact extraction and ICP scoring...")
        from enrichers.fact_extractor import extract_leads_facts
        hit_leads = extract_leads_facts(hit_leads, active_providers, registry=registry)

        from processors.icp_scorer import apply_scores
        hit_leads = apply_scores(hit_leads)

        logger.info("Step 9 — Angle writing...")
        from enrichers.angle_writer import write_leads_angles
        hit_leads = write_leads_angles(hit_leads, registry=registry)
    else:
        reason = "--skip-gpt flag set" if args.skip_gpt else "no reachable leads"
        logger.info(f"Steps 7-9 — Skipped ({reason})")
        for lead in hit_leads:
            for field in ("icp_score", "icp_tier", "icp_rationale", "icp_scores_detail",
                          "disqualification_reason", "evidence_level", "evidence_verified",
                          "facts_json", "activity_summary", "conversion_angle",
                          "digital_maturity", "estimated_budget", "business_signals"):
                lead.setdefault(field, None)

    leads = hit_leads + nohit_leads + pending_leads

    # ── Final CSV export ──────────────────────────────────────────────────────
    output_filename = args.output or f"leads_final_{ts}.csv"
    final_path = export_csv(leads, output_filename)

    # Also save no-hit leads separately
    if nohit_leads:
        nohit_filename = f"leads_nohit_{ts}.csv"
        nohit_path = export_csv(nohit_leads, nohit_filename)
        logger.info(f"No-hit CSV saved: {nohit_path}")

    # pending_quota leads were never asked the question — a separate CSV keeps
    # them from padding either the hit or the no-hit numbers (§11).
    if pending_leads:
        pending_filename = f"leads_pending_quota_{ts}.csv"
        pending_path = export_csv(pending_leads, pending_filename)
        logger.info(f"Pending-quota CSV saved: {pending_path}")

    print_summary(leads, hit_leads, nohit_leads, final_path, registry, pending_leads)


def parse_args():
    parser = argparse.ArgumentParser(
        description="ORSAM — B2B Lead Generation Pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--url",
        required=True,
        help="Apollo.io search results URL",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Output CSV filename (saved in ./output/)",
    )
    parser.add_argument(
        "--max-leads",
        type=int,
        default=config.MAX_LEADS,
        help=f"Max leads to scrape (default: {config.MAX_LEADS})",
    )
    parser.add_argument(
        "--skip-gpt",
        action="store_true",
        help="Skip evidence collection and AI enrichment (Steps 5-8)",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging verbosity (default: INFO)",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    setup_logging(args.log_level)
    try:
        asyncio.run(run_pipeline(args))
    except ProviderFailure as exc:
        # A critical provider gave up. Say so plainly and exit non-zero rather
        # than dumping a traceback the operator has to decode.
        print("\n" + "=" * 60)
        print("  RUN INTERROMPU — fournisseur critique indisponible")
        print("=" * 60)
        print(f"  Fournisseur : {PROVIDER_LABELS.get(exc.provider, exc.provider)}")
        print(f"  Motif       : {exc.reason}")
        print("\n  Aucun fichier final n'a été produit : le run s'arrête plutôt")
        print("  que de livrer un CSV sans données de contact.")
        print("  Vérifiez la clé API et les crédits du fournisseur, puis relancez.")
        print("=" * 60 + "\n")
        sys.exit(1)
