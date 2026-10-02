import pytest

import config
from api import quota_db
from api.provider_status import ProviderRegistry
from enrichers import email_cascade
from enrichers.contact_extractor import ExtractedEmail
from enrichers.providers.base import ACCEPT_ALL, NOT_FOUND, UNKNOWN, VALID, EmailResult
from enrichers.retry import QuotaExhausted


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(quota_db, "_DB_PATH", str(tmp_path / "q.db"))
    # Pinned rather than left on the production defaults in config.py: a
    # future change to those numbers must not silently change what these
    # tests exercise.
    for provider in ("prospeo", "getprospect", "hunter", "getprospect_verify"):
        monkeypatch.setitem(config.PROVIDER_ALLOCATIONS, provider, 100.0)
    quota_db.init_quota_tables()
    monkeypatch.setattr(email_cascade.domain_intel, "lookup_mx",
                        lambda d: email_cascade.domain_intel.MxInfo(True, "google"))
    monkeypatch.setattr(email_cascade.domain_intel, "is_catch_all", lambda d, fn: False)
    yield
    email_cascade.domain_intel.reset_caches()


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    """Default every provider entry point to an offline "nothing found".

    A developer .env holds real keys, so any entry point a test leaves alone
    is a live HTTP call from inside the cascade — billed, slow and dependent
    on a third party. Permuting FINDER_ORDER made that visible: half a dozen
    tests had simply never exercised the provider that now runs first.

    A test that cares about a provider still patches it explicitly; this only
    decides what an unpatched one answers.
    """
    for name in ("prospeo", "getprospect", "hunter"):
        module = getattr(email_cascade, name)
        for entry_point in ("find_email", "verify_email"):
            if hasattr(module, entry_point):
                monkeypatch.setattr(
                    module, entry_point,
                    lambda *a, _provider=name, **k: EmailResult(
                        status=NOT_FOUND, provider=_provider),
                )


def _lead(**over):
    base = {"first_name": "Karim", "last_name": "El Amrani",
            "company": "Acme", "website": "https://acme.ma",
            "location": "Casablanca, Maroc", "_site_contacts": {"emails": [], "phones": []}}
    base.update(over)
    return base


def _site(*emails):
    return {"emails": [ExtractedEmail(v, k, "https://acme.ma/contact") for v, k in emails],
            "phones": []}


# ── a. Email nominatif trouvé sur le site ─────────────────────────────────────

def test_a_nominative_site_email_wins_without_spending(monkeypatch):
    monkeypatch.setattr(email_cascade.getprospect, "verify_email",
                        lambda e: EmailResult(email=e, status=VALID, provider="getprospect",
                                              billed=True, cost=1.0))
    def _never(*a, **k):
        raise AssertionError("aucun finder ne doit être appelé")
    monkeypatch.setattr(email_cascade.prospeo, "find_email", _never)

    lead = _lead(_site_contacts=_site(("karim.elamrani@acme.ma", "nominatif_lead")))
    email_cascade.resolve_email(lead, is_priority=True)

    assert lead["email"] == "karim.elamrani@acme.ma"
    assert lead["email_status"] == "valid_nominatif"
    assert lead["email_source"] == "website"


def test_a_generic_site_email_is_the_last_resort_not_the_first(monkeypatch):
    """The net: the generic comes back only once everything else has failed."""
    monkeypatch.setattr(email_cascade.getprospect, "verify_email",
                        lambda e: EmailResult(email=e, status=NOT_FOUND,
                                              provider="getprospect", billed=True, cost=1.0))
    monkeypatch.setattr(email_cascade.hunter, "verify_email",
                        lambda e: EmailResult(email=e, status=NOT_FOUND,
                                              provider="hunter", billed=True, cost=0.5))
    monkeypatch.setattr(email_cascade.prospeo, "find_email",
                        lambda *a: EmailResult(status=NOT_FOUND, provider="prospeo"))
    monkeypatch.setattr(email_cascade.getprospect, "find_email",
                        lambda *a: EmailResult(status=NOT_FOUND, provider="getprospect"))
    monkeypatch.setattr(email_cascade.hunter, "find_email",
                        lambda *a: EmailResult(status=NOT_FOUND, provider="hunter"))

    lead = _lead(_site_contacts=_site(("contact@acme.ma", "generique")))
    email_cascade.resolve_email(lead, is_priority=True)
    assert lead["email"] == "contact@acme.ma"
    assert lead["email_status"] == "valid_generique"
    assert lead["email_source"] == "website"
    assert lead["email_type"] == "generique"
    assert lead["contact_source_url"] == "https://acme.ma/contact"


