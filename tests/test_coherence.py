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


def test_detect_country_prefers_the_most_specific_match_over_dict_order():
    """Regression: a Senegalese company mentioning a Paris office was rejected.

    detect_country returned the first hit in dictionary order — France, listed
    before Sénégal — and the site was dropped for "pays incohérent".
    """
    text = ("Groupe Teranga, basé à Dakar, Sénégal. "
            "Bureau de représentation à Paris pour l'Europe.")
    assert detect_country(text) == "Sénégal"


def test_detect_country_prefers_the_longest_alias():
    # "cote d ivoire" (13) must win over any shorter alias also present.
    assert detect_country("Abidjan, Côte d'Ivoire") == "Côte d'Ivoire"


def test_check_site_coherence_does_not_reject_on_a_generic_homepage_title():
    """A title naming no company is not evidence of a different company.

    Real case: "Groupe Zenith Immobilier" against a homepage titled
    "Accueil" came back coherent=False / verified=True — a rejection asserted
    from silence, costing the lead its site, 10 hit points and any chance of
    evidence_level = "sufficient".
    """
    result = check_site_coherence(
        company="Groupe Zenith Immobilier",
        location="Casablanca, Maroc",
        page_title="Accueil",
        page_text=(
            "Bienvenue sur notre site. Nous accompagnons les investisseurs "
            "dans leurs projets d'acquisition et de gestion de patrimoine "
            "depuis plus de quinze ans."
        ),
    )
    assert result.coherent is True
    assert result.verified is False


def test_check_site_coherence_finds_the_name_beyond_the_first_1500_chars():
    """The legal name usually sits in the footer, past the old truncation."""
    filler = "Nous accompagnons les investisseurs dans leurs projets. " * 60
    result = check_site_coherence(
        company="Groupe Zenith Immobilier",
        location="Casablanca, Maroc",
        page_title="Accueil",
        page_text=filler + " Mentions légales — Groupe Zenith Immobilier SARL, Casablanca.",
    )
    assert result.coherent is True
    assert result.verified is True


def test_check_site_coherence_accepts_a_fully_generic_company_name_in_the_title():
    """Regression: the rejection reason was factually false.

    significant_tokens("Digital Solutions") is empty, so names_match fell back
    to requiring identical token sets and reported that a title spelling the
    name out word for word "ne mentionne pas « Digital Solutions »".
    """
    result = check_site_coherence(
        company="Digital Solutions",
        location="Casablanca, Maroc",
        page_title="Accueil - Digital Solutions Maroc",
        page_text=(
            "Nous concevons des plateformes sur mesure pour les entreprises "
            "marocaines, de la conception au déploiement et à la maintenance."
        ),
    )
    assert result.coherent is True
    assert result.reason is None or "ne mentionne pas" not in result.reason


def test_generic_company_name_absent_from_the_page_is_inconclusive_not_rejected():
    result = check_site_coherence(
        company="Groupe Conseil",
        location="Paris, France",
        page_title="Rentkasa — Location de vacances",
        page_text="Rentkasa propose des locations saisonnières en Espagne depuis 2015.",
    )
    assert result.coherent is True
    assert result.verified is False
    assert "générique" in (result.reason or "")


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
