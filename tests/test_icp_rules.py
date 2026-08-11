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


# ── Country canonicalization ────────────────────────────────────────────────

@pytest.mark.parametrize("label,canonical", [
    ("Morocco", "Maroc"),
    ("morocco", "Maroc"),
    ("Maroc (Casablanca)", "Maroc"),
    ("Casablanca", "Maroc"),
    ("Tunisia", "Tunisie"),
    ("Ivory Coast", "Côte d'Ivoire"),
    ("Belgium", "Belgique"),
    ("Quebec", "Canada"),
    ("United States", "États-Unis"),
])
def test_canonical_country_resolves_common_labels(label, canonical):
    assert load_rules().canonical_country(label) == canonical


def test_canonical_country_returns_none_for_an_unknown_label():
    """None must read as "unknown", never as "out of zone"."""
    rules = load_rules()
    assert rules.canonical_country("Zzz") is None
    assert rules.canonical_country("") is None
    assert rules.canonical_country("   ") is None


def test_canonical_country_prefers_the_longest_alias():
    # "congo" is an alias of Congo and a substring of the RDC aliases;
    # dictionary order must not decide this.
    rules = load_rules()
    assert rules.canonical_country("Democratic Republic of the Congo") == "RDC"
    assert rules.canonical_country("Congo-Brazzaville") == "Congo"


def test_alias_matching_respects_word_boundaries():
    # "Niger" is in zone, "Nigeria" is not: a substring match would merge them.
    rules = load_rules()
    assert rules.canonical_country("Nigeria") == "Nigeria"
    assert rules.canonical_country("Niger") == "Niger"
    assert rules.country_zone("Niger") == "afrique_francophone"
    assert rules.country_zone("Nigeria") is None


def test_every_zone_country_is_recognised():
    """A zone country that canonicalization cannot recognise would be scored
    for its zone but reported as unknown by canonical_country — the two must
    never disagree."""
    rules = load_rules()
    for zone, countries in rules.zone_countries.items():
        for country in countries:
            assert rules.canonical_country(country) is not None, country
            assert rules.country_zone(country) == zone, country


def test_missing_rules_file_names_the_expected_path(tmp_path):
    missing = tmp_path / "nope" / "icp_rules.json"
    with pytest.raises(FileNotFoundError, match="icp_rules:"):
        load_rules(str(missing))


def test_malformed_rules_file_is_reported_clearly(tmp_path):
    broken = tmp_path / "broken.json"
    broken.write_text("{ not json", encoding="utf-8")
    with pytest.raises(ValueError, match="icp_rules:"):
        load_rules(str(broken))


def test_competitor_keywords_no_longer_exist():
    """Dead config invites the belief that something reads it. Nothing did."""
    rules = load_rules()
    assert not hasattr(rules, "competitor_keywords")


# ── Sector canonicalization ──────────────────────────────────────────────────

@pytest.mark.parametrize("label,canonical", [
    ("hôtellerie restauration", "tourisme"),
    ("hôtellerie", "tourisme"),
    ("restauration", "tourisme"),
    ("recherche clinique", "sante"),
    ("santé", "sante"),
    ("pharmaceutique", "sante"),
    ("biotechnologie", "sante"),
    ("conseil qualité", "services b2b"),
    ("conseil digital", "services b2b"),
    ("conseil", "services b2b"),
    ("ingénierie", "services b2b"),
    ("datacenters", "saas"),
    ("infrastructure informatique", "saas"),
    ("logiciel", "saas"),
    ("informatique", "saas"),
    ("logement social", "immobilier"),
    ("immobilier résidentiel", "immobilier"),
    ("promotion immobilière", "immobilier"),
    ("formation", "education"),
    ("enseignement", "education"),
    ("immobilier", "immobilier"),  # canonical label itself still resolves
    ("SANTE", "sante"),            # case-insensitive
])
def test_canonical_sector_resolves_pilot_run_labels(label, canonical):
    assert load_rules().canonical_sector(label) == canonical


def test_canonical_sector_returns_none_for_an_unknown_label():
    """None must read as "unknown", never as "excluded" or "high value"."""
    rules = load_rules()
    assert rules.canonical_sector("vente de mobilier de jardin") is None
    assert rules.canonical_sector("") is None
    assert rules.canonical_sector(None) is None


def test_canonical_sector_matches_exactly_not_by_substring():
    # Regression: a substring test previously matched "sante" inside
    # "industrie croissante" ("crois-*sante*").
    rules = load_rules()
    assert rules.canonical_sector("industrie croissante") is None


def test_canonical_sector_resolves_excluded_labels_too():
    rules = load_rules()
    assert rules.canonical_sector("agriculture") == "agriculture"
    assert rules.canonical_sector("Agriculture") == "agriculture"
