from unittest.mock import patch

import enrichers.angle_writer as aw
from api.provider_status import ProviderRegistry
from enrichers.angle_writer import should_write, write_leads_angles
from enrichers.retry import CREDIT_EXHAUSTED_MESSAGE, CreditExhausted


def test_disqualified_lead_gets_no_angle():
    assert should_write({"icp_tier": "disqualified"}) is False


def test_unverified_lead_gets_no_angle():
    assert should_write({"icp_tier": "cold", "evidence_verified": False}) is False


def test_verified_cold_lead_still_gets_an_angle():
    assert should_write({"icp_tier": "cold", "evidence_verified": True}) is True


def test_hot_lead_gets_an_angle():
    assert should_write({"icp_tier": "hot", "evidence_verified": True}) is True


def test_well_evidenced_disqualified_lead_still_gets_no_angle():
    # The row that actually exercises the disqualification short-circuit:
    # without it, evidence_verified=True would let this lead through.
    assert should_write({"icp_tier": "disqualified", "evidence_verified": True}) is False


# ── Honest run status (§8d) ──────────────────────────────────────────────────

def _eligible(n):
    return [
        {"first_name": f"A{i}", "last_name": "B", "company": "Acme",
         "job_title": "CEO", "icp_tier": "warm", "icp_score": 60,
         "icp_rationale": "r", "facts_json": "{}", "evidence_verified": True}
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
            write_leads_angles([{"icp_tier": "cold", "evidence_verified": False}],
                               registry=reg)
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