def test_a_generic_site_email_no_longer_stops_the_cascade(monkeypatch):
    """The 7 valid_generique rows of the 2026-09-25 demo left with a
    switchboard address and an empty domain_catch_all column — proof that the
    cascade had returned before the verification step ever ran. A generic must
    now cost nothing but a place in reserve.
    """
    monkeypatch.setattr(email_cascade.getprospect, "verify_email",
                        lambda e: EmailResult(email=e, status=VALID, provider="getprospect",
                                              billed=True, cost=1.0))
    def _never(*a, **k):
        raise AssertionError("un nominatif vérifié rend le finder inutile")
    monkeypatch.setattr(email_cascade.prospeo, "find_email", _never)
    monkeypatch.setattr(email_cascade.getprospect, "find_email", _never)

    lead = _lead(_site_contacts=_site(("contact@acme.ma", "generique")))
    email_cascade.resolve_email(lead, is_priority=True)

    assert lead["email"] == "karim.elamrani@acme.ma"
    assert lead["email_status"] == "valid_nominatif"
    assert lead["email_source"] == "pattern_verified"
    assert lead["domain_catch_all"] is False, "l'étape (c) doit avoir été atteinte"


def test_a_finder_hit_beats_the_generic_held_in_reserve(monkeypatch):
    monkeypatch.setattr(email_cascade.getprospect, "verify_email",
                        lambda e: EmailResult(email=e, status=NOT_FOUND,
                                              provider="getprospect", billed=True, cost=1.0))
    monkeypatch.setattr(email_cascade.hunter, "verify_email",
                        lambda e: EmailResult(email=e, status=NOT_FOUND,
                                              provider="hunter", billed=True, cost=0.5))
    monkeypatch.setattr(email_cascade.prospeo, "find_email",
                        lambda *a: EmailResult(status=NOT_FOUND, provider="prospeo"))
    monkeypatch.setattr(email_cascade.getprospect, "find_email",
                        lambda f, l, d: EmailResult(email="k.elamrani@acme.ma", status=VALID,
                                                    provider="getprospect",
                                                    billed=True, cost=1.0))

    lead = _lead(_site_contacts=_site(("contact@acme.ma", "generique")))
    email_cascade.resolve_email(lead, is_priority=True)
    assert lead["email"] == "k.elamrani@acme.ma"
    assert lead["email_source"] == "getprospect"
    assert lead["email_type"] == "nominatif_lead"


def test_a_non_priority_lead_falls_back_to_the_generic(monkeypatch):
    """A withheld finder credit is not a reason to export an empty cell when
    the company published a reachable address."""
    monkeypatch.setattr(email_cascade.getprospect, "verify_email",
                        lambda e: EmailResult(email=e, status=NOT_FOUND,
                                              provider="getprospect", billed=True, cost=1.0))
    monkeypatch.setattr(email_cascade.hunter, "verify_email",
                        lambda e: EmailResult(email=e, status=NOT_FOUND,
                                              provider="hunter", billed=True, cost=0.5))

    lead = _lead(_site_contacts=_site(("contact@acme.ma", "generique")))
    email_cascade.resolve_email(lead, is_priority=False)
    assert lead["email"] == "contact@acme.ma"
    assert lead["email_status"] == "valid_generique"


