from unittest.mock import patch

import enrichers.fact_extractor as fx
from api.provider_status import ProviderRegistry
from enrichers.fact_extractor import (
    VALID_SOURCES,
    _EMPTY_FACTS,
    build_system_prompt,
    extract_leads_facts,
    sanitize_facts,
)
from enrichers.retry import (
    CREDIT_EXHAUSTED_MESSAGE,
    AuthError,
    CreditExhausted,
)
from processors.icp_rules import load_rules


def test_unsourced_scalar_fact_is_dropped():
    raw = {"secteur": {"value": "immobilier"}, "identite_confirmee": True}
    assert sanitize_facts(raw)["secteur"] is None


def test_fact_with_unknown_source_is_dropped():
    raw = {"secteur": {"value": "immobilier", "source": "intuition"}}
    assert sanitize_facts(raw)["secteur"] is None


def test_properly_sourced_fact_survives():
    raw = {"secteur": {"value": "immobilier", "source": "website"}}
    assert sanitize_facts(raw)["secteur"] == {"value": "immobilier", "source": "website"}


def test_unsourced_signal_is_dropped_but_sourced_one_kept():
    raw = {"signaux": [
        {"type": "levee_de_fonds", "date": "2026-05", "source": "perplexity", "citation": "a"},
        {"type": "rumeur", "date": "2026-05", "citation": "b"},
    ]}
    signals = sanitize_facts(raw)["signaux"]
    assert len(signals) == 1
    assert signals[0]["type"] == "levee_de_fonds"


def test_missing_identity_defaults_to_false():
    assert sanitize_facts({})["identite_confirmee"] is False


def test_sourced_competitor_flag_survives_as_a_sourced_fact():
    raw = {"est_concurrent": {"value": True, "source": "website"}}
    assert sanitize_facts(raw)["est_concurrent"] == {"value": True, "source": "website"}


def test_sourced_competitor_flag_accepts_a_string_true():
    raw = {"est_concurrent": {"value": "true", "source": "perplexity"}}
    assert sanitize_facts(raw)["est_concurrent"] == {"value": True, "source": "perplexity"}


def test_bare_competitor_boolean_is_dropped():
    """A source is required here as for every other fact.

    est_concurrent is the only disqualification that applies even at
    evidence_level = "none", so a bare boolean the model can assert from the
    company name alone must not reach the scorer.
    """
    assert sanitize_facts({"est_concurrent": True})["est_concurrent"] is None
    assert sanitize_facts({"est_concurrent": "true"})["est_concurrent"] is None
    assert sanitize_facts({})["est_concurrent"] is None


def test_competitor_with_unknown_source_is_dropped():
    raw = {"est_concurrent": {"value": True, "source": "intuition"}}
    assert sanitize_facts(raw)["est_concurrent"] is None


def test_sourced_competitor_false_is_dropped():
    """A sourced "not a competitor" carries no consequence; only True does."""
    raw = {"est_concurrent": {"value": False, "source": "website"}}
    assert sanitize_facts(raw)["est_concurrent"] is None


def test_headcount_string_is_coerced_to_int():
    raw = {"effectif": {"value": "45", "source": "perplexity"}}
    assert sanitize_facts(raw)["effectif"]["value"] == 45


def test_unparseable_headcount_is_dropped():
    raw = {"effectif": {"value": "une cinquantaine", "source": "perplexity"}}
    assert sanitize_facts(raw)["effectif"] is None


def test_valid_sources_are_the_three_expected():
    assert VALID_SOURCES == frozenset({"website", "linkedin", "perplexity"})


def test_non_dict_input_returns_complete_shape():
    for bad in ([], "texte", 42, True, None):
        facts = sanitize_facts(bad)
        assert facts["identite_confirmee"] is False
        assert facts["est_concurrent"] is None
        assert facts["signaux"] == []
        assert facts["secteur"] is None


def test_non_list_signaux_is_ignored():
    facts = sanitize_facts({"signaux": "levée de fonds"})
    assert facts["signaux"] == []


def test_negative_headcount_is_dropped():
    raw = {"effectif": {"value": -5, "source": "perplexity"}}
    assert sanitize_facts(raw)["effectif"] is None


def test_zero_headcount_is_treated_as_unsourced():
    """A model rendering "effectif non communiqué" as 0 must not disqualify.

    Kept as a value, 0 falls under size_disqualify_below and produces
    "micro-entreprise — 0 employés" — a definitive verdict built on a missing
    number.
    """
    raw = {"effectif": {"value": 0, "source": "perplexity"}}
    assert sanitize_facts(raw)["effectif"] is None


