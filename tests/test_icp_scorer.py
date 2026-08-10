from datetime import date

import pytest

from processors.icp_rules import load_rules
from processors.icp_scorer import score_lead

RUN_DATE = date(2026, 8, 10)


@pytest.fixture
def rules():
    return load_rules()


def _facts(**kw):
    base = {
        "identite_confirmee": True,
        "pays": {"value": "Maroc", "source": "website"},
        "secteur": {"value": "immobilier", "source": "website"},
        "effectif": {"value": 45, "source": "perplexity"},
        "est_concurrent": False,
        "maturite_digitale": None,
        "signaux": [],
    }
    base.update(kw)
    return base


# ── Spec §9 fixed cases ──────────────────────────────────────────────────────

def test_large_group_is_disqualified(rules):
    facts = _facts(effectif={"value": 5000, "source": "perplexity"},
                   pays={"value": "France", "source": "website"})
    result = score_lead(facts, "sufficient", rules, RUN_DATE)
    assert result.icp_tier == "disqualified"
    assert "grand groupe" in result.disqualification_reason


def test_unverified_lead_falls_into_cold_capped(rules):
    facts = _facts(identite_confirmee=False)
    result = score_lead(facts, "none", rules, RUN_DATE)
    assert result.icp_tier == "cold"
    assert result.icp_score <= rules.unverified_score_cap
    assert result.evidence_verified is False


def test_mid_fit_lead_with_one_signal_is_warm(rules):
    # secteur "other" 50x0.20 + taille 100x0.20 + France 80x0.20 + 1 signal 40x0.40 = 62
    facts = _facts(
        secteur={"value": "logistique", "source": "website"},
        pays={"value": "France", "source": "website"},
        signaux=[{"type": "recrutement_marketing", "date": "2026-04",
                  "source": "perplexity", "citation": "..."}],
    )
    result = score_lead(facts, "sufficient", rules, RUN_DATE)
    assert result.icp_score == 62
    assert result.icp_tier == "warm"


def test_ideal_moroccan_sme_with_one_signal_is_hot(rules):
    # 100x0.20 + 100x0.20 + 100x0.20 + 40x0.40 = 76
    facts = _facts(signaux=[{"type": "recrutement_marketing", "date": "2026-04",
                             "source": "perplexity", "citation": "..."}])
    result = score_lead(facts, "sufficient", rules, RUN_DATE)
    assert result.icp_score == 76
    assert result.icp_tier == "hot"


def test_moroccan_sme_with_three_recent_signals_and_low_maturity_is_hot(rules):
    facts = _facts(
        maturite_digitale={"value": 3, "source": "perplexity"},
        signaux=[
            {"type": "levee_de_fonds", "date": "2026-06", "source": "perplexity", "citation": "a"},
            {"type": "recrutement_marketing", "date": "2026-05", "source": "perplexity", "citation": "b"},
            {"type": "lancement_produit", "date": "2026-07", "source": "website", "citation": "c"},
        ],
    )
    result = score_lead(facts, "sufficient", rules, RUN_DATE)
    assert result.icp_tier == "hot"


def test_competitor_is_disqualified(rules):
    facts = _facts(est_concurrent=True)
    result = score_lead(facts, "sufficient", rules, RUN_DATE)
    assert result.icp_tier == "disqualified"
    assert "concurrent" in result.disqualification_reason


def test_excluded_sector_is_disqualified(rules):
    facts = _facts(secteur={"value": "agriculture", "source": "website"},
                   effectif={"value": 80, "source": "perplexity"})
    result = score_lead(facts, "sufficient", rules, RUN_DATE)
    assert result.icp_tier == "disqualified"
    assert "secteur" in result.disqualification_reason


def test_out_of_zone_country_is_disqualified(rules):
    facts = _facts(pays={"value": "États-Unis", "source": "website"})
    result = score_lead(facts, "sufficient", rules, RUN_DATE)
    assert result.icp_tier == "disqualified"


# ── The reported inversion ───────────────────────────────────────────────────

def test_absence_of_signals_scores_zero_on_that_axis(rules):
    """The core fix: no sourced signal must yield 0, never an invented score."""
    facts = _facts(signaux=[])
    result = score_lead(facts, "sufficient", rules, RUN_DATE)
    detail = __import__("json").loads(result.icp_scores_detail)
    assert detail["signaux"] == 0


def test_more_evidence_never_lowers_the_score(rules):
    poor = score_lead(_facts(signaux=[]), "sufficient", rules, RUN_DATE)
    rich = score_lead(
        _facts(signaux=[{"type": "levee_de_fonds", "date": "2026-07",
                         "source": "perplexity", "citation": "x"}]),
        "sufficient", rules, RUN_DATE,
    )
    assert rich.icp_score > poor.icp_score