def test_a_published_generic_is_never_overwritten_by_a_catch_all_guess(monkeypatch):
    """Arbitration: candidates[0] on a catch-all domain is a guess nobody can
    confirm — the domain says yes to every address. The real address the
    company published must survive it, with its own status, not be replaced by
    a fiction labelled nominatif_lead."""
    monkeypatch.setattr(email_cascade.domain_intel, "is_catch_all", lambda d, fn: True)
    def _never(*a, **k):
        raise AssertionError("un domaine catch-all ne se vérifie pas")
    monkeypatch.setattr(email_cascade.getprospect, "verify_email", _never)
    monkeypatch.setattr(email_cascade.hunter, "verify_email", _never)
    monkeypatch.setattr(email_cascade.prospeo, "find_email", _never)
    monkeypatch.setattr(email_cascade.getprospect, "find_email", _never)

    lead = _lead(_site_contacts=_site(("contact@acme.ma", "generique")))
    email_cascade.resolve_email(lead, is_priority=True)

    assert lead["email"] == "contact@acme.ma"
    assert lead["email_status"] == "valid_generique"
    assert lead["email_type"] == "generique"
    assert lead["domain_catch_all"] is True, "le fait reste exporté"


def test_a_webmail_on_the_site_is_never_used_as_the_company_address(monkeypatch):
    monkeypatch.setattr(email_cascade.prospeo, "find_email",
                        lambda *a: EmailResult(status=NOT_FOUND, provider="prospeo"))
    monkeypatch.setattr(email_cascade.getprospect, "find_email",
                        lambda *a: EmailResult(status=NOT_FOUND, provider="getprospect"))
    monkeypatch.setattr(email_cascade.hunter, "find_email",
                        lambda *a: EmailResult(status=NOT_FOUND, provider="hunter"))
    monkeypatch.setattr(email_cascade.getprospect, "verify_email",
                        lambda e: EmailResult(email=e, status=NOT_FOUND, provider="getprospect",
                                              billed=True, cost=1.0))

    lead = _lead(_site_contacts=_site(("karim@gmail.com", "webmail")))
    email_cascade.resolve_email(lead, is_priority=True)
    assert lead["email_status"] == "not_found"


# ── b/c. Pattern et vérification ──────────────────────────────────────────────

def test_a_pattern_candidate_is_verified_and_kept(monkeypatch):
    seen = []

    def _verify(email):
        seen.append(email)
        status = VALID if email == "kelamrani@acme.ma" else NOT_FOUND
        return EmailResult(email=email, status=status, provider="getprospect",
                           billed=True, cost=1.0)

    monkeypatch.setattr(email_cascade.getprospect, "verify_email", _verify)
    lead = _lead()
    email_cascade.resolve_email(lead, is_priority=True)

    assert lead["email"] == "kelamrani@acme.ma"
    assert lead["email_source"] == "pattern_verified"
    assert seen == ["karim.elamrani@acme.ma", "kelamrani@acme.ma"], "arrêt au premier valid"


def test_unknown_moves_to_the_next_candidate_rather_than_stopping(monkeypatch):
    def _verify(email):
        status = UNKNOWN if email == "karim.elamrani@acme.ma" else VALID
        return EmailResult(email=email, status=status, provider="getprospect",
                           billed=True, cost=1.0)

    monkeypatch.setattr(email_cascade.getprospect, "verify_email", _verify)
    lead = _lead()
    email_cascade.resolve_email(lead, is_priority=True)
    assert lead["email"] == "kelamrani@acme.ma"


def test_hunter_verifies_only_after_getprospect(monkeypatch):
    """Décision 7: GetProspect's verification quota serves nothing else,
    Hunter's is shared with its searches."""
    order = []
    monkeypatch.setattr(email_cascade.getprospect, "verify_email",
                        lambda e: order.append("getprospect") or
                        EmailResult(email=e, status=UNKNOWN, provider="getprospect",
                                    billed=True, cost=1.0))
    monkeypatch.setattr(email_cascade.hunter, "verify_email",
                        lambda e: order.append("hunter") or
                        EmailResult(email=e, status=VALID, provider="hunter",
                                    billed=True, cost=0.5))
    lead = _lead()
    email_cascade.resolve_email(lead, is_priority=True)
    assert order[0] == "getprospect"
    assert "hunter" in order


