"""
Pass 1 — free, unsourced ICP prescore.

This exists to answer one question: of the leads we have, which ones deserve
the month's 50 to 100 paid lookups and the Perplexity/Claude enrichment. It
answers it from what Apollo displayed and nothing else.

Two rules make it safe to build a score on unsourced data:

  1. It never disqualifies (décision 3). A missing or wrong Apollo cell costs
     a lead its place in the queue, never its existence — the sourced pass
     can still rehabilitate it.
  2. It never touches icp_score, icp_tier or disqualification_reason. Those
     belong to processors/icp_scorer.py, which reads validated facts. Letting
     an unsourced number reach them would restore exactly the inversion the
     2026-08 rework removed: an unknown company scoring well on generous
     defaults, a known one scoring badly on real criteria.
"""
import logging
from typing import Optional

from processors.icp_rules import IcpRules, load_rules

logger = logging.getLogger(__name__)

# Only the three axes we can populate without spending anything. "signaux"
# (40% of the real score) needs Perplexity, so it is absent here — which is
# why a prescore is never comparable to an icp_score and never exported as one.
PRESCORE_AXES = ("secteur", "taille", "localisation")


def _sector_points(lead: dict, rules: IcpRules) -> int:
    label = lead.get("apollo_industry")
    if not label:
        return 0
    canonical = rules.canonical_sector(str(label))
    if canonical is not None and canonical in rules.high_value_sectors:
        return rules.sector_points.get("high_value", 100)
    if canonical is not None and canonical in rules.excluded_sectors:
        # Scored low rather than disqualified: Apollo's label is not evidence.
        return 0
    return rules.sector_points.get("other", 50)


def _size_points(lead: dict, rules: IcpRules) -> int:
    headcount = lead.get("employee_count")
    if not isinstance(headcount, (int, float)) or headcount <= 0:
        return 0
    for band in rules.size_bands:
        if band["min"] <= headcount <= band["max"]:
            return band["points"]
    return 0


def _location_points(lead: dict, rules: IcpRules) -> int:
    zone = rules.country_zone(str(lead.get("location") or ""))
    if zone is None:
        return 0
    return rules.zone_points.get(zone, 0)


def compute_prescore(lead: dict, rules: Optional[IcpRules] = None) -> int:
    """Weighted 0-100 score on the three free axes. Never raises."""
    active = rules or load_rules()
    points = {
        "secteur": _sector_points(lead, active),
        "taille": _size_points(lead, active),
        "localisation": _location_points(lead, active),
    }
    return round(sum(points[axis] * active.weights[axis] for axis in PRESCORE_AXES))


def apply_prescores(leads: list[dict], rules: Optional[IcpRules] = None) -> list[dict]:
    """Write lead["prescore"] in place. Writes nothing else."""
    active = rules or load_rules()
    for lead in leads:
        lead["prescore"] = compute_prescore(lead, active)
    return leads


def rank_for_spending(leads: list[dict], rules: Optional[IcpRules] = None) -> list[dict]:
    """Return a new list ordered by prescore descending, input order preserved.

    Python's sort is stable, so leads tied on prescore keep their scrape order
    rather than being reshuffled between runs.
    """
    active = rules or load_rules()
    scored = apply_prescores(list(leads), active)
    return sorted(scored, key=lambda l: l.get("prescore", 0), reverse=True)
