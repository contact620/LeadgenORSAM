import pytest

from processors.icp_rules import load_rules
from processors.prescore import apply_prescores, compute_prescore, rank_for_spending


@pytest.fixture
def rules():
    return load_rules()


def _lead(**over):
    base = {"first_name": "Karim", "last_name": "El Amrani",
            "company": "Acme", "location": "Casablanca, Maroc",
            "employee_count": 45, "apollo_industry": "e-commerce"}
    base.update(over)
    return base


def test_a_perfect_lead_scores_high(rules):
    # The formula weighs each of the three free axes at its raw config
    # weight (0.20 each — see test_zone_points_follow_the_validated_geography
    # below, which pins the same per-axis weight) and never renormalises for
    # the missing fourth axis ("signaux", 0.40, unavailable before a paid
    # lookup runs). A lead perfect on all three free axes therefore caps at
    # 100*0.20*3 = 60, not 100 — the ceiling this test checks against.
    assert compute_prescore(_lead(), rules) >= 55


def test_a_missing_field_costs_its_axis_but_never_disqualifies(rules):
    """Décision 3: the prescore only sorts. A lead Apollo described poorly
    loses its place in the queue, never its existence."""
    score = compute_prescore(_lead(employee_count=None), rules)
    assert 0 < score < compute_prescore(_lead(), rules)


def test_every_field_missing_scores_zero_and_still_returns_a_lead(rules):
    lead = _lead(location=None, employee_count=None, apollo_industry=None)
    assert compute_prescore(lead, rules) == 0


def test_an_excluded_sector_scores_low_but_is_not_removed(rules):
    """The sourced pass may still rehabilitate it: Apollo's industry label is
    not evidence, and a verdict we cannot substantiate is not a verdict."""
    lead = _lead(apollo_industry="industrie lourde")
    score = compute_prescore(lead, rules)
    # Sector axis alone drops to 0; taille (100) and localisation (100) are
    # unaffected, so the exact total pins the "scored low, not zeroed out"
    # claim instead of a >= 0 check that no implementation could ever fail.
    assert score == round(100 * rules.weights["taille"] + 100 * rules.weights["localisation"])
    assert "disqualified" not in str(lead.get("icp_tier", ""))


def test_a_huge_company_scores_low_but_is_not_removed(rules):
    score = compute_prescore(_lead(employee_count=50000), rules)
    # Taille axis alone drops to 0 (50000 is outside every size band); secteur
    # (100) and localisation (100) are unaffected.
    assert score == round(100 * rules.weights["secteur"] + 100 * rules.weights["localisation"])


def test_the_prescore_never_writes_icp_fields(rules):
    """Contamination guard: the sourced score is the only verdict, and an
    unsourced prescore leaking into icp_tier would restore exactly the
    "score inversely correlated with knowledge" problem the 2026-08 rework
    removed."""
    lead = _lead()
    apply_prescores([lead], rules)
    assert lead["prescore"] > 0
    assert "icp_score" not in lead
    assert "icp_tier" not in lead
    assert "disqualification_reason" not in lead


# ── Géographie (décision 2) ───────────────────────────────────────────────────

@pytest.mark.parametrize("location,expected_zone_points", [
    ("Casablanca, Maroc", 100), ("Dakar, Sénégal", 90),
    ("Lagos, Nigeria", 70), ("Paris, France", 20),
    ("Bruxelles, Belgique", 10), ("Montréal, Canada", 10),
])
def test_zone_points_follow_the_validated_geography(rules, location, expected_zone_points):
    lead = _lead(location=location, employee_count=None, apollo_industry=None)
    # Localisation weighs 20% and is the only axis scoring here.
    assert compute_prescore(lead, rules) == round(expected_zone_points * 0.20)


def test_an_unrecognized_country_scores_zero_on_its_axis(rules):
    lead = _lead(location="Zzz", employee_count=None, apollo_industry=None)
    assert compute_prescore(lead, rules) == 0


# ── Tri ───────────────────────────────────────────────────────────────────────

def test_ranking_is_descending_and_stable(rules):
    leads = [
        _lead(company="Faible", location="Paris, France", employee_count=None,
              apollo_industry=None),
        _lead(company="Fort", location="Casablanca, Maroc"),
        _lead(company="Moyen", location="Dakar, Sénégal", employee_count=None),
    ]
    ranked = rank_for_spending(leads, rules)
    assert [l["company"] for l in ranked] == ["Fort", "Moyen", "Faible"]


def test_apollo_interface_labels_flatten_the_whole_ranking(rules):
    """The 2026-09-25 demo, reproduced: `location` held "Fair" / "Not a fit"
    on all 20 rows, every prescore came out 0 and the spending queue ranked a
    column of zeros — is_priority = position < budget then selected leads in
    scrape order. Sanitising the cell (scrapers/apollo_scraper) is what gives
    the ranking something to rank.
    """
    from scrapers.apollo_scraper import plausible_location

    raw = [
        _lead(company="Maroc", location="Fair", employee_count=None,
              apollo_industry=None),
        _lead(company="France", location="Not a fit", employee_count=None,
              apollo_industry=None),
    ]
    assert [compute_prescore(l, rules) for l in raw] == [0, 0]

    sane = [
        _lead(company="Maroc", location=plausible_location("Casablanca, Maroc"),
              employee_count=None, apollo_industry=None),
        _lead(company="France", location=plausible_location("Paris, France"),
              employee_count=None, apollo_industry=None),
    ]
    ranked = rank_for_spending(sane, rules)
    assert [l["company"] for l in ranked] == ["Maroc", "France"]
    assert ranked[0]["prescore"] > ranked[1]["prescore"] > 0


def test_ranking_does_not_mutate_the_input_order(rules):
    leads = [_lead(company="A", location="Paris, France"),
             _lead(company="B", location="Casablanca, Maroc")]
    rank_for_spending(leads, rules)
    assert [l["company"] for l in leads] == ["A", "B"]
