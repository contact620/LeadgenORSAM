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


def test_no_declared_provider_but_real_content_gives_sufficient():
    # enabled_providers empty means the caller declared nothing — unreachable
    # today, since collect_evidence always includes "website". Pinned here so
    # the behaviour is a decision, not an accident of set arithmetic.
    ev = _ev(website_text=LONG, website_coherent=True,
             enabled_providers=frozenset())
    assert compute_evidence_level(ev, identity_confirmed=True) == "sufficient"


# ── Unreachable website (Astrak case, 2026-08-11 pilot run) ─────────────────
# A site that failed to respond (network/DNS/timeout/error status) is a
# provider outage for this lead, not a source that spoke and had nothing to
# say — it must drop out of `expected_sources`, unlike a site that answered
# with a thin or empty page.

def test_unreachable_website_is_dropped_from_expected_sources():
    ev = _ev(website_unreachable=True)
    assert expected_sources(ev) == {"perplexity"}


def test_reachable_website_stays_expected_even_when_empty():
    ev = _ev(website_unreachable=False)
    assert expected_sources(ev) == {"website", "perplexity"}


def test_unreachable_website_and_silent_perplexity_stays_none():
    """Invariant 1: no usable source anywhere must never reach 'sufficient'."""
    ev = _ev(website_text="", website_coherent=False, website_unreachable=True,
              perplexity_fields={})
    assert compute_evidence_level(ev, identity_confirmed=True) == "none"


def test_unreachable_website_with_substantive_perplexity_is_sufficient():
    """Invariant 2 — the Astrak case: site down, but Perplexity delivered."""
    ev = _ev(website_text="", website_coherent=False, website_unreachable=True,
              perplexity_fields={"estimated_budget": "Effectif estimé: 35 employés"})
    assert compute_evidence_level(ev, identity_confirmed=True) == "sufficient"


def test_reachable_but_empty_website_with_substantive_perplexity_stays_weak():
    """Invariant 3: joignable-mais-vide must not be confused with injoignable.

    Same evidence as the unreachable case above except website_unreachable is
    False (site answered, just had nothing usable) — this must stay "weak",
    pinning the distinction the Astrak fix depends on.
    """
    ev = _ev(website_text="", website_coherent=False, website_unreachable=False,
              perplexity_fields={"estimated_budget": "Effectif estimé: 35 employés"})
    assert compute_evidence_level(ev, identity_confirmed=True) == "weak"


def test_unreachable_website_does_not_override_unconfirmed_identity():
    """Invariant 4: identite_confirmee=False still forces 'none' unconditionally."""
    ev = _ev(website_text="", website_coherent=False, website_unreachable=True,
              perplexity_fields={"estimated_budget": "Effectif estimé: 35 employés"})
    assert compute_evidence_level(ev, identity_confirmed=False) == "none"
