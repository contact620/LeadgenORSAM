"""
Typed loader for config/icp_rules.json.

Scoring tables live in a versioned data file rather than inside a prompt:
the score must be reproducible and reviewable without an API call.

That includes `country_aliases`, which lets "Morocco" or "Maroc (Casablanca)"
reach the same zone as "Maroc". processors/coherence.py owns a similar table,
but it answers a different question — which country a page of free text talks
about — and the two are kept apart on purpose: importing it here would give
the scorer a dependency on the coherence module (see normalize_label below),
and would couple a scoring input the operator may need to edit to a table
tuned for text detection.
"""
import json
import os
import re
import unicodedata
from dataclasses import dataclass

RULES_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "config", "icp_rules.json",
)

_REQUIRED_AXES = ("secteur", "taille", "localisation", "signaux")

# Typographic apostrophes/quotes an LLM extraction commonly produces
# ("Côte d'Ivoire" with a curly quote) folded to the straight apostrophe
# used in config/icp_rules.json — otherwise a cosmetic character difference
# silently disqualifies an in-zone country.
_APOSTROPHE_VARIANTS = {
    "’": "'",  # RIGHT SINGLE QUOTATION MARK
    "‘": "'",  # LEFT SINGLE QUOTATION MARK
    "ʼ": "'",  # MODIFIER LETTER APOSTROPHE
}


def normalize_label(value: str) -> str:
    """Lowercase, strip accents, fold apostrophe variants, and trim whitespace.

    Duplicated from processors/coherence.py's private ``_deaccent`` rather
    than imported: this module is read as plain data by the scorer and must
    not depend on coherence.py.
    """
    if not value:
        return ""
    text = str(value)
    for variant, straight in _APOSTROPHE_VARIANTS.items():
        text = text.replace(variant, straight)
    decomposed = unicodedata.normalize("NFKD", text)
    deaccented = "".join(c for c in decomposed if not unicodedata.combining(c))
    return deaccented.strip().lower()


_NON_WORD_RE = re.compile(r"[^a-z0-9]+")


def _padded_words(value: str) -> str:
    """Normalize to a space-padded word sequence, e.g. "  Maroc (Casablanca) " -> " maroc casablanca ".

    Padding both ends lets a plain ``in`` test act as a word-boundary match:
    " niger " is not contained in " nigeria ", while " maroc " is contained in
    " maroc casablanca ".
    """
    cleaned = _NON_WORD_RE.sub(" ", normalize_label(value)).strip()
    return f" {cleaned} " if cleaned else ""


@dataclass(frozen=True)
class IcpRules:
    weights: dict[str, float]
    high_value_sectors: list[str]
    excluded_sectors: list[str]
    sector_points: dict[str, int]
    country_aliases: dict[str, list[str]]
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

    def canonical_country(self, country: str) -> str | None:
        """Return the canonical French label for a country string, or None.

        The extraction model reads whatever the sources say: an English site
        yields "Morocco", a decorated label yields "Maroc (Casablanca)", and a
        city can stand in for its country. All three designate the same place
        and must reach the same zone.

        None means *unrecognised*, which callers must read as "unknown" —
        never as "out of zone". A verdict we cannot substantiate is not a
        verdict.
        """
        if not country:
            return None
        normalized = normalize_label(country)
        if not normalized:
            return None

        # 1. Exact match against a zone label — the authoritative spelling,
        #    and the safety net for a zone country with no alias entry.
        for countries in self.zone_countries.values():
            for label in countries:
                if normalize_label(label) == normalized:
                    return label

        # 2. Alias lookup. The longest matching alias wins so that
        #    "democratic republic of the congo" resolves to RDC rather than to
        #    Congo, independently of dictionary order.
        haystack = _padded_words(country)
        if not haystack:
            return None
        best_label: str | None = None
        best_length = 0
        for canonical, aliases in self.country_aliases.items():
            for alias in (canonical, *aliases):
                needle = _padded_words(alias)
                if needle and needle in haystack and len(needle) > best_length:
                    best_label, best_length = canonical, len(needle)
        return best_label

    def country_zone(self, country: str) -> str | None:
        """Return the zone a country belongs to, or None if outside all zones.

        Canonicalises first (see canonical_country), so "Morocco" scores
        exactly like "Maroc". Comparison is accent/case/whitespace-insensitive.
        """
        canonical = self.canonical_country(country)
        if canonical is None:
            return None
        normalized = normalize_label(canonical)
        for zone, countries in self.zone_countries.items():
            if normalized in {normalize_label(c) for c in countries}:
                return zone
        return None


def load_rules(path: str | None = None) -> IcpRules:
    """Load and validate the ICP rule table.

    Every failure is re-raised with an "icp_rules:" prefix and the path that
    was tried. The file ships with the code but is distributed as a zip (see
    README): losing it during a copy would otherwise kill step 7 of every run
    with a bare traceback naming neither the file nor what to do about it.
    """
    target = path or RULES_PATH
    try:
        with open(target, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except FileNotFoundError as exc:
        raise FileNotFoundError(
            f"icp_rules: fichier de règles introuvable à l'emplacement attendu "
            f"« {target} ». Restaurez-le depuis le dépôt (config/icp_rules.json) : "
            f"sans lui, le scoring ICP ne peut pas s'exécuter."
        ) from exc
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"icp_rules: le fichier « {target} » n'est pas un JSON valide "
            f"(ligne {exc.lineno}, colonne {exc.colno}) : {exc.msg}."
        ) from exc
    except OSError as exc:
        raise OSError(f"icp_rules: lecture impossible de « {target} » : {exc}") from exc

    if not isinstance(raw, dict):
        raise ValueError(f"icp_rules: « {target} » doit contenir un objet JSON.")

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
        country_aliases=raw.get("country_aliases", {}),
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
    )
