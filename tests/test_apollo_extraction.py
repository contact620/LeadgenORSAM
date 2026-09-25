import pytest

from scrapers.apollo_scraper import parse_employee_count


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