def test_a_domain_without_mx_skips_pattern_generation(monkeypatch):
    monkeypatch.setattr(email_cascade.domain_intel, "lookup_mx",
                        lambda d: email_cascade.domain_intel.MxInfo(False, None))
    def _never(*a, **k):
        raise AssertionError("pas de MX = pas de vérification")
    monkeypatch.setattr(email_cascade.getprospect, "verify_email", _never)
    monkeypatch.setattr(email_cascade.prospeo, "find_email",
                        lambda *a: EmailResult(status=NOT_FOUND, provider="prospeo"))
    monkeypatch.setattr(email_cascade.getprospect, "find_email",
                        lambda *a: EmailResult(status=NOT_FOUND, provider="getprospect"))
    monkeypatch.setattr(email_cascade.hunter, "find_email",
                        lambda *a: EmailResult(status=NOT_FOUND, provider="hunter"))

    lead = _lead()
    email_cascade.resolve_email(lead, is_priority=True)
    assert lead["email_status"] == "not_found"


def test_a_catch_all_domain_spends_nothing_and_reports_catch_all(monkeypatch):
    """Verifying against a domain that accepts everything buys no information."""
    monkeypatch.setattr(email_cascade.domain_intel, "is_catch_all", lambda d, fn: True)
    def _never(*a, **k):
        raise AssertionError("un domaine catch-all ne se vérifie pas")
    monkeypatch.setattr(email_cascade.getprospect, "verify_email", _never)
    monkeypatch.setattr(email_cascade.hunter, "verify_email", _never)

    lead = _lead()
    email_cascade.resolve_email(lead, is_priority=True)
    assert lead["email_status"] == "catch_all"
    assert lead["domain_catch_all"] is True
    assert lead["email"] == "karim.elamrani@acme.ma"


def test_the_company_format_is_inferred_from_a_colleague(monkeypatch):
    """One nominatif_autre on the site collapses three verifications to one."""
    seen = []
    monkeypatch.setattr(email_cascade.getprospect, "verify_email",
                        lambda e: seen.append(e) or
                        EmailResult(email=e, status=VALID, provider="getprospect",
                                    billed=True, cost=1.0))
    lead = _lead(_site_contacts=_site(("s.bennani@acme.ma", "nominatif_autre")))
    lead["_site_colleague"] = {"email": "s.bennani@acme.ma",
                               "first_name": "Sara", "last_name": "Bennani"}
    email_cascade.resolve_email(lead, is_priority=True)
    assert seen == ["k.elamrani@acme.ma"]


# ── d. Finders ────────────────────────────────────────────────────────────────

def test_finders_run_in_order_and_stop_at_the_first_hit(monkeypatch):
    """GetProspect, puis Prospeo, puis Hunter — Hunter toujours en dernier."""
    calls = []
    monkeypatch.setattr(email_cascade.getprospect, "verify_email",
                        lambda e: EmailResult(email=e, status=NOT_FOUND,
                                              provider="getprospect", billed=True, cost=1.0))
    monkeypatch.setattr(email_cascade.hunter, "verify_email",
                        lambda e: EmailResult(email=e, status=NOT_FOUND,
                                              provider="hunter", billed=True, cost=0.5))
    monkeypatch.setattr(email_cascade.getprospect, "find_email",
                        lambda *a: calls.append("getprospect") or
                        EmailResult(status=NOT_FOUND, provider="getprospect"))
    monkeypatch.setattr(email_cascade.prospeo, "find_email",
                        lambda *a: calls.append("prospeo") or
                        EmailResult(email="k@acme.ma", status=VALID,
                                    provider="prospeo", billed=True, cost=1.0))
    monkeypatch.setattr(email_cascade.hunter, "find_email",
                        lambda *a: calls.append("hunter") or
                        EmailResult(status=NOT_FOUND, provider="hunter"))

    lead = _lead()
    email_cascade.resolve_email(lead, is_priority=True)
    assert calls == ["getprospect", "prospeo"], "Hunter n'est jamais atteint"
    assert lead["email_source"] == "prospeo"


