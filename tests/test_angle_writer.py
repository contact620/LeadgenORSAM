from unittest.mock import patch

import enrichers.angle_writer as aw
from api.provider_status import ProviderRegistry
from enrichers.angle_writer import should_write, write_leads_angles
from enrichers.retry import CREDIT_EXHAUSTED_MESSAGE, CreditExhausted


def test_disqualified_lead_gets_no_angle():
    assert should_write({"disqualification_reason": "concurrent direct",
                         "evidence_level": "sufficient"}) is False


def test_a_lead_without_any_usable_source_gets_no_angle():
    """The floor that keeps an Anthropic outage visible.

    A failed extraction gives every lead _EMPTY_FACTS, hence
    identite_confirmee=False, hence evidence_level="none". Writing anyway
    would turn twenty empty cells into twenty invented angles.
    """
    assert should_write({"evidence_level": "none"}) is False
    assert should_write({"evidence_level": None}) is False
    assert should_write({}) is False


def test_a_weakly_evidenced_lead_now_gets_an_angle():
    """Thin sourced facts make a thin angle, which is a correct outcome. The
    score used to gate this through evidence_verified; the score is gone."""
    assert should_write({"evidence_level": "weak"}) is True


def test_a_well_evidenced_lead_gets_an_angle():
    assert should_write({"evidence_level": "sufficient"}) is True


def test_the_icp_tier_no_longer_decides_anything():
    """The client's call: the score and its tier leave the operator's view, so
    they must not silently keep steering the token spend either."""
    assert should_write({"icp_tier": "disqualified", "evidence_level": "weak"}) is True
    assert should_write({"icp_tier": "hot", "evidence_level": "none"}) is False


def test_the_prompt_no_longer_carries_the_score():
    """Left in the prompt, the score comes back out IN PROSE inside the angle
    the salesperson reads — the exact opposite of the request."""
    assert "{icp_score}" not in aw.USER_PROMPT_TEMPLATE
    assert "{icp_tier}" not in aw.USER_PROMPT_TEMPLATE
    assert "{icp_rationale}" not in aw.USER_PROMPT_TEMPLATE
    assert "ICP" not in aw.USER_PROMPT_TEMPLATE
    assert "/100" not in aw.USER_PROMPT_TEMPLATE


def test_a_lead_carrying_an_icp_score_still_renders_a_prompt():
    """Regression guard on the template/format pair: a leftover placeholder
    would raise KeyError on the first lead of every run."""
    lead = {"first_name": "Karim", "last_name": "El Amrani", "job_title": "CEO",
            "company": "Acme", "facts_json": '{"pays": "Maroc"}',
            "icp_score": 72, "icp_tier": "warm", "icp_rationale": "r"}
    rendered = aw.USER_PROMPT_TEMPLATE.format(
        first_name=lead["first_name"], last_name=lead["last_name"],
        job_title=lead["job_title"], company=lead["company"],
        facts_json=lead["facts_json"],
    )
    assert "72" not in rendered
    assert "Maroc" in rendered


# ── The hard refusals still protect the writing (processors/icp_scorer.py) ───

def test_a_weakly_evidenced_large_group_is_still_refused_an_angle():
    """icp_scorer returns before the competitor test when evidence is weak, so
    a weak lead used to carry disqualification_reason=None and sail past
    should_write. The single-fact rules now report their reason at every
    evidence level."""
    from datetime import date

    from processors.icp_rules import load_rules
    from processors.icp_scorer import score_lead

    facts = {
        "identite_confirmee": True,
        "pays": {"value": "Maroc", "source": "website"},
        "secteur": {"value": "immobilier", "source": "website"},
        "effectif": {"value": 5000, "source": "perplexity"},
        "est_concurrent": None,
        "maturite_digitale": None,
        "signaux": [],
    }
    result = score_lead(facts, "weak", load_rules(), date(2026, 10, 2))
    lead = {"evidence_level": "weak",
            "disqualification_reason": result.disqualification_reason}
    assert should_write(lead) is False


