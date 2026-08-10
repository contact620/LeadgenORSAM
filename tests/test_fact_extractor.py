from enrichers.fact_extractor import VALID_SOURCES, sanitize_facts


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


def test_competitor_flag_is_coerced_to_bool():
    assert sanitize_facts({"est_concurrent": "true"})["est_concurrent"] is True
    assert sanitize_facts({})["est_concurrent"] is False


def test_headcount_string_is_coerced_to_int():
    raw = {"effectif": {"value": "45", "source": "perplexity"}}
    assert sanitize_facts(raw)["effectif"]["value"] == 45


def test_unparseable_headcount_is_dropped():
    raw = {"effectif": {"value": "une cinquantaine", "source": "perplexity"}}
    assert sanitize_facts(raw)["effectif"] is None


def test_valid_sources_are_the_three_expected():
    assert VALID_SOURCES == frozenset({"website", "linkedin", "perplexity"})