def test_the_finder_order_puts_getprospect_first_and_hunter_last(monkeypatch):
    """Point 1 du client. Sa premisse etait fausse — Hunter etait deja dernier
    — mais GetProspect passe desormais avant Prospeo."""
    assert [name for name, _fn, _cost in email_cascade.FINDER_ORDER] == [
        "getprospect", "prospeo", "hunter"
    ]
    assert [name for name, _fn, _cost in email_cascade.VERIFIER_ORDER] == [
        "getprospect_verify", "hunter"
    ]


def test_a_non_priority_lead_never_reaches_the_finders(monkeypatch):
    """Finder credits go to the top of the prescore queue (§7). The lead was
    verified (its candidates came back not_found) but never got a finder's
    credit spent on it, so it is pending_quota — withheld, not a negative
    answer — never disappears silently into the same bucket as a lead that
    was actually checked and came back empty."""
    monkeypatch.setattr(email_cascade.getprospect, "verify_email",
                        lambda e: EmailResult(email=e, status=NOT_FOUND,
                                              provider="getprospect", billed=True, cost=1.0))
    def _never(*a, **k):
        raise AssertionError("un lead non prioritaire ne consomme pas de crédit finder")
    monkeypatch.setattr(email_cascade.prospeo, "find_email", _never)

    lead = _lead()
    email_cascade.resolve_email(lead, is_priority=False)
    assert lead["email_status"] == "pending_quota"
    assert lead.get("email") is None


def test_a_non_priority_lead_with_no_domain_at_all_stays_not_found(monkeypatch):
    """Genuinely no route to check — no website, no MX — is a real negative,
    unlike a non-priority lead on a real domain (see test above)."""
    lead = _lead(website="")
    email_cascade.resolve_email(lead, is_priority=False)
    assert lead["email_status"] == "not_found"


def test_an_incomplete_name_never_reaches_the_finders(monkeypatch):
    """Apollo sometimes supplies a surname alone ("El Lyazidi" in the
    2026-09-25 export, split as first="El" by the old naive rule). Every
    finder keys on (given name, surname, domain): the request is unanswerable
    by construction and the credit is spent for nothing."""
    def _never(*a, **k):
        raise AssertionError("un nom incomplet ne consomme pas de crédit finder")
    for provider in (email_cascade.prospeo, email_cascade.getprospect,
                     email_cascade.hunter):
        monkeypatch.setattr(provider, "find_email", _never)

    lead = _lead(first_name="", last_name="El Lyazidi")
    email_cascade.resolve_email(lead, is_priority=True)
    assert lead.get("email") is None


def test_a_complete_name_still_reaches_the_finders(monkeypatch):
    """The guard above must not be the end of the cascade for everyone else."""
    monkeypatch.setattr(email_cascade.getprospect, "verify_email",
                        lambda e: EmailResult(email=e, status=NOT_FOUND,
                                              provider="getprospect", billed=True, cost=1.0))
    monkeypatch.setattr(email_cascade.getprospect, "find_email",
                        lambda *a: EmailResult(status=NOT_FOUND, provider="getprospect"))
    monkeypatch.setattr(email_cascade.prospeo, "find_email",
                        lambda f, l, d: EmailResult(email=f"{f}@{d}", status=VALID,
                                                    provider="prospeo", billed=True, cost=1.0))

    lead = _lead()
    email_cascade.resolve_email(lead, is_priority=True)
    assert lead["email_source"] == "prospeo"


def test_a_finder_returning_another_domain_is_flagged(monkeypatch):
    monkeypatch.setattr(email_cascade.getprospect, "verify_email",
                        lambda e: EmailResult(email=e, status=NOT_FOUND,
                                              provider="getprospect", billed=True, cost=1.0))
    monkeypatch.setattr(email_cascade.getprospect, "find_email",
                        lambda *a: EmailResult(status=NOT_FOUND, provider="getprospect"))
    monkeypatch.setattr(email_cascade.prospeo, "find_email",
                        lambda *a: EmailResult(email="karim@autre.ma", status=VALID,
                                               provider="prospeo", billed=True, cost=1.0,
                                               domain_mismatch=True))
    lead = _lead()
    email_cascade.resolve_email(lead, is_priority=True)
    assert lead["domain_mismatch"] is True