def test_zero_digital_maturity_is_treated_as_unsourced():
    # The maturity scale runs 1-10; a 0 is a missing value, not a reading.
    raw = {"maturite_digitale": {"value": 0, "source": "perplexity"}}
    assert sanitize_facts(raw)["maturite_digitale"] is None


# ── Blast radius of a single auth failure (the riskiest path in the branch) ──

def _leads(n):
    return [
        {"first_name": f"A{i}", "last_name": "B", "company": "Acme",
         "job_title": "CEO", "location": "Casablanca, Maroc",
         "website_text": "x" * 500, "website_coherent": True}
        for i in range(n)
    ]


def test_auth_failure_leaves_every_remaining_lead_in_a_complete_shape():
    """One AuthError disables extraction for the whole run.

    Every remaining lead must still come out with the full fact shape and
    evidence_level = "none" — a missing key downstream would crash the scorer,
    and a stale evidence_level would let an unevidenced lead keep a score.
    """
    fx._reset_state()
    reg = ProviderRegistry()
    leads = _leads(4)

    with patch("enrichers.fact_extractor.config.ANTHROPIC_API_KEY", "sk-test"), \
         patch("enrichers.fact_extractor.retry_api_call",
               side_effect=AuthError("401 invalid x-api-key")), \
         patch("enrichers.fact_extractor.time.sleep", return_value=None):
        try:
            result = extract_leads_facts(leads, frozenset({"website"}), registry=reg)
        finally:
            fx._reset_state()

    assert len(result) == 4
    for lead in result:
        assert set(lead["facts"].keys()) == set(_EMPTY_FACTS.keys())
        assert lead["facts"]["identite_confirmee"] is False
        assert lead["facts"]["est_concurrent"] is None
        assert lead["evidence_level"] == "none"
        assert lead["facts_json"]


def test_auth_failure_is_recorded_as_degraded_not_ok():
    """The run scores the whole portfolio cold; it must not report as healthy."""
    fx._reset_state()
    reg = ProviderRegistry()

    with patch("enrichers.fact_extractor.config.ANTHROPIC_API_KEY", "sk-test"), \
         patch("enrichers.fact_extractor.retry_api_call",
               side_effect=AuthError("401 invalid x-api-key")), \
         patch("enrichers.fact_extractor.time.sleep", return_value=None):
        try:
            extract_leads_facts(_leads(3), frozenset({"website"}), registry=reg)
        finally:
            fx._reset_state()

    assert reg.to_dict()["anthropic_facts"]["status"] == "degraded"


def test_auth_failure_stops_calling_the_api_after_the_first_lead():
    """_extractor_disabled must short-circuit, not retry 200 times."""
    fx._reset_state()
    calls = []

    def _record(*args, **kwargs):
        calls.append(1)
        raise AuthError("401")

    with patch("enrichers.fact_extractor.config.ANTHROPIC_API_KEY", "sk-test"), \
         patch("enrichers.fact_extractor.retry_api_call", side_effect=_record), \
         patch("enrichers.fact_extractor.time.sleep", return_value=None):
        try:
            extract_leads_facts(_leads(10), frozenset({"website"}), registry=ProviderRegistry())
        finally:
            fx._reset_state()

    assert len(calls) == 1


# ── Closed sector vocabulary (built from config/icp_rules.json) ─────────────
# Pilot run: the model's free-text sector labels never matched
# high_value_sectors, so 9 leads out of 10 fell back to the "other" score.
# The prompt must offer a closed list built from the same file the scorer
# reads, so the two never drift apart.

def test_system_prompt_includes_every_sector_label_from_the_rules_file():
    rules = load_rules()
    prompt = build_system_prompt(rules)
    for label in rules.high_value_sectors + rules.excluded_sectors:
        assert label in prompt, label
    assert "autre" in prompt


def test_system_prompt_has_no_leftover_placeholder_token():
    # The vocabulary is injected via a literal-token replace() rather than
    # str.format(), because the prompt's JSON example contains literal
    # braces that format() would otherwise choke on. Guard the substitution
    # itself: a missed replace would ship the raw token to the model.
    prompt = build_system_prompt(load_rules())
    assert "__SECTEUR_VALEURS__" not in prompt


# ── Signal deduplication (Astrak pilot case, 2026-08-11) ────────────────────
# Perplexity reported "expansion" dated 2026-05 twice; the scorer counted 3
# signals (100 points) instead of 2 (70 points) — a 12-point score inflation
# from one duplicate. Dedup runs on (type, date) after the source filter.

