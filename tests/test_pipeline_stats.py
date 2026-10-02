import pytest

from api.pipeline_runner import STEP_NAMES, STEP_PATTERNS, STEP_WEIGHTS, compute_stats


def _lead(**over):
    base = {"email": None, "email_status": "not_found", "email_source": None,
            "phone": None, "phone_type": None, "whatsapp": False,
            "reachable": False, "prescore": 0}
    base.update(over)
    return base


def test_step_weights_sum_to_one():
    assert round(sum(STEP_WEIGHTS.values()), 6) == 1.0


def test_every_weighted_step_has_a_name_and_a_pattern():
    assert set(STEP_WEIGHTS) == set(STEP_NAMES)
    covered = {step for step, _ in STEP_PATTERNS}
    assert covered.issubset(set(STEP_WEIGHTS))


def test_find_rate_is_broken_down_by_source():
    leads = [
        _lead(email="a@x.ma", email_status="valid_nominatif", email_source="website"),
        _lead(email="b@x.ma", email_status="valid_nominatif", email_source="website"),
        _lead(email="c@x.ma", email_status="valid_nominatif", email_source="pattern_verified"),
        _lead(email="d@x.ma", email_status="valid_nominatif", email_source="prospeo"),
        _lead(),
    ]
    stats = compute_stats(leads)
    assert stats.email_by_source["website"] == 2
    assert stats.email_by_source["pattern_verified"] == 1
    assert stats.email_by_source["prospeo"] == 1


def test_mobile_and_whatsapp_rates_are_reported():
    leads = [_lead(phone="+212661234567", phone_type="mobile"),
             _lead(phone="+212522123456", phone_type="fixe"),
             _lead(whatsapp=True), _lead()]
    stats = compute_stats(leads)
    assert stats.mobile_count == 1
    assert stats.whatsapp_count == 1


def test_pending_quota_leads_are_counted_separately():
    stats = compute_stats([_lead(email_status="pending_quota"), _lead()])
    assert stats.pending_quota_count == 1


def test_stats_on_an_empty_run_do_not_divide_by_zero():
    stats = compute_stats([])
    assert stats.email_pct == 0.0


def test_a_lead_with_a_factual_refusal_is_not_counted_as_low_relevance():
    """score_lead keeps a weak-evidence lead in tier "cold" even when a
    single-fact rule refused it, but the modal says "Disqualifié" from the
    reason. The run summary must say the same, not "faible pertinence"."""
    refused_but_weak = _lead(icp_tier="cold", disqualification_reason="grand groupe",
                             evidence_verified=False)
    plain_cold = _lead(icp_tier="cold", disqualification_reason=None)
    stats = compute_stats([refused_but_weak, plain_cold])
    assert stats.icp_disqualified_count == 1
    assert stats.icp_cold_count == 1


def test_the_scorer_output_for_a_weak_refused_lead_is_counted_as_disqualified():
    """Through the real scorer rather than a hand-built dict: an unverified
    5000-employee group keeps tier "cold" and carries a reason."""
    from datetime import date

    from processors.icp_rules import load_rules
    from processors.icp_scorer import apply_scores

    lead = {"evidence_level": "weak", "facts": {
        "identite_confirmee": True,
        "pays": {"value": "Maroc", "source": "website"},
        "secteur": {"value": "e-commerce", "source": "website"},
        "effectif": {"value": 5000, "source": "perplexity"},
        "est_concurrent": None, "maturite_digitale": None, "signaux": [],
    }}
    apply_scores([lead], load_rules(), date(2026, 10, 2))
    assert lead["icp_tier"] == "cold" and lead["disqualification_reason"]
    stats = compute_stats([dict(_lead(), **lead)])
    assert stats.icp_disqualified_count == 1
    assert stats.icp_cold_count == 0