# ── e. Quota ──────────────────────────────────────────────────────────────────

def test_an_exhausted_quota_everywhere_yields_pending_quota(monkeypatch):
    """The lead is not discarded: it goes back in the queue for next month."""
    for provider in ("prospeo", "getprospect", "hunter", "getprospect_verify"):
        quota_db.sync_remaining(provider, 0.0, "2026-10-01")

    def _never(*a, **k):
        raise AssertionError("aucun appel ne part sans quota")
    monkeypatch.setattr(email_cascade.prospeo, "find_email", _never)
    monkeypatch.setattr(email_cascade.getprospect, "verify_email", _never)

    lead = _lead()
    email_cascade.resolve_email(lead, is_priority=True)
    assert lead["email_status"] == "pending_quota"
    assert lead.get("email") is None


def test_a_provider_raising_quota_exhausted_falls_through_to_the_next(monkeypatch):
    monkeypatch.setattr(email_cascade.getprospect, "verify_email",
                        lambda e: EmailResult(email=e, status=NOT_FOUND,
                                              provider="getprospect", billed=True, cost=1.0))
    def _boom(*a, **k):
        raise QuotaExhausted("getprospect: INSUFFICIENT_CREDITS")
    # GetProspect runs first since the finder order was permuted, so it is the
    # one that must be able to collapse without taking the lead with it.
    monkeypatch.setattr(email_cascade.getprospect, "find_email", _boom)
    monkeypatch.setattr(email_cascade.prospeo, "find_email",
                        lambda *a: EmailResult(email="k@acme.ma", status=VALID,
                                               provider="prospeo", billed=True, cost=1.0))
    lead = _lead()
    email_cascade.resolve_email(lead, is_priority=True)
    assert lead["email_source"] == "prospeo"


# ── GetProspect balance ────────────────────────────────────────────────────────

def test_getprospect_responses_are_not_double_decremented(monkeypatch):
    """GetProspect has no account endpoint: every response already syncs its
    own balance via absorb_getprospect_metadata (see quota_sync.py), which
    lands the provider's authoritative post-call number. record_spend must
    not also subtract the cost on top of that already-synced number."""
    calls = []
    monkeypatch.setattr(quota_db, "record_spend",
                        lambda provider, cost, billed: calls.append(provider))
    billed_result = EmailResult(email="k@acme.ma", status=VALID,
                                provider="getprospect", billed=True, cost=1.0)
    email_cascade._call("getprospect", lambda: billed_result)
    email_cascade._call("getprospect_verify", lambda: billed_result)
    assert calls == []


def test_other_providers_are_still_decremented_normally(monkeypatch):
    """Only GetProspect's two labels sync their own balance — everyone else
    must keep going through record_spend as before."""
    calls = []
    monkeypatch.setattr(quota_db, "record_spend",
                        lambda provider, cost, billed: calls.append(provider))
    billed_result = EmailResult(email="k@acme.ma", status=VALID,
                                provider="hunter", billed=True, cost=0.5)
    email_cascade._call("hunter", lambda: billed_result)
    assert calls == ["hunter"]


def test_the_cache_short_circuits_a_repeat_lookup(monkeypatch):
    quota_db.cache_store("Karim", "El Amrani", "acme.ma", "prospeo",
                         {"email": "karim@acme.ma", "status": "valid"})
    monkeypatch.setattr(email_cascade.getprospect, "verify_email",
                        lambda e: EmailResult(email=e, status=NOT_FOUND,
                                              provider="getprospect", billed=True, cost=1.0))
    monkeypatch.setattr(email_cascade.hunter, "verify_email",
                        lambda e: EmailResult(email=e, status=NOT_FOUND,
                                              provider="hunter", billed=True, cost=0.5))
    def _never(*a, **k):
        raise AssertionError("le cache doit éviter l'appel réseau")
    monkeypatch.setattr(email_cascade.prospeo, "find_email", _never)

    lead = _lead()
    email_cascade.resolve_email(lead, is_priority=True)
    assert lead["email"] == "karim@acme.ma"
    assert lead["email_status"] == "valid_nominatif"
    assert lead["email_source"] == "prospeo"
    assert lead["domain_mismatch"] is False


