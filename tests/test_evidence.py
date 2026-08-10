from processors.evidence import (
    Evidence,
    compute_evidence_level,
    expected_sources,
    usable_sources,
)

LONG = "a" * 300


def _ev(**kw):
    base = dict(
        website_text="",
        website_coherent=False,
        perplexity_fields={},
        enabled_providers=frozenset({"website", "perplexity"}),
    )
    base.update(kw)
    return Evidence(**base)


def test_no_source_gives_none():
    assert compute_evidence_level(_ev(), identity_confirmed=True) == "none"


def test_identity_not_confirmed_forces_none():
    ev = _ev(website_text=LONG, website_coherent=True,
             perplexity_fields={"digital_maturity": "Score: 4/10 — site vieillissant"})
    assert compute_evidence_level(ev, identity_confirmed=False) == "none"


def test_one_of_two_expected_sources_gives_weak():
    ev = _ev(website_text=LONG, website_coherent=True)
    assert compute_evidence_level(ev, identity_confirmed=True) == "weak"


def test_all_expected_sources_give_sufficient():
    ev = _ev(website_text=LONG, website_coherent=True,
             perplexity_fields={"business_signals": "- levée de fonds mars 2026"})
    assert compute_evidence_level(ev, identity_confirmed=True) == "sufficient"


def test_perplexity_disabled_makes_website_alone_sufficient():
    ev = _ev(website_text=LONG, website_coherent=True,
             enabled_providers=frozenset({"website"}))
    assert compute_evidence_level(ev, identity_confirmed=True) == "sufficient"


def test_incoherent_website_is_not_a_usable_source():
    ev = _ev(website_text=LONG, website_coherent=False)
    assert "website" not in usable_sources(ev)


def test_short_website_text_is_not_a_usable_source():
    ev = _ev(website_text="trop court", website_coherent=True)
    assert "website" not in usable_sources(ev)


def test_placeholder_perplexity_answer_is_not_a_usable_source():
    ev = _ev(perplexity_fields={"business_signals": "Aucun signal récent identifié"})
    assert "perplexity" not in usable_sources(ev)


def test_expected_sources_follow_enabled_providers():
    assert expected_sources(_ev(enabled_providers=frozenset({"website"}))) == {"website"}
    assert expected_sources(_ev()) == {"website", "perplexity"}
