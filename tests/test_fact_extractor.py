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
from enrichers.retry import AuthError
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


def test_missing_api_key_is_recorded_as_skipped():
    fx._reset_state()
    reg = ProviderRegistry()
    with patch("enrichers.fact_extractor.config.ANTHROPIC_API_KEY", ""):
        leads = extract_leads_facts(_leads(2), frozenset({"website"}), registry=reg)
    assert reg.to_dict()["anthropic_facts"]["status"] == "skipped"
    assert all(l["evidence_level"] == "none" for l in leads)