def test_a_cached_accept_all_result_replays_as_catch_all(monkeypatch):
    """A cached accept_all payload must come back exactly as it would have
    fresh off the wire — as catch_all, never quietly upgraded to verified."""
    quota_db.cache_store("Karim", "El Amrani", "acme.ma", "prospeo",
                         {"email": "karim@acme.ma", "status": "accept_all"})
    def _never(*a, **k):
        raise AssertionError("le cache doit éviter l'appel réseau")
    monkeypatch.setattr(email_cascade.prospeo, "find_email", _never)

    lead = _lead()
    email_cascade.resolve_email(lead, is_priority=True)
    assert lead["email"] == "karim@acme.ma"
    assert lead["email_status"] == "catch_all"
    assert lead["email_source"] == "prospeo"


def test_a_cached_unknown_result_is_never_replayed_as_verified(monkeypatch):
    """The defect this guards: a finder that could not verify its own find
    must not be fabricated into a clean nominative contact just because the
    unresolved answer happens to be sitting in cache from a previous run."""
    quota_db.cache_store("Karim", "El Amrani", "acme.ma", "prospeo",
                         {"email": "karim@acme.ma", "status": "unknown"})
    monkeypatch.setattr(email_cascade.getprospect, "find_email",
                        lambda *a: EmailResult(status=NOT_FOUND, provider="getprospect"))
    monkeypatch.setattr(email_cascade.hunter, "find_email",
                        lambda *a: EmailResult(status=NOT_FOUND, provider="hunter"))

    lead = _lead()
    email_cascade.resolve_email(lead, is_priority=True)
    assert lead.get("email") is None
    assert lead["email_status"] != "valid_nominatif"


def test_a_cached_wrong_domain_result_replays_the_mismatch_flag(monkeypatch):
    """The defect this guards: RUN 2 in the bug report — a cached address on
    another company's domain must keep its mismatch warning, never lose it."""
    quota_db.cache_store("Karim", "El Amrani", "acme.ma", "prospeo",
                         {"email": "karim@autre-societe.ma", "status": "valid"})
    def _never(*a, **k):
        raise AssertionError("le cache doit éviter l'appel réseau")
    monkeypatch.setattr(email_cascade.prospeo, "find_email", _never)

    lead = _lead()
    email_cascade.resolve_email(lead, is_priority=True)
    assert lead["email"] == "karim@autre-societe.ma"
    assert lead["domain_mismatch"] is True


# ── Qui a fait le travail ─────────────────────────────────────────────────────

def test_a_verified_address_names_its_verifier(monkeypatch):
    """email_source names a branch of the cascade ("pattern_verified"), never
    a vendor. Reading it, the client concluded GetProspect was never called —
    when it is the first verifier of every candidate."""
    monkeypatch.setattr(email_cascade.getprospect, "verify_email",
                        lambda e: EmailResult(email=e, status=VALID, provider="getprospect",
                                              billed=True, cost=1.0))
    lead = _lead()
    email_cascade.resolve_email(lead, is_priority=True)

    assert lead["email_status"] == "valid_nominatif"
    assert lead["email_source"] == "pattern_verified"
    assert lead["email_verification_provider"] == "getprospect"


def test_an_address_that_went_through_no_verifier_names_none(monkeypatch):
    """The column must stay empty rather than borrow a name: a site address
    was never verified by anyone, and a finder is named by email_source."""
    lead = _lead(_site_contacts=_site(("karim.elamrani@acme.ma", "nominatif_lead")))
    email_cascade.resolve_email(lead, is_priority=True)
    assert lead["email_verification_provider"] is None

    monkeypatch.setattr(email_cascade.getprospect, "find_email",
                        lambda *a: EmailResult(email="k@acme.ma", status=VALID,
                                               provider="getprospect",
                                               billed=True, cost=1.0))
    found = _lead()
    email_cascade.resolve_email(found, is_priority=True)
    assert found["email_source"] == "getprospect"
    assert found["email_verification_provider"] is None


