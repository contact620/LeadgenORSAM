import json
from datetime import date
from unittest.mock import MagicMock, patch

import enrichers.angle_writer as aw
from api.provider_status import ProviderRegistry
from enrichers.angle_writer import should_write, write_leads_angles
from enrichers.retry import CREDIT_EXHAUSTED_MESSAGE, CreditExhausted
from processors.icp_rules import load_rules


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


def _capture_user_prompt(lead, run_date=date(2026, 10, 2)):
    """Run one real writing pass against a fake client and return the prompt
    that was actually sent — the template and its format() call must stay in
    step, or the first lead of every run raises KeyError."""
    sent = {}

    def _create(**kwargs):
        sent["prompt"] = kwargs["messages"][0]["content"]
        block = MagicMock()
        block.text = '{"activity_summary": "s", "conversion_angle": "a"}'
        message = MagicMock()
        message.content = [block]
        return message

    client = MagicMock()
    client.messages.create.side_effect = _create

    aw._reset_state()
    with patch("enrichers.angle_writer.config.ANTHROPIC_API_KEY", "sk-test"), \
         patch("enrichers.angle_writer.anthropic.Anthropic", return_value=client), \
         patch("enrichers.angle_writer.time.sleep", return_value=None):
        try:
            write_leads_angles([lead], registry=ProviderRegistry(), run_date=run_date)
        finally:
            aw._reset_state()
    return sent["prompt"]


def test_a_lead_carrying_an_icp_score_sends_none_of_it():
    lead = {"first_name": "Karim", "last_name": "El Amrani", "job_title": "CEO",
            "company": "Acme", "facts_json": '{"pays": "Maroc"}',
            "evidence_level": "sufficient",
            "icp_score": 72, "icp_tier": "warm", "icp_rationale": "r"}
    prompt = _capture_user_prompt(lead)
    assert "72" not in prompt
    assert "Maroc" in prompt


# ── The consolidated angle (task 12) ─────────────────────────────────────────

def _appointment(month="2026-08", kind="nouvelle_entreprise"):
    return {"value": month, "type": kind, "source": "linkedin",
            "citation": "A rejoint Acme"}


def _lead_with(appointment=None, **kw):
    facts = {"identite_confirmee": True,
             "secteur": {"value": "immobilier", "source": "website"},
             "prise_de_poste": appointment}
    lead = {"first_name": "Amal", "last_name": "Benali",
            "job_title": "Directrice marketing", "company": "Acme",
            "evidence_level": "sufficient", "facts": facts}
    lead.update(kw)
    return lead


def test_the_system_prompt_asks_for_the_person_and_the_company():
    """An angle that only talks about the company misses half the job."""
    assert "PERSONNE" in aw.SYSTEM_PROMPT
    assert "ENTREPRISE" in aw.SYSTEM_PROMPT


def test_the_bans_are_still_in_place():
    assert "leader du marché" in aw.SYSTEM_PROMPT
    assert "acteur de référence" in aw.SYSTEM_PROMPT


def test_the_writer_is_told_to_open_on_a_recent_appointment():
    prompt = _capture_user_prompt(_lead_with(_appointment()))
    assert "SIGNAL PRIORITAIRE" in prompt
    assert "2026-08" in prompt
    assert "arrivée dans une nouvelle entreprise" in prompt


def test_a_promotion_is_named_as_a_promotion_not_an_arrival():
    prompt = _capture_user_prompt(_lead_with(_appointment(kind="nouveau_poste")))
    assert "nouveau poste dans la même entreprise" in prompt


def test_the_writer_is_never_given_the_source_of_the_appointment():
    """The instruction states the move and its date. Sources are withheld from
    this step by design — it verifies nothing, so it is given nothing to
    verify."""
    prompt = _capture_user_prompt(_lead_with(_appointment()))
    notice = prompt.split("SIGNAL PRIORITAIRE")[1]
    assert "linkedin" not in notice
    assert "A rejoint Acme" not in notice


def test_an_old_appointment_does_not_lead_the_angle():
    """"Vous venez de prendre vos fonctions" addressed to someone in post for
    three years reads as a form letter. The fact stays true and stays in
    facts_json; it simply stops being the hook."""
    prompt = _capture_user_prompt(_lead_with(_appointment(month="2023-01")))
    assert "SIGNAL PRIORITAIRE" not in prompt
    assert "2023-01" in prompt, "the fact itself is still transmitted"


def test_a_lead_without_an_appointment_gets_no_priority_instruction():
    """Rule 6: with no appointment in the facts, inventing congratulations is
    an invention like any other."""
    prompt = _capture_user_prompt(_lead_with(None))
    assert "SIGNAL PRIORITAIRE" not in prompt
    assert "prise de poste" not in prompt


def test_an_unsourced_or_malformed_appointment_never_reaches_the_instruction():
    for broken in ("depuis juin", True, {}, {"value": "2026-08"},
                   {"value": "2026-08", "type": "promotion"},
                   {"type": "nouveau_poste"}):
        lead = _lead_with(broken)
        assert aw.recent_appointment(lead, load_rules(), date(2026, 10, 2)) is None, broken


def test_the_appointment_window_is_the_one_the_scorer_uses():
    """One number for one notion of recency: the operator tunes
    icp_rules.signal_recency_months, not two thresholds."""
    rules = load_rules()
    today = date(2026, 10, 2)
    inside = _lead_with(_appointment(month="2026-05"))   # 5 months
    outside = _lead_with(_appointment(month="2025-10"))  # 12 months
    assert rules.signal_recency_months == 6
    assert aw.recent_appointment(inside, rules, today) is not None
    assert aw.recent_appointment(outside, rules, today) is None


def test_an_appointment_dated_in_the_future_is_not_recent():
    """A negative age is a corrupted date, not a fresher signal."""
    lead = _lead_with(_appointment(month="2027-03"))
    assert aw.recent_appointment(lead, load_rules(), date(2026, 10, 2)) is None


def test_the_appointment_is_read_from_stored_json_too():
    """The enrich-only flow replays facts_json from the pool; lead["facts"] is
    not always the dict."""
    lead = _lead_with(_appointment())
    lead["facts_json"] = json.dumps(lead.pop("facts"), ensure_ascii=False)
    assert aw.recent_appointment(lead, load_rules(), date(2026, 10, 2)) is not None


def test_unreadable_stored_facts_do_not_crash_the_writer():
    for broken in ("", "not json", "[1, 2]", None):
        lead = {"facts_json": broken}
        assert aw.recent_appointment(lead, load_rules(), date(2026, 10, 2)) is None


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
