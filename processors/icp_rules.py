"""
Typed loader for config/icp_rules.json.

Scoring tables live in a versioned data file rather than inside a prompt:
the score must be reproducible and reviewable without an API call.
"""
import json
import os
import unicodedata
from dataclasses import dataclass

RULES_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "config", "icp_rules.json",
)

_REQUIRED_AXES = ("secteur", "taille", "localisation", "signaux")


def normalize_label(value: str) -> str:
    """Lowercase, strip accents and trim whitespace for label comparisons.

    Duplicated from processors/coherence.py's private ``_deaccent`` rather
    than imported: this module is read as plain data by the scorer and must
    not depend on coherence.py.
    """
    if not value:
        return ""
    decomposed = unicodedata.normalize("NFKD", str(value))
    deaccented = "".join(c for c in decomposed if not unicodedata.combining(c))
    return deaccented.strip().lower()


@dataclass(frozen=True)
class IcpRules:
    weights: dict[str, float]
    high_value_sectors: list[str]
    excluded_sectors: list[str]
    sector_points: dict[str, int]
    zone_countries: dict[str, list[str]]
    zone_points: dict[str, int]
    size_bands: list[dict]
    size_disqualify_below: int
    size_disqualify_above: int
    signal_points: dict[str, int]
    signal_recency_months: int
    maturity_low_max: int
    maturity_bonus: int
    tier_hot_min: int
    tier_warm_min: int
    unverified_score_cap: int
    competitor_keywords: list[str]

    def country_zone(self, country: str) -> str | None:
        """Return the zone a country belongs to, or None if outside all zones.

        Comparison is accent/case/whitespace-insensitive: a sourced fact like
        "maroc" or " Maroc " must match the "Maroc" label in zone_countries
        just as reliably as an exact match would.
        """
        if not country:
            return None
        normalized = normalize_label(country)
        for zone, countries in self.zone_countries.items():
            if normalized in {normalize_label(c) for c in countries}:
                return zone
        return None


def load_rules(path: str | None = None) -> IcpRules:
    """Load and validate the ICP rule table."""
    target = path or RULES_PATH
    with open(target, "r", encoding="utf-8") as f:
        raw = json.load(f)

    weights = raw.get("weights", {})
    missing = [a for a in _REQUIRED_AXES if a not in weights]
    if missing:
        raise ValueError(f"icp_rules: missing weights for {', '.join(missing)}")
    if round(sum(weights.values()), 6) != 1.0:
        raise ValueError(f"icp_rules: weights must sum to 1.0, got {sum(weights.values())}")

    return IcpRules(
        weights=weights,
        high_value_sectors=raw.get("high_value_sectors", []),
        excluded_sectors=raw.get("excluded_sectors", []),
        sector_points=raw.get("sector_points", {"high_value": 100, "other": 50, "unknown": 0}),
        zone_countries=raw.get("zone_countries", {}),
        zone_points=raw.get("zone_points", {}),
        size_bands=raw.get("size_bands", []),
        size_disqualify_below=raw.get("size_disqualify_below", 5),
        size_disqualify_above=raw.get("size_disqualify_above", 1000),
        signal_points=raw.get("signal_points", {}),
        signal_recency_months=raw.get("signal_recency_months", 6),
        maturity_low_max=raw.get("maturity_low_max", 4),
        maturity_bonus=raw.get("maturity_bonus", 20),
        tier_hot_min=raw.get("tier_hot_min", 70),
        tier_warm_min=raw.get("tier_warm_min", 40),
        unverified_score_cap=raw.get("unverified_score_cap", 39),
        competitor_keywords=raw.get("competitor_keywords", []),
    )