def test_the_verifier_name_does_not_survive_a_later_overwrite(monkeypatch):
    """A candidate verified as not_found, then replaced by the generic net,
    must not keep the verifier's name on an address it never touched."""
    monkeypatch.setattr(email_cascade.getprospect, "verify_email",
                        lambda e: EmailResult(email=e, status=NOT_FOUND,
                                              provider="getprospect", billed=True, cost=1.0))
    lead = _lead(_site_contacts=_site(("contact@acme.ma", "generique")))
    email_cascade.resolve_email(lead, is_priority=True)
    assert lead["email_status"] == "valid_generique"
    assert lead["email_verification_provider"] is None


def test_the_verification_step_reports_to_the_status_panel(monkeypatch):
    """registry.record was called from _finders alone: the panel was blind to
    the whole verification half of the cascade."""
    registry = ProviderRegistry()
    monkeypatch.setattr(email_cascade.getprospect, "verify_email",
                        lambda e: EmailResult(email=e, status=VALID, provider="getprospect",
                                              billed=True, cost=1.0))
    lead = _lead()
    email_cascade.resolve_email(lead, is_priority=True, registry=registry)

    reported = registry.to_dict()
    assert "getprospect_verify" in reported
    assert reported["getprospect_verify"]["status"] == "ok"


def test_the_catch_all_probe_is_recorded_too(monkeypatch):
    """One getprospect_verify credit per domain — 9 on the 2026-09-25 demo —
    spent with no trace anywhere."""
    registry = ProviderRegistry()
    monkeypatch.setattr(email_cascade.domain_intel, "is_catch_all",
                        lambda d, fn: fn("probe@acme.ma") == "accept_all")
    monkeypatch.setattr(email_cascade.getprospect, "verify_email",
                        lambda e: EmailResult(email=e, status=ACCEPT_ALL,
                                              provider="getprospect", billed=True, cost=1.0))
    lead = _lead()
    email_cascade.resolve_email(lead, is_priority=True, registry=registry)

    assert lead["domain_catch_all"] is True
    assert registry.to_dict()["getprospect_verify"]["status"] == "ok"


def test_a_verifier_without_credit_is_reported_as_skipped(monkeypatch):
    """An exhausted verification quota is not an outage, but the panel must
    not show it as a provider that worked either."""
    registry = ProviderRegistry()
    quota_db.sync_remaining("getprospect_verify", 0.0, "2026-11-01")
    monkeypatch.setattr(email_cascade.hunter, "verify_email",
                        lambda e: EmailResult(email=e, status=VALID, provider="hunter",
                                              billed=True, cost=0.5))
    lead = _lead()
    email_cascade.resolve_email(lead, is_priority=True, registry=registry)

    reported = registry.to_dict()
    assert reported["getprospect_verify"]["status"] == "skipped"
    assert reported["hunter"]["status"] == "ok"
    assert lead["email_verification_provider"] == "hunter"


def test_a_network_timeout_does_not_kill_the_run(monkeypatch):
    """A raw timeout from a provider must cost that provider, never the run.

    GetProspect documents verification as running live and taking up to a
    minute, so a ReadTimeout is an expected answer from it. _call names four
    typed failures; anything outside that list used to propagate out of the
    cascade and abort the whole pipeline — observed on a real run, which died
    at the cascade step after five free steps had succeeded.
    """
    import requests

    def _timeout(*a, **k):
        raise requests.exceptions.ReadTimeout("read timeout=25")

    monkeypatch.setattr(email_cascade.getprospect, "verify_email", _timeout)
    monkeypatch.setattr(email_cascade.hunter, "verify_email", _timeout)
    monkeypatch.setattr(email_cascade.prospeo, "find_email", _timeout)
    monkeypatch.setattr(email_cascade.getprospect, "find_email", _timeout)
    monkeypatch.setattr(email_cascade.hunter, "find_email", _timeout)

    lead = _lead()
    email_cascade.resolve_email(lead, is_priority=True)   # must not raise
    assert lead["email"] is None
    assert lead["email_status"] in ("not_found", "pending_quota")