# ── Honest run status (§8d) ──────────────────────────────────────────────────

def _eligible(n):
    return [
        {"first_name": f"A{i}", "last_name": "B", "company": "Acme",
         "job_title": "CEO", "facts_json": "{}",
         "evidence_level": "sufficient", "disqualification_reason": None}
        for i in range(n)
    ]


def test_every_call_failing_is_recorded_as_degraded_not_ok():
    """The silent failure this closes: a lead with no angle looks exactly like
    a lead that was never eligible, so a total outage recorded "ok"."""
    aw._reset_state()
    reg = ProviderRegistry()

    with patch("enrichers.angle_writer.config.ANTHROPIC_API_KEY", "sk-test"), \
         patch("enrichers.angle_writer.retry_api_call",
               side_effect=RuntimeError("overloaded")), \
         patch("enrichers.angle_writer.time.sleep", return_value=None):
        try:
            write_leads_angles(_eligible(3), registry=reg)
        finally:
            aw._reset_state()

    outcome = reg.to_dict()["anthropic_angles"]
    assert outcome["status"] == "degraded"
    assert "3" in (outcome["reason"] or ""), "say how many calls were lost"


def test_a_spent_credit_balance_is_named_in_the_recorded_reason():
    aw._reset_state()
    reg = ProviderRegistry()

    with patch("enrichers.angle_writer.config.ANTHROPIC_API_KEY", "sk-test"), \
         patch("enrichers.angle_writer.retry_api_call",
               side_effect=CreditExhausted(CREDIT_EXHAUSTED_MESSAGE)), \
         patch("enrichers.angle_writer.time.sleep", return_value=None):
        try:
            write_leads_angles(_eligible(5), registry=reg)
        finally:
            aw._reset_state()

    outcome = reg.to_dict()["anthropic_angles"]
    assert outcome["status"] == "degraded"
    assert "crédits" in outcome["reason"]


def test_a_spent_credit_balance_stops_after_the_first_lead():
    aw._reset_state()
    calls = []

    def _record(*args, **kwargs):
        calls.append(1)
        raise CreditExhausted(CREDIT_EXHAUSTED_MESSAGE)

    with patch("enrichers.angle_writer.config.ANTHROPIC_API_KEY", "sk-test"), \
         patch("enrichers.angle_writer.retry_api_call", side_effect=_record), \
         patch("enrichers.angle_writer.time.sleep", return_value=None):
        try:
            write_leads_angles(_eligible(10), registry=ProviderRegistry())
        finally:
            aw._reset_state()

    assert len(calls) == 1


def test_a_run_with_no_eligible_lead_is_not_reported_as_degraded():
    """Nothing was asked of the API, so nothing failed. Reporting this as an
    outage would cry wolf on every run of poorly evidenced leads."""
    aw._reset_state()
    reg = ProviderRegistry()

    with patch("enrichers.angle_writer.config.ANTHROPIC_API_KEY", "sk-test"):
        try:
            write_leads_angles([{"evidence_level": "none"}], registry=reg)
        finally:
            aw._reset_state()

    assert reg.to_dict()["anthropic_angles"]["status"] == "ok"


def test_a_successful_run_is_recorded_as_ok():
    aw._reset_state()
    reg = ProviderRegistry()

    with patch("enrichers.angle_writer.config.ANTHROPIC_API_KEY", "sk-test"), \
         patch("enrichers.angle_writer.retry_api_call",
               return_value={"activity_summary": "s", "conversion_angle": "a"}), \
         patch("enrichers.angle_writer.time.sleep", return_value=None):
        try:
            leads = write_leads_angles(_eligible(2), registry=reg)
        finally:
            aw._reset_state()

    assert reg.to_dict()["anthropic_angles"]["status"] == "ok"
    assert all(l["conversion_angle"] == "a" for l in leads)
