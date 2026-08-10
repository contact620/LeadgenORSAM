import pytest

from processors.coherence import (
    names_match,
    normalize_tokens,
    significant_tokens,
    strip_www,
)


def test_strip_www_removes_prefix_not_characters():
    assert strip_www("www.acme.com") == "acme.com"
    # Regression: lstrip("www.") ate leading characters of the domain itself
    assert strip_www("wework.com") == "wework.com"
    assert strip_www("world.example.org") == "world.example.org"


def test_normalize_tokens_lowercases_and_strips_accents_and_punctuation():
    assert normalize_tokens("Société Générale") == {"societe", "generale"}
    assert normalize_tokens("Acme, Inc.") == {"acme", "inc"}


def test_significant_tokens_drops_legal_suffixes_and_generic_words():
    assert significant_tokens("Acme Solutions SARL") == {"acme"}
    assert significant_tokens("Alp Financial") == {"alp"}
    assert significant_tokens("Financial Times") == {"times"}


def test_names_match_rejects_generic_word_only_overlap():
    # The reported bug: "Alp Financial" must not accept "Financial Times"
    assert names_match("Financial Times", "Alp Financial") is False


def test_names_match_rejects_unrelated_names():
    assert names_match("Rentkasa", "Houzing") is False


def test_names_match_accepts_same_company_with_legal_suffix():
    assert names_match("Acme Solutions SARL", "Acme Solutions") is True


def test_names_match_accepts_subset_of_tokens():
    assert names_match("Atlas Technologies", "Groupe Atlas") is True


def test_names_match_with_only_generic_tokens_falls_back_to_exact_tokens():
    # Both sides reduce to an empty significant set; only an exact token match passes
    assert names_match("Digital Services", "Digital Solutions") is False
    assert names_match("Digital Services", "Services Digital") is True


def test_names_match_handles_empty_input():
    assert names_match("", "Acme") is False
    assert names_match("Acme", "") is False
