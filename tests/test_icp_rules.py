import json

import pytest

from processors.icp_rules import IcpRules, load_rules, normalize_label


def test_default_rules_load():
    rules = load_rules()
    assert isinstance(rules, IcpRules)
    assert rules.weights["signaux"] == 0.40


def test_weights_sum_to_one():
    rules = load_rules()
    assert round(sum(rules.weights.values()), 6) == 1.0


def test_zone_countries_cover_zone_points():
    rules = load_rules()
    for zone in rules.zone_points:
        assert zone in rules.zone_countries, f"zone '{zone}' has points but no country list"


def test_tier_thresholds_are_ordered():
    rules = load_rules()
    assert rules.tier_hot_min > rules.tier_warm_min > rules.unverified_score_cap


def test_invalid_weights_are_rejected(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"weights": {"secteur": 0.9, "taille": 0.9,
                                           "localisation": 0.1, "signaux": 0.1}}),
                   encoding="utf-8")
    with pytest.raises(ValueError, match="weights"):
        load_rules(str(bad))


# ── Label normalization (case/accent-insensitive matching) ──────────────────

def test_normalize_label_strips_accents_case_and_whitespace():
    assert normalize_label("Maroc") == "maroc"
    assert normalize_label("MAROC") == "maroc"
    assert normalize_label(" Maroc ") == "maroc"
    assert normalize_label("Sénégal") == "senegal"
    assert normalize_label("") == ""


@pytest.mark.parametrize("country", ["maroc", "MAROC", " Maroc ", "Maroc"])
def test_country_zone_is_case_and_accent_insensitive(country):
    # Regression: a sourced fact rarely comes back in the exact casing used
    # in zone_countries. A mismatch here silently disqualified a lead that
    # was squarely in the ideal zone.
    rules = load_rules()
    assert rules.country_zone(country) == "maroc"


def test_normalize_label_folds_curly_apostrophes():
    # Regression: an LLM extraction typically returns the typographic
    # apostrophe (U+2019), not the straight one (U+0027) used in
    # config/icp_rules.json's "Côte d'Ivoire". Left unfolded, this
    # cosmetic difference alone disqualified an in-zone country.
    assert normalize_label("Côte d’Ivoire") == normalize_label("Côte d'Ivoire")
    assert normalize_label("Côte d‘Ivoire") == normalize_label("Côte d'Ivoire")
    assert normalize_label("Côte dʼIvoire") == normalize_label("Côte d'Ivoire")


def test_country_zone_matches_curly_apostrophe_variant():
    rules = load_rules()
    assert rules.country_zone("Côte d’Ivoire") == "afrique_francophone"
