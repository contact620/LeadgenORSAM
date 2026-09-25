import json

import pytest

from processors.icp_rules import IcpRules, load_rules, normalize_label


@pytest.fixture
def rules():
    return load_rules()


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
    # Niger and Nigeria are both in zone since Task 19 (décision 2), but in
    # two different ones: a substring match would merge them into the same
    # zone, which is exactly the regression this test guards against.
    rules = load_rules()
    assert rules.canonical_country("Nigeria") == "Nigeria"
    assert rules.canonical_country("Niger") == "Niger"
    assert rules.country_zone("Niger") == "afrique_francophone"
    assert rules.country_zone("Nigeria") == "reste_afrique"


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
    ("logiciel", "saas"),
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


@pytest.mark.parametrize("label", [
    "datacenters",
    "infrastructure informatique",
    "informatique",
    "logement social",
    "ingénierie",
])
def test_adjacent_sectors_are_deliberately_not_aliased(label):
    """
    An alias is a synonym, never a classification judgement.

    These labels appeared in the 10-lead pilot and were briefly aliased to a
    high-value sector, which handed each affected lead +10 points and moved
    JERLAURE (a datacenter *builder*) and OPH 05 (a public housing body) from
    cold to warm. Neither sells through digital acquisition, so the promotion
    was flattering rather than accurate. They resolve to None and score
    `other` (50) — "we know what they do, it just is not a priority".

    Revisit only with real conversion data from BoxCom's own client base.
    """
    assert load_rules().canonical_sector(label) is None


def test_canonical_sector_matches_exactly_not_by_substring():
    # Regression: a substring test previously matched "sante" inside
    # "industrie croissante" ("crois-*sante*").
    rules = load_rules()
    assert rules.canonical_sector("industrie croissante") is None


def test_canonical_sector_resolves_excluded_labels_too():
    rules = load_rules()
    assert rules.canonical_sector("agriculture") == "agriculture"
    assert rules.canonical_sector("Agriculture") == "agriculture"


# ── Geography (décision 2): Africa widened, Europe secondary ────────────────

@pytest.mark.parametrize("country,zone", [
    ("Maroc", "maroc"), ("Morocco", "maroc"), ("Casablanca", "maroc"),
    ("Sénégal", "afrique_francophone"), ("Côte d'Ivoire", "afrique_francophone"),
    ("Nigeria", "reste_afrique"), ("Ghana", "reste_afrique"),
    ("Kenya", "reste_afrique"), ("Égypte", "reste_afrique"),
    ("Afrique du Sud", "reste_afrique"), ("Ethiopie", "reste_afrique"),
    ("France", "france"), ("Belgique", "francophonie_elargie"),
    ("Canada", "francophonie_elargie"),
])
def test_countries_land_in_the_expected_zone(rules, country, zone):
    assert rules.country_zone(country) == zone


@pytest.mark.parametrize("zone,points", [
    ("maroc", 100), ("afrique_francophone", 90), ("reste_afrique", 70),
    ("france", 20), ("francophonie_elargie", 10),
])
def test_zone_points_match_the_validated_scale(rules, zone, points):
    assert rules.zone_points[zone] == points


def test_europe_is_no_longer_out_of_zone(rules):
    """Décision 2: Europe stays relevant but secondary. It must resolve to a
    zone — an unrecognised country is what triggers disqualification."""
    for country in ("France", "Belgique", "Suisse", "Luxembourg", "Canada"):
        assert rules.country_zone(country) is not None


def test_a_country_outside_every_zone_still_resolves_to_none(rules):
    assert rules.country_zone("Japon") is None
    assert rules.country_zone("Zzz") is None


def test_the_african_floor_stays_above_the_european_ceiling(rules):
    """The client targets Africa first: no European zone may outrank the
    weakest African one."""
    african = min(rules.zone_points[z] for z in
                  ("maroc", "afrique_francophone", "reste_afrique"))
    european = max(rules.zone_points[z] for z in ("france", "francophonie_elargie"))
    assert african > european
