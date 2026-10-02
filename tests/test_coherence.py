import pytest

from processors.coherence import (
    CoherenceResult,
    check_site_coherence,
    domain_echoes_company,
    name_looks_like_a_company,
    names_match,
    primary_domain_label,
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


# ── A "person" that is in fact a company ─────────────────────────────────────

@pytest.mark.parametrize("full_name,company", [
    ("Delta Btp", "CONSTRUCTION BATIMENT TRAVAUX PUBLICS ET DIVERS SARL"),
    ("Stpv Voire", "STPV"),
    ("Les Marrakech", "LES SENS DE MARRAKECH"),
])
def test_the_three_companies_of_the_demo_are_flagged(full_name, company):
    """The exact rows of the 2026-09-25 export. Each one produced a generated
    address (delta.btp@, les.marrakech@) and a finder query for a person who
    does not exist."""
    assert name_looks_like_a_company(full_name, company) is True


@pytest.mark.parametrize("full_name,company", [
    ("Salma Hili", "POWER FLEET"),
    ("Rachid Attabi", "SkyCrew Recruitment, Training & Employment"),
    ("Abdelmounaim Badri", "Ecole Hôtelière Privée de Marrakech -EHPM"),
    ("Mohamed Morkane", "Maison D'Hote"),
    ("Bilal Mohamed", "INEV"),
])
def test_the_real_people_of_the_demo_are_not_flagged(full_name, company):
    assert name_looks_like_a_company(full_name, company) is False


def test_an_eponymous_founder_is_not_flagged():
    """A surname shared with the company is the normal case for an SME, not a
    signal: containment runs name-into-company, never the reverse."""
    assert name_looks_like_a_company("Jean Dupont", "Dupont") is False
    assert name_looks_like_a_company("Pierre Lefevre", "Lefevre & Fils SARL") is False


def test_an_empty_name_is_not_flagged():
    assert name_looks_like_a_company("", "Acme") is False
    assert name_looks_like_a_company("Salma Hili", "") is False


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


# ── The candidate domain as evidence (2026-10-02) ─────────────────────────────
# The four cases below are the four websites the 2026-09-25 export rejected.
# Exactly one of them was in fact the right domain.

_SKYCREW_PAGE = (
    "SkyCrew forme et place des equipages. Nos programmes couvrent la "
    "formation initiale, la qualification de type et le placement en "
    "compagnie, au Maroc et a l'international depuis 2016."
)


def test_the_right_domain_is_no_longer_lost_to_a_marketing_headline():
    """The one true rejection of the demo. "SkyCrew &#8211; Fly with us" shares
    one token out of four with the company name — below the overlap threshold —
    so website became None and the whole email cascade never started for a lead
    whose domain was already in hand."""
    result = check_site_coherence(
        company="SkyCrew Recruitment, Training & Employment",
        page_title="SkyCrew – Fly with us",
        page_text=_SKYCREW_PAGE,
        url="https://skycrewinfo.com/",
    )
    assert result.coherent is True


def test_a_wrong_domain_born_of_a_junk_location_is_still_rejected():
    """notfit.io came from the query "MTCom Not a fit site officiel"."""
    result = check_site_coherence(
        company="MTCom",
        page_title="NotFit - The Anti-Fitness App",
        page_text=(
            "NotFit is the anti-fitness app for people who hate the gym. "
            "Track nothing, celebrate everything, and keep your streak alive."
        ),
        url="https://notfit.io/",
    )
    assert result.coherent is False


def test_a_wrong_domain_from_the_other_junk_location_is_still_rejected():
    """northfloridafair.com came from the query "INEV Fair site officiel"."""
    result = check_site_coherence(
        company="INEV",
        page_title="North Florida Fair",
        page_text=(
            "The North Florida Fair returns to Tallahassee this November with "
            "rides, livestock shows, concerts and the midway."
        ),
        url="https://www.northfloridafair.com/",
    )
    assert result.coherent is False


def test_a_plausible_but_different_school_is_still_rejected():
    """upm.ac.ma is a real Marrakech university — and not the prospect's
    school. The hardest of the four: same city, same sector, and a short domain
    label that must not be allowed to echo anything."""
    result = check_site_coherence(
        company="Ecole Hôtelière Privée de Marrakech -EHPM",
        page_title="UPM – Université Privée de Marrakech",
        page_text=(
            "L'Université Privée de Marrakech propose des formations en "
            "ingénierie, management, santé et architecture sur son campus de "
            "l'avenue Mohammed VI."
        ),
        url="https://upm.ac.ma/",
    )
    assert result.coherent is False


def test_the_domain_path_only_ever_accepts():
    """Called with no url at all, the verdict is exactly what it was before."""
    without = check_site_coherence(
        company="SkyCrew Recruitment, Training & Employment",
        page_title="SkyCrew – Fly with us",
        page_text=_SKYCREW_PAGE,
    )
    assert without.coherent is False


@pytest.mark.parametrize("raw,expected", [
    ("https://www.skycrewinfo.com/", "skycrewinfo"),
    ("https://upm.ac.ma/", "upm"),
    ("skycrewinfo.com", "skycrewinfo"),
    ("https://acme-maroc.ma:8443/contact", "acmemaroc"),
    ("", ""),
])
def test_primary_domain_label(raw, expected):
    assert primary_domain_label(raw) == expected


def test_a_short_domain_label_echoes_nothing():
    """Three letters match too much of the web to count as evidence."""
    assert domain_echoes_company("UPM Marrakech", "https://upm.ac.ma/") is False


def test_a_generic_company_token_never_echoes():
    """"Groupe" in groupe-immobilier.ma is not an identification."""
    assert domain_echoes_company("Groupe Conseil", "https://groupe-conseil2.fr") is False


@pytest.mark.parametrize("company,url,expected", [
    # The four rejections of the 2026-09-25 export, judged on the one piece of
    # evidence the rule adds. Only the first domain was the right one.
    ("SkyCrew Recruitment, Training & Employment", "https://skycrewinfo.com/", True),
    ("MTCom", "https://notfit.io/", False),
    ("INEV", "https://www.northfloridafair.com/", False),
    ("Ecole Hôtelière Privée de Marrakech -EHPM", "https://upm.ac.ma/", False),
])
def test_domain_echoes_company_on_the_four_demo_cases(company, url, expected):
    assert domain_echoes_company(company, url) is expected
