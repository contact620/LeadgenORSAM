import pytest

from processors.coherence import (
    CoherenceResult,
    check_site_coherence,
    detect_country,
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


def test_detect_country_finds_known_country():
    assert detect_country("Notre siège est à Casablanca, Maroc.") == "Maroc"
    assert detect_country("Head office in Dakar, Senegal") == "Sénégal"


def test_detect_country_returns_none_when_absent():
    assert detect_country("We build software for everyone.") is None
    assert detect_country("") is None


def test_check_site_coherence_accepts_matching_title():
    result = check_site_coherence(
        company="Acme Solutions",
        location="Casablanca, Maroc",
        page_title="Acme Solutions — Agence immobilière",
        page_text="Acme Solutions accompagne les investisseurs au Maroc.",
    )
    assert result.coherent is True
    assert result.verified is True


def test_check_site_coherence_accepts_company_named_in_body_only():
    result = check_site_coherence(
        company="Houzing",
        location="Paris, France",
        page_title="Accueil",
        page_text=(
            "Bienvenue chez Houzing, spécialiste de la gestion locative en France. "
            "Nous accompagnons les propriétaires bailleurs dans la mise en location "
            "et le suivi quotidien de leurs biens."
        ),
    )
    assert result.coherent is True
    assert result.verified is True


def test_check_site_coherence_rejects_unrelated_site():
    # The reported case: company "houzing" resolved to rentkasa.com
    result = check_site_coherence(
        company="Houzing",
        location="Paris, France",
        page_title="Rentkasa — Location de vacances",
        page_text="Rentkasa propose des locations saisonnières en Espagne.",
    )
    assert result.coherent is False
    assert result.verified is True
    assert "Rentkasa" in (result.reason or "")


def test_check_site_coherence_rejects_country_mismatch():
    result = check_site_coherence(
        company="Atlas Technologies",
        location="Paris, France",
        page_title="Atlas Technologies",
        page_text="Atlas Technologies, transformation de mangues à Dakar, Sénégal.",
    )
    assert result.coherent is False
    assert "Sénégal" in (result.reason or "")


def test_check_site_coherence_is_inconclusive_on_empty_page():
    result = check_site_coherence(
        company="Acme",
        location="Paris, France",
        page_title="",
        page_text="",
    )
    assert result.coherent is True
    assert result.verified is False


def test_check_site_coherence_ignores_corrupted_apollo_location():
    # Apollo's `location` is often garbage; it must never trigger a rejection
    result = check_site_coherence(
        company="Acme",
        location="Access Mobile",
        page_title="Acme",
        page_text=(
            "Acme est basée à Dakar, Sénégal. Nous offrons des solutions complètes "
            "pour la gestion immobilière et les services d'investissement immobilier."
        ),
    )
    assert result.coherent is True