def test_astrak_duplicate_expansion_signal_is_collapsed_to_two():
    raw = {"signaux": [
        {"type": "expansion", "date": "2026-05", "source": "perplexity", "citation": "a"},
        {"type": "expansion", "date": "2026-05", "source": "perplexity", "citation": "a (bis)"},
        {"type": "lancement", "date": "2025-06", "source": "perplexity", "citation": "b"},
    ]}
    signals = sanitize_facts(raw)["signaux"]
    assert len(signals) == 2
    assert [s["type"] for s in signals] == ["expansion", "lancement"]


def test_signal_dedup_ignores_case_and_surrounding_whitespace():
    raw = {"signaux": [
        {"type": "Expansion", "date": " 2026-05 ", "source": "perplexity", "citation": "a"},
        {"type": " expansion ", "date": "2026-05", "source": "perplexity", "citation": "a (bis)"},
    ]}
    signals = sanitize_facts(raw)["signaux"]
    assert len(signals) == 1
    assert signals[0]["citation"] == "a"


def test_signal_dedup_keeps_the_first_occurrence_in_order():
    raw = {"signaux": [
        {"type": "recrutement", "date": "2026-01", "source": "website", "citation": "first"},
        {"type": "expansion", "date": "2026-05", "source": "perplexity", "citation": "second"},
        {"type": "recrutement", "date": "2026-01", "source": "perplexity", "citation": "dup"},
    ]}
    signals = sanitize_facts(raw)["signaux"]
    assert len(signals) == 2
    assert signals[0]["citation"] == "first"
    assert signals[1]["citation"] == "second"


def test_same_type_different_dates_are_not_deduplicated():
    raw = {"signaux": [
        {"type": "expansion", "date": "2026-05", "source": "perplexity", "citation": "a"},
        {"type": "expansion", "date": "2025-11", "source": "perplexity", "citation": "b"},
    ]}
    signals = sanitize_facts(raw)["signaux"]
    assert len(signals) == 2


def test_different_types_same_date_are_not_deduplicated():
    raw = {"signaux": [
        {"type": "expansion", "date": "2026-05", "source": "perplexity", "citation": "a"},
        {"type": "lancement", "date": "2026-05", "source": "perplexity", "citation": "b"},
    ]}
    signals = sanitize_facts(raw)["signaux"]
    assert len(signals) == 2


def test_nothing_deduplicated_when_all_signals_are_distinct():
    raw = {"signaux": [
        {"type": "recrutement", "date": "2026-01", "source": "website", "citation": "a"},
        {"type": "expansion", "date": "2026-05", "source": "perplexity", "citation": "b"},
        {"type": "lancement", "date": "2025-06", "source": "perplexity", "citation": "c"},
    ]}
    signals = sanitize_facts(raw)["signaux"]
    assert len(signals) == 3


def test_missing_api_key_is_recorded_as_skipped():
    fx._reset_state()
    reg = ProviderRegistry()
    with patch("enrichers.fact_extractor.config.ANTHROPIC_API_KEY", ""):
        leads = extract_leads_facts(_leads(2), frozenset({"website"}), registry=reg)
    assert reg.to_dict()["anthropic_facts"]["status"] == "skipped"
    assert all(l["evidence_level"] == "none" for l in leads)


# ── Honest run status (§8d) ──────────────────────────────────────────────────

def test_every_call_failing_is_recorded_as_degraded_not_ok():
    """The silent failure this closes: transient errors are not AuthError, so
    the step stayed enabled, returned empty facts for all 20 leads and then
    recorded "ok". The run came out green with no AI columns at all."""
    fx._reset_state()
    reg = ProviderRegistry()

    with patch("enrichers.fact_extractor.config.ANTHROPIC_API_KEY", "sk-test"), \
         patch("enrichers.fact_extractor.retry_api_call",
               side_effect=RuntimeError("overloaded")), \
         patch("enrichers.fact_extractor.time.sleep", return_value=None):
        try:
            extract_leads_facts(_leads(3), frozenset({"website"}), registry=reg)
        finally:
            fx._reset_state()

    outcome = reg.to_dict()["anthropic_facts"]
    assert outcome["status"] == "degraded"
    assert "3" in (outcome["reason"] or ""), "say how many calls were lost"


def test_a_spent_credit_balance_is_named_in_the_recorded_reason():
    """"clé Anthropic refusée" would send the operator to the wrong screen."""
    fx._reset_state()
    reg = ProviderRegistry()

    with patch("enrichers.fact_extractor.config.ANTHROPIC_API_KEY", "sk-test"), \
         patch("enrichers.fact_extractor.retry_api_call",
               side_effect=CreditExhausted(CREDIT_EXHAUSTED_MESSAGE)), \
         patch("enrichers.fact_extractor.time.sleep", return_value=None):
        try:
            extract_leads_facts(_leads(5), frozenset({"website"}), registry=reg)
        finally:
            fx._reset_state()

    outcome = reg.to_dict()["anthropic_facts"]
    assert outcome["status"] == "degraded"
    assert "crédits" in outcome["reason"]


