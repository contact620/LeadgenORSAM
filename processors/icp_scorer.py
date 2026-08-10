"""
Step 7 — Deterministic ICP scoring.

The previous version asked an LLM to grade four axes before any evidence had
been collected, which made the score inversely correlated with knowledge: an
unknown company got generous defaults, a known one got real criteria applied.

Here the LLM only extracts sourced facts (see enrichers/fact_extractor.py).
This module turns facts into a score using versioned tables, so the result is
reproducible, explainable and testable without an API call.
"""
import json
import logging
from dataclasses import dataclass
from datetime import date
from typing import Optional

from processors.icp_rules import IcpRules, load_rules

logger = logging.getLogger(__name__)


@dataclass
class IcpResult:
    icp_score: int
    icp_tier: str                       # "hot" | "warm" | "cold" | "disqualified"
    icp_rationale: str
    icp_scores_detail: str              # JSON string
    disqualification_reason: Optional[str]
    evidence_verified: bool


def _reset_state():
    """Kept for import compatibility with api/pipeline_runner.py. No-op."""
    return None


# ── Fact readers ─────────────────────────────────────────────────────────────

def _value(fact) -> object:
    """Read the value of a sourced fact, or None when the fact is absent."""
    if isinstance(fact, dict):
        return fact.get("value")
    return None


def _months_between(older: str, reference: date) -> Optional[int]:
    """Months from a 'YYYY-MM' (or 'YYYY-MM-DD') string to the reference date."""
    if not older:
        return None
    try:
        parts = str(older).split("-")
        year, month = int(parts[0]), int(parts[1])
    except (ValueError, IndexError):
        return None
    return (reference.year - year) * 12 + (reference.month - month)


# ── Axis scoring ─────────────────────────────────────────────────────────────

def _score_sector(facts: dict, rules: IcpRules) -> int:
    sector = _value(facts.get("secteur"))
    if not sector:
        return rules.sector_points.get("unknown", 0)
    normalized = str(sector).strip().lower()
    if any(h in normalized for h in rules.high_value_sectors):
        return rules.sector_points.get("high_value", 100)
    return rules.sector_points.get("other", 50)


def _score_size(facts: dict, rules: IcpRules) -> int:
    headcount = _value(facts.get("effectif"))
    if not isinstance(headcount, (int, float)):
        return 0
    for band in rules.size_bands:
        if band["min"] <= headcount <= band["max"]:
            return band["points"]
    return 0


def _score_location(facts: dict, rules: IcpRules) -> int:
    country = _value(facts.get("pays"))
    if not country:
        return 0
    zone = rules.country_zone(str(country))
    if zone is None:
        return 0
    return rules.zone_points.get(zone, 0)


def _score_signals(facts: dict, rules: IcpRules, run_date: date) -> int:
    signals = [s for s in (facts.get("signaux") or []) if isinstance(s, dict)]
    count = len(signals)

    recent = any(
        (age := _months_between(s.get("date"), run_date)) is not None
        and 0 <= age <= rules.signal_recency_months
        for s in signals
    )

    if count >= 3:
        key = "three_or_more_recent" if recent else "three_or_more"
    elif count == 2:
        key = "two"
    elif count == 1:
        key = "one"
    else:
        key = "none"
    points = rules.signal_points.get(key, 0)

    # Digital maturity encodes BoxCom's ideal profile: a weak or ageing
    # digital presence is the buying signal, a mature one is not.
    maturity = _value(facts.get("maturite_digitale"))
    if isinstance(maturity, (int, float)):
        if maturity <= rules.maturity_low_max:
            points += rules.maturity_bonus
        elif maturity >= rules.maturity_high_min:
            points -= rules.maturity_penalty

    return max(0, min(100, points))


# ── Disqualification ─────────────────────────────────────────────────────────

def _disqualification_reason(facts: dict, rules: IcpRules) -> Optional[str]:
    headcount = _value(facts.get("effectif"))
    if isinstance(headcount, (int, float)):
        if headcount > rules.size_disqualify_above:
            return (f"grand groupe — {int(headcount)} employés, "
                    f"au-delà du seuil de {rules.size_disqualify_above}")
        if headcount < rules.size_disqualify_below:
            return (f"micro-entreprise — {int(headcount)} employés, "
                    f"sous le seuil de {rules.size_disqualify_below}")

    sector = _value(facts.get("secteur"))
    if sector:
        normalized = str(sector).strip().lower()
        for excluded in rules.excluded_sectors:
            if excluded in normalized:
                return f"secteur exclu — {sector}"

    country = _value(facts.get("pays"))
    if country and rules.country_zone(str(country)) is None:
        return f"hors zone géographique — {country}"

    return None


