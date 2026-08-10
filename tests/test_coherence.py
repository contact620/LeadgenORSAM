import pytest

from processors.coherence import (
    CoherenceResult,
    check_site_coherence,
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


def test_check_site_coherence_accepts_matching_title():
    result = check_site_coherence(
        company="Acme Solutions",
        page_title="Acme Solutions — Agence immobilière",
        page_text="Acme Solutions accompagne les investisseurs au Maroc.",
    )
    assert result.coherent is True
    assert result.verified is True


def test_check_site_coherence_accepts_company_named_in_body_only():
    result = check_site_coherence(
        company="Houzing",
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
        page_title="Rentkasa — Location de vacances",
        page_text="Rentkasa propose des locations saisonnières en Espagne.",
    )
    assert result.coherent is False
    assert result.verified is True
    assert "Rentkasa" in (result.reason or "")


def test_cross_border_homonym_is_now_accepted():
    """Assumed trade-off, not a regression: country-mismatch checking was

    removed on 2026-08-10 because it produced false rejects on the client's
    core Franco-Maghrebi market (see check_site_coherence's docstring). This
    exact case — "Atlas Technologies" in Paris vs. an unrelated company of
    the same name in Dakar — used to be caught by the country check and is
    now accepted, since the site does name the prospect's company. If this
    test starts failing because someone reintroduced a country check, that
    is an intentional product decision to revisit, not a bug to silently fix.
    """
    result = check_site_coherence(
        company="Atlas Technologies",
        page_title="Atlas Technologies",
        page_text="Atlas Technologies, transformation de mangues à Dakar, Sénégal.",
    )
    assert result.coherent is True
    assert result.verified is True


def test_check_site_coherence_accepts_paris_firm_mentioning_casablanca():
    """Non-regression: a Paris firm discussing Moroccan investment opportunities

    must not be rejected for "incohérence France/Maroc" — this was the exact
    false-reject motivating the removal of the country check.
    """
    result = check_site_coherence(
        company="Cabinet Lefevre",
        page_title="Cabinet Lefevre — Conseil en investissement",
        page_text=(
            "Cabinet Lefevre, basé à Paris, accompagne ses clients souhaitant "
            "investir à Casablanca et développer leur patrimoine au Maroc."
        ),
    )
    assert result.coherent is True
    assert result.verified is True


def test_check_site_coherence_accepts_tunisian_company_mentioning_lausanne():
    """Non-regression: a Tunisian company naming a Lausanne partner must not

    be misclassified as Swiss and rejected — the other false-reject that
    motivated removing the country check.
    """
    result = check_site_coherence(
        company="Société Amiri",
        page_title="Société Amiri — Tunis",
        page_text=(
            "Société Amiri, implantée à Tunis, travaille avec un partenaire "
            "basé à Lausanne pour ses clients européens."
        ),
    )
    assert result.coherent is True
    assert result.verified is True


def test_check_site_coherence_is_inconclusive_on_empty_page():
    result = check_site_coherence(
        company="Acme",
        page_title="",
        page_text="",
    )
    assert result.coherent is True
    assert result.verified is False


def test_check_site_coherence_does_not_reject_on_a_generic_homepage_title():
    """A title naming no company is not evidence of a different company.

    Real case: "Groupe Zenith Immobilier" against a homepage titled
    "Accueil" came back coherent=False / verified=True — a rejection asserted
    from silence, costing the lead its site, 10 hit points and any chance of
    evidence_level = "sufficient".
    """
    result = check_site_coherence(
        company="Groupe Zenith Immobilier",
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
        page_title="Rentkasa — Location de vacances",
        page_text="Rentkasa propose des locations saisonnières en Espagne depuis 2015.",
    )
    assert result.coherent is True
    assert result.verified is False
    assert "générique" in (result.reason or "")
