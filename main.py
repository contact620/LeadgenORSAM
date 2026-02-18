"""
ORSAM — B2B Lead Generation Pipeline
======================================
Pipeline en 5 étapes :
  1. Input Apollo URL          (CLI arg)
  2. Scraping Apollo            (Playwright headless)
  3. Enrichissement multi-sources  (Google Search + Dropcontact)
  4. Calcul du taux de hit     (score 0-100, seuil 50)
  5. Enrichissement IA          (LinkedIn/web scraping + GPT-4o-mini)

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
from scrapers.apollo_scraper import scrape_apollo
from enrichers.google_search import enrich_leads_google
from enrichers.dropcontact import enrich_leads_dropcontact
from processors.hit_calculator import score_all_leads
from scrapers.linkedin_scraper import scrape_hit_leads
from enrichers.gpt_enricher import enrich_leads_gpt

# ── CSV column order (matches PRD schema) ─────────────────────────────────────
CSV_COLUMNS = [
    "first_name",
    "last_name",
    "company",
    "job_title",
    "location",
    "email",
    "phone",
    "linkedin_url",
    "website",
    "hit_score",
    "is_hit",
    "activity_summary",
    "conversion_angle",
]


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


def print_summary(all_leads: list[dict], hit_leads: list[dict], nohit_leads: list[dict], path: str):
    total = len(all_leads)
    print("\n" + "=" * 60)
    print("  ORSAM — PIPELINE SUMMARY")
    print("=" * 60)
    print(f"  Total leads scraped    : {total}")
    print(f"  Hit leads (score ≥ {config.HIT_THRESHOLD}) : {len(hit_leads)}")
    print(f"  No-hit leads           : {len(nohit_leads)}")
    if total:
        emails = sum(1 for l in all_leads if l.get("email"))
        linkedins = sum(1 for l in all_leads if l.get("linkedin_url"))
        phones = sum(1 for l in all_leads if l.get("phone"))
        websites = sum(1 for l in all_leads if l.get("website"))
        print(f"  Emails found           : {emails} ({100*emails//total}%)")
        print(f"  LinkedIn URLs found    : {linkedins} ({100*linkedins//total}%)")
        print(f"  Phones found           : {phones} ({100*phones//total}%)")
        print(f"  Websites found         : {websites} ({100*websites//total}%)")
    print(f"\n  Output file: {path}")
    print("=" * 60 + "\n")


async def run_pipeline(args):
    logger = logging.getLogger("main")

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

    # ── Step 3a: Google enrichment ────────────────────────────────────────────
    logger.info("Step 3a — Google enrichment (LinkedIn + website)...")
    leads = enrich_leads_google(leads)

    # ── Step 3b: Dropcontact enrichment ───────────────────────────────────────
    logger.info("Step 3b — Dropcontact enrichment (email + phone)...")
    leads = enrich_leads_dropcontact(leads)

    # ── Step 4: Hit score ─────────────────────────────────────────────────────
    logger.info("Step 4 — Calculating hit scores...")
    hit_leads, nohit_leads = score_all_leads(leads)

    # ── Save intermediate CSV (all leads, before AI enrichment) ───────────────
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    intermediate_filename = f"leads_intermediate_{ts}.csv"
    intermediate_path = export_csv(leads, intermediate_filename)
    logger.info(f"Intermediate CSV saved: {intermediate_path}")

    # ── Step 5: AI enrichment (hit leads only) ────────────────────────────────
    if not args.skip_gpt and hit_leads:
        logger.info(f"Step 5 — AI enrichment on {len(hit_leads)} hit leads...")

        # 5a: Scrape LinkedIn + website
        logger.info("Step 5a — Scraping LinkedIn profiles + websites...")
        hit_leads = await scrape_hit_leads(hit_leads)

        # 5b: GPT-4o-mini
        logger.info("Step 5b — GPT-4o-mini enrichment...")
        hit_leads = enrich_leads_gpt(hit_leads)
    else:
        if args.skip_gpt:
            logger.info("Step 5 — Skipped (--skip-gpt flag set)")
        else:
            logger.info("Step 5 — Skipped (no hit leads)")

        for lead in hit_leads:
            lead.setdefault("linkedin_text", "")
            lead.setdefault("website_text", "")
            lead.setdefault("activity_summary", None)
            lead.setdefault("conversion_angle", None)

    # ── Final CSV export ──────────────────────────────────────────────────────
    output_filename = args.output or f"leads_final_{ts}.csv"
    final_path = export_csv(leads, output_filename)

    # Also save no-hit leads separately
    if nohit_leads:
        nohit_filename = f"leads_nohit_{ts}.csv"
        nohit_path = export_csv(nohit_leads, nohit_filename)
        logger.info(f"No-hit CSV saved: {nohit_path}")

    print_summary(leads, hit_leads, nohit_leads, final_path)


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
        help="Skip GPT-4o-mini enrichment (Step 5)",
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
    asyncio.run(run_pipeline(args))