# ── Public API ───────────────────────────────────────────────────────────────

def score_lead(
    facts: dict,
    evidence_level: str,
    rules: IcpRules,
    run_date: date,
) -> IcpResult:
    """Turn validated facts into a score, a tier and, where warranted, a refusal."""
    detail = {
        "secteur": _score_sector(facts, rules),
        "taille": _score_size(facts, rules),
        "localisation": _score_location(facts, rules),
        "signaux": _score_signals(facts, rules, run_date),
    }
    raw_score = round(sum(detail[axis] * rules.weights[axis] for axis in detail))
    detail_json = json.dumps(detail)
    verified = evidence_level == "sufficient"

    # 1. A sourced competitor is disqualified whatever the evidence level:
    #    the fact alone settles it.
    if facts.get("est_concurrent") is True:
        return IcpResult(
            icp_score=raw_score, icp_tier="disqualified",
            icp_rationale="Concurrent direct de BoxCom — ne peut pas être client.",
            icp_scores_detail=detail_json,
            disqualification_reason="concurrent direct",
            evidence_verified=verified,
        )

    # 2. Insufficient evidence: cap and fall into cold. No disqualification
    #    claim is made — we lack the facts to assert one.
    if not verified:
        return IcpResult(
            icp_score=min(raw_score, rules.unverified_score_cap),
            icp_tier="cold",
            icp_rationale=(
                "Preuves insuffisantes pour évaluer ce prospect "
                f"(niveau de preuve : {evidence_level}). Score plafonné, "
                "qualification manuelle nécessaire."
            ),
            icp_scores_detail=detail_json,
            disqualification_reason=None,
            evidence_verified=False,
        )

    # 3. Hard rules, only on properly evidenced leads
    reason = _disqualification_reason(facts, rules)
    if reason:
        return IcpResult(
            icp_score=raw_score, icp_tier="disqualified",
            icp_rationale=f"Prospect disqualifié : {reason}.",
            icp_scores_detail=detail_json,
            disqualification_reason=reason,
            evidence_verified=True,
        )

    # 4. Normal tiers
    if raw_score >= rules.tier_hot_min:
        tier = "hot"
    elif raw_score >= rules.tier_warm_min:
        tier = "warm"
    else:
        tier = "cold"

    signal_count = len([s for s in (facts.get("signaux") or []) if isinstance(s, dict)])
    rationale = (
        f"Secteur {detail['secteur']}/100, taille {detail['taille']}/100, "
        f"localisation {detail['localisation']}/100, "
        f"signaux {detail['signaux']}/100 ({signal_count} signal(aux) sourcé(s))."
    )

    return IcpResult(
        icp_score=raw_score, icp_tier=tier,
        icp_rationale=rationale,
        icp_scores_detail=detail_json,
        disqualification_reason=None,
        evidence_verified=True,
    )


def apply_scores(
    leads: list[dict],
    rules: Optional[IcpRules] = None,
    run_date: Optional[date] = None,
) -> list[dict]:
    """
    Score every lead in place from lead['facts'] and lead['evidence_level'].

    Both keys are produced by enrichers/fact_extractor.py earlier in the run.
    """
    active_rules = rules or load_rules()
    today = run_date or date.today()

    counts = {"hot": 0, "warm": 0, "cold": 0, "disqualified": 0}
    for lead in leads:
        result = score_lead(
            lead.get("facts") or {},
            lead.get("evidence_level") or "none",
            active_rules,
            today,
        )
        lead["icp_score"] = result.icp_score
        lead["icp_tier"] = result.icp_tier
        lead["icp_rationale"] = result.icp_rationale
        lead["icp_scores_detail"] = result.icp_scores_detail
        lead["disqualification_reason"] = result.disqualification_reason
        lead["evidence_verified"] = result.evidence_verified
        counts[result.icp_tier] = counts.get(result.icp_tier, 0) + 1

    logger.info(
        f"ICP scoring complete: {counts['hot']} hot, {counts['warm']} warm, "
        f"{counts['cold']} cold, {counts['disqualified']} disqualified."
    )
    return leads
