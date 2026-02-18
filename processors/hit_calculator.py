"""
Step 4 — Hit score calculator.

Scoring:
  email found      → +40 pts
  LinkedIn found   → +30 pts
  phone found      → +20 pts
  website found    → +10 pts
  Total max        → 100 pts

A lead is flagged as 'hit' if score >= HIT_THRESHOLD (default 50).
"""
import logging

import config

logger = logging.getLogger(__name__)


def calculate_hit_score(lead: dict) -> dict:
    """
    Compute hit_score and is_hit for a single lead.
    Modifies lead in place and returns it.
    """
    score = 0

    if lead.get("email"):
        score += config.SCORE_EMAIL
    if lead.get("linkedin_url"):
        score += config.SCORE_LINKEDIN
    if lead.get("phone"):
        score += config.SCORE_PHONE
    if lead.get("website"):
        score += config.SCORE_WEBSITE

    lead["hit_score"] = score
    lead["is_hit"] = score >= config.HIT_THRESHOLD
    return lead


def score_all_leads(leads: list[dict]) -> tuple[list[dict], list[dict]]:
    """
    Score all leads and split into hit / no-hit groups.

    Returns:
        (hit_leads, nohit_leads) — both are subsets of the same dicts (not copies).
    """
    for lead in leads:
        calculate_hit_score(lead)

    hit_leads = [l for l in leads if l["is_hit"]]
    nohit_leads = [l for l in leads if not l["is_hit"]]

    logger.info(
        f"Hit score complete: {len(hit_leads)} hits / {len(nohit_leads)} no-hits "
        f"(threshold: {config.HIT_THRESHOLD})"
    )

    # Score distribution
    if leads:
        avg = sum(l["hit_score"] for l in leads) / len(leads)
        logger.info(f"Average hit score: {avg:.1f}")

    return hit_leads, nohit_leads