def test_a_spent_credit_balance_stops_after_the_first_lead():
    fx._reset_state()
    calls = []

    def _record(*args, **kwargs):
        calls.append(1)
        raise CreditExhausted(CREDIT_EXHAUSTED_MESSAGE)

    with patch("enrichers.fact_extractor.config.ANTHROPIC_API_KEY", "sk-test"), \
         patch("enrichers.fact_extractor.retry_api_call", side_effect=_record), \
         patch("enrichers.fact_extractor.time.sleep", return_value=None):
        try:
            extract_leads_facts(_leads(10), frozenset({"website"}),
                                registry=ProviderRegistry())
        finally:
            fx._reset_state()

    assert len(calls) == 1


def test_a_working_run_that_confirms_no_identity_is_still_ok():
    """Zero confirmed identities is not a fault: thin evidence legitimately
    produces it. Only a failed call is a fault, which is why the health
    verdict counts calls and not confirmations."""
    fx._reset_state()
    reg = ProviderRegistry()

    with patch("enrichers.fact_extractor.config.ANTHROPIC_API_KEY", "sk-test"), \
         patch("enrichers.fact_extractor.retry_api_call",
               return_value=dict(_EMPTY_FACTS)), \
         patch("enrichers.fact_extractor.time.sleep", return_value=None):
        try:
            extract_leads_facts(_leads(3), frozenset({"website"}), registry=reg)
        finally:
            fx._reset_state()

    assert reg.to_dict()["anthropic_facts"]["status"] == "ok"


def test_a_run_with_no_leads_is_not_reported_as_degraded():
    """Nothing was asked of the API, so nothing failed."""
    fx._reset_state()
    reg = ProviderRegistry()

    with patch("enrichers.fact_extractor.config.ANTHROPIC_API_KEY", "sk-test"):
        try:
            extract_leads_facts([], frozenset({"website"}), registry=reg)
        finally:
            fx._reset_state()

    assert reg.to_dict()["anthropic_facts"]["status"] == "ok"


# ── Person material reaches the prompt (task 10) ──────────────────────────────

def _capture_user_prompt(lead, enabled=frozenset({"website", "perplexity"})):
    """Run one real extraction against a fake Anthropic client and return the
    user prompt that was actually sent."""
    from unittest.mock import MagicMock

    sent = {}

    def _create(**kwargs):
        sent["prompt"] = kwargs["messages"][0]["content"]
        block = MagicMock()
        block.text = '{"identite_confirmee": true}'
        message = MagicMock()
        message.content = [block]
        return message

    client = MagicMock()
    client.messages.create.side_effect = _create

    fx._reset_state()
    with patch("enrichers.fact_extractor.config.ANTHROPIC_API_KEY", "sk-test"), \
         patch("enrichers.fact_extractor.anthropic.Anthropic", return_value=client), \
         patch("enrichers.fact_extractor.time.sleep", return_value=None):
        try:
            extract_leads_facts([lead], enabled, registry=ProviderRegistry())
        finally:
            fx._reset_state()
    return sent["prompt"]


def test_the_person_research_reaches_the_extraction_prompt():
    """The search is paid for per lead; a field the extractor never reads is a
    credit spent for nothing."""
    lead = dict(_leads(1)[0],
                person_research="Poste actuel : directrice marketing depuis 2026-06",
                digital_maturity="Score: 4/10")
    prompt = _capture_user_prompt(lead)
    assert "directrice marketing depuis 2026-06" in prompt
    assert "Score: 4/10" in prompt


def test_the_google_snippets_reach_the_extraction_prompt_as_a_linkedin_source():
    """"linkedin" is in VALID_SOURCES but nothing in the prompt was ever
    labelled that way, so the model could never legitimately use it."""
    lead = dict(_leads(1)[0],
                linkedin_snippets="- Amal Benali — Directrice marketing chez Acme "
                                  "(https://www.linkedin.com/in/amal-b)")
    prompt = _capture_user_prompt(lead)
    assert 'SOURCE "linkedin"' in prompt
    assert "Directrice marketing chez Acme" in prompt


def test_a_lead_without_person_material_renders_an_explicit_absence():
    """Not the word "None": a model reading "None" as content invents around
    it."""
    prompt = _capture_user_prompt(_leads(1)[0])
    assert "None" not in prompt
    assert prompt.count("Non disponible") >= 2
