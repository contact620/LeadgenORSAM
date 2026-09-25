import pytest

from enrichers.phone_extractor import (
    best_phone, country_hint, extract_phones,
)


def _kinds(html, location):
    return {(p.e164, p.kind) for p in extract_phones(html, location)}


# ── Maroc ─────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("raw", [
    "+212 6 61 23 45 67", "0661234567", "06 61 23 45 67", "+212661234567",
])
def test_moroccan_mobile_is_normalized_and_typed(raw):
    assert ("+212661234567", "mobile") in _kinds(f"<p>{raw}</p>", "Casablanca, Maroc")


def test_moroccan_07_prefix_is_also_mobile():
    """Morocco opened the 07 range for mobiles in 2015; a hand-rolled regex
    keyed on 06 alone would type half the country's mobiles as landlines."""
    assert ("+212701234567", "mobile") in _kinds("<p>07 01 23 45 67</p>", "Rabat, Maroc")


def test_moroccan_landline_is_typed_fixe():
    assert ("+212522123456", "fixe") in _kinds("<p>05 22 12 34 56</p>", "Casablanca, Maroc")


# ── Autres pays africains ─────────────────────────────────────────────────────

@pytest.mark.parametrize("raw,location,expected", [
    ("+225 07 12 34 56 78", "Abidjan, Côte d'Ivoire", "+2250712345678"),
    ("+221 77 123 45 67", "Dakar, Sénégal", "+221771234567"),
    ("+237 6 71 23 45 67", "Douala, Cameroun", "+237671234567"),
    ("+216 20 123 456", "Tunis, Tunisie", "+21620123456"),
    ("+213 5 51 23 45 67", "Alger, Algérie", "+213551234567"),
])
def test_african_mobiles_are_recognized(raw, location, expected):
    assert ("mobile") in {k for _, k in _kinds(f"<p>{raw}</p>", location)}
    assert expected in {e for e, _ in _kinds(f"<p>{raw}</p>", location)}


def test_international_format_works_without_a_location():
    """A +212 number carries its own country: no hint needed."""
    assert ("+212661234567", "mobile") in _kinds("<p>+212661234567</p>", "")


def test_a_national_number_without_a_location_hint_is_dropped():
    """0661234567 is Moroccan, French or Ivorian depending on where you are.
    Guessing would mint a plausible but wrong E.164."""
    assert _kinds("<p>0661234567</p>", "") == set()


# ── Faux positifs ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("noise", [
    "<p>SIRET 12345678901234</p>",
    "<p>RC 123456</p>",
    "<p>2024 2025 2026</p>",
    '<img src="banner-1200x628.png">',
])
def test_identifiers_are_not_phone_numbers(noise):
    assert _kinds(noise, "Casablanca, Maroc") == set()


def test_duplicates_across_formats_collapse():
    html = "<p>+212 661 23 45 67</p><p>0661234567</p>"
    assert len(extract_phones(html, "Casablanca, Maroc")) == 1


# ── Indices pays ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("location,code", [
    ("Casablanca, Maroc", "MA"), ("Morocco", "MA"), ("Rabat", "MA"),
    ("Abidjan, Côte d'Ivoire", "CI"), ("Dakar, Senegal", "SN"),
    ("Paris, France", "FR"), ("", None), ("Zzz", None),
])
def test_country_hint_resolves_locations(location, code):
    assert country_hint(location) == code


# ── Meilleur numéro ───────────────────────────────────────────────────────────

def test_mobile_beats_landline():
    phones = extract_phones("<p>05 22 12 34 56</p><p>06 61 23 45 67</p>", "Casablanca, Maroc")
    assert best_phone(phones).kind == "mobile"


def test_best_phone_of_nothing_is_none():
    assert best_phone([]) is None
