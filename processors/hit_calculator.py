"""
Step 4 — Hit score calculator.

Scoring:
  email (verified valid)         → +40 pts (full)
  email (accept_all/webmail/unknown) → +20 pts (half — could be valid)
  email (invalid/disposable)     → 0 pts   (drop)
  email (no verification done)   → +40 pts (legacy fallback)
  LinkedIn found                 → +30 pts
  phone found                    → +20 pts
  website found                  → +10 pts
  Total max                      → 100 pts

A lead is flagged as 'hit' if score >= HIT_THRESHOLD (default 50).
"""
import logging

import config

logger = logging.getLogger(__name__)

# Hunter.io status → email score multiplier (applied to SCORE_EMAIL)
_EMAIL_STATUS_WEIGHTS = {
    "valid": 1.0,
    "accept_all": 0.5,
    "webmail": 0.5,
    "unknown": 0.5,
    "invalid": 0.0,
    "disposable": 0.0,
}


def _email_points(lead: dict) -> int:
    """Compute email contribution to hit_score, weighted by verification status."""
    if not lead.get("email"):
        return 0
    status = lead.get("email_status")
    if status is None:
        # No verification was run (Hunter disabled or no API key) — fall back to legacy full weight.
        return config.SCORE_EMAIL
    weight = _EMAIL_STATUS_WEIGHTS.get(status, 0.5)
    return int(round(config.SCORE_EMAIL * weight))


def calculate_hit_score(lead: dict) -> dict:
    """
    Compute hit_score and is_hit for a single lead.
    Modifies lead in place and returns it.
    """
    score = _email_points(lead)

    if lead.get("linkedin_url"):
        score += config.SCORE_LINKEDIN
    if lead.get("phone"):
        score += config.SCORE_PHONE
    # A website rejected by the coherence check must not earn points.
    # Absent flag = pool scraped before the check existed -> keep legacy behaviour.
    if lead.get("website") and lead.get("website_coherent") is not False:
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


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    test_leads = [
        {"first_name": "Jean",  "email": "jean@acme.com", "linkedin_url": "https://linkedin.com/in/jean", "phone": "+33600000000", "website": "https://acme.com"},
        {"first_name": "Marie", "email": None,            "linkedin_url": "https://linkedin.com/in/marie", "phone": None, "website": None},
        {"first_name": "Paul",  "email": None,            "linkedin_url": None, "phone": None, "website": None},
    ]

    hits, nohits = score_all_leads(test_leads)
    print(f"\nHits ({len(hits)}):")
    for l in hits:
        print(f"  {l['first_name']} — score: {l['hit_score']}")
    print(f"\nNo-hits ({len(nohits)}):")
    for l in nohits:
        print(f"  {l['first_name']} — score: {l['hit_score']}")
