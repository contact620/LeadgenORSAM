import pytest

from scrapers.apollo_scraper import (
    APOLLO_UI_LABELS,
    _JS_EXTRACT,
    parse_employee_count,
    plausible_location,
)


@pytest.mark.parametrize("raw,expected", [
    ("45", 45), ("1,250", 1250), ("1 250", 1250),
    ("11-50", 30), ("50-200", 125), ("1001-5000", 3000),
    ("11 - 50", 30), ("10,001+", 10001), ("5000+", 5000),
])
def test_headcount_formats_are_parsed(raw, expected):
    assert parse_employee_count(raw) == expected


@pytest.mark.parametrize("raw", ["", None, "—", "N/A", "unknown", "Access", "abc"])
def test_unreadable_headcount_is_none_not_zero(raw):
    """Zero would read as a micro-company and skew the prescore downward;
    None correctly means "Apollo did not show this column"."""
    assert parse_employee_count(raw) is None


def test_a_range_is_folded_to_its_rounded_midpoint():
    """Same convention as enrichers/fact_extractor.py, so a lead scored from
    Apollo and the same lead scored from sourced facts land on one scale."""
    assert parse_employee_count("11-50") == 30


# ── Location cells: interface chrome must never pass for a place ──────────────

@pytest.mark.parametrize("raw", ["Fair", "Not a fit", "Good", "Save contact"])
def test_apollo_fit_column_is_not_a_location(raw):
    """The four values the 2026-09-25 demo exported as `location` on 20 rows
    out of 20. Each one reached the website query, the prescore zone and the
    dialling code as if it named a place."""
    assert plausible_location(raw) is None


@pytest.mark.parametrize("raw", [
    "Casablanca, Morocco", "Marrakech", "Paris, France", "Maroc",
    "Dakar", "Abidjan, Côte d'Ivoire", "Lyon",
])
def test_a_real_location_is_kept_verbatim(raw):
    assert plausible_location(raw) == raw


def test_an_unrecognised_word_without_a_comma_is_dropped():
    """None is the safe answer: every consumer treats an absent location as
    unknown, none of them survives a wrong one."""
    assert plausible_location("Excellent") is None


def test_a_city_is_not_matched_inside_a_longer_word():
    """"Fes" is a Moroccan city and a substring of "Professional Services" —
    word-boundary matching is what keeps the second from passing as the first."""
    assert plausible_location("Professional Services") is None


def test_an_interface_label_with_a_comma_is_still_dropped():
    assert plausible_location("Fair, Good") is None


@pytest.mark.parametrize("raw", [None, "", "   ", "x" * 200])
def test_empty_or_oversized_cells_are_dropped(raw):
    assert plausible_location(raw) is None


def test_the_browser_side_extractor_shares_the_same_label_list():
    """plausible_location is the net; the extractor itself must already refuse
    these labels, otherwise a "fit" verdict still wins the positional race for
    the job_title and company columns."""
    for label in ("not a fit", "save contact", "fair"):
        assert label in APOLLO_UI_LABELS
        assert f'"{label}"' in _JS_EXTRACT
    assert "__APOLLO_UI_LABELS__" not in _JS_EXTRACT
