import json

import pytest

from processors.icp_rules import IcpRules, load_rules


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