def test_competitor_disqualifies_even_without_evidence(rules):
    facts = _facts(est_concurrent=True, identite_confirmee=False)
    result = score_lead(facts, "none", rules, RUN_DATE)
    assert result.icp_tier == "disqualified"


def test_disqualification_requires_sufficient_evidence(rules):
    """A weak-evidence lead is never disqualified — we cannot assert the reason."""
    facts = _facts(effectif={"value": 5000, "source": "perplexity"})
    result = score_lead(facts, "weak", rules, RUN_DATE)
    assert result.icp_tier == "cold"
    assert result.disqualification_reason is None


# ── Unsourced facts ──────────────────────────────────────────────────────────

def test_unknown_sector_scores_zero_not_average(rules):
    facts = _facts(secteur=None)
    result = score_lead(facts, "sufficient", rules, RUN_DATE)
    detail = __import__("json").loads(result.icp_scores_detail)
    assert detail["secteur"] == 0


def test_unknown_size_does_not_disqualify(rules):
    facts = _facts(effectif=None)
    result = score_lead(facts, "sufficient", rules, RUN_DATE)
    assert result.icp_tier != "disqualified"


# ── Signal recency ───────────────────────────────────────────────────────────

def test_old_signals_score_lower_than_recent_ones(rules):
    old = [{"type": "x", "date": "2024-01", "source": "perplexity", "citation": "c"}
           for _ in range(3)]
    recent = [{"type": "x", "date": "2026-07", "source": "perplexity", "citation": "c"}
              for _ in range(3)]
    old_result = score_lead(_facts(signaux=old), "sufficient", rules, RUN_DATE)
    new_result = score_lead(_facts(signaux=recent), "sufficient", rules, RUN_DATE)
    assert new_result.icp_score > old_result.icp_score


def test_signal_without_date_counts_but_is_never_recent(rules):
    facts = _facts(signaux=[{"type": "x", "date": None, "source": "website", "citation": "c"}])
    result = score_lead(facts, "sufficient", rules, RUN_DATE)
    detail = __import__("json").loads(result.icp_scores_detail)
    assert detail["signaux"] == rules.signal_points["one"]


# ── Digital maturity: bonus-only, never a penalty ────────────────────────────

def test_learning_digital_maturity_never_lowers_the_score(rules):
    """Acquiring a fact must never cost points — the client's original complaint."""
    unknown = score_lead(_facts(signaux=[{"type": "x", "date": "2026-07",
                                          "source": "perplexity", "citation": "c"}]),
                         "sufficient", rules, RUN_DATE)
    mature = score_lead(_facts(maturite_digitale={"value": 9, "source": "perplexity"},
                               signaux=[{"type": "x", "date": "2026-07",
                                         "source": "perplexity", "citation": "c"}]),
                        "sufficient", rules, RUN_DATE)
    assert mature.icp_score >= unknown.icp_score


def test_low_maturity_bonus_is_reported_in_detail_and_rationale(rules):
    facts = _facts(maturite_digitale={"value": 2, "source": "perplexity"},
                   signaux=[{"type": "x", "date": "2026-07",
                             "source": "perplexity", "citation": "c"}])
    result = score_lead(facts, "sufficient", rules, RUN_DATE)
    detail = __import__("json").loads(result.icp_scores_detail)
    assert detail["maturite_ajustement"] == rules.maturity_bonus
    assert "maturité" in result.icp_rationale


# ── Label normalization (case/accent-insensitive matching) ──────────────────

def test_lowercase_country_does_not_disqualify(rules):
    # Regression: country_zone compared exact case/accents, so a sourced
    # "maroc" (lowercase) silently missed the "Maroc" entry and disqualified
    # an otherwise-ideal lead as "hors zone géographique".
    facts = _facts(pays={"value": "maroc", "source": "website"})
    result = score_lead(facts, "sufficient", rules, RUN_DATE)
    detail = __import__("json").loads(result.icp_scores_detail)
    assert result.icp_tier != "disqualified"
    assert detail["localisation"] == rules.zone_points["maroc"]


def test_accented_sector_scores_as_high_value(rules):
    # Regression: "santé" (accented, as a real extraction would return it)
    # did not match "sante" in the rule table and silently fell back to 50.
    facts = _facts(secteur={"value": "santé", "source": "website"})
    result = score_lead(facts, "sufficient", rules, RUN_DATE)
    detail = __import__("json").loads(result.icp_scores_detail)
    assert detail["secteur"] == rules.sector_points["high_value"]


# ── Evidence gates the competitor score too ──────────────────────────────────

def test_unverified_competitor_score_is_also_capped(rules):
    facts = _facts(est_concurrent=True, effectif={"value": 45, "source": "perplexity"})
    result = score_lead(facts, "weak", rules, RUN_DATE)
    assert result.icp_tier == "disqualified"
    assert result.icp_score <= rules.unverified_score_cap
