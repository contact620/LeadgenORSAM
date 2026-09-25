import pytest

import config
from api import quota_db
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


def test_a_generic_site_email_is_kept_but_marked_generique(monkeypatch):
    monkeypatch.setattr(email_cascade.getprospect, "verify_email",
                        lambda e: EmailResult(email=e, status=VALID, provider="getprospect",
                                              billed=True, cost=1.0))
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
    calls = []
    monkeypatch.setattr(email_cascade.getprospect, "verify_email",
                        lambda e: EmailResult(email=e, status=NOT_FOUND,
                                              provider="getprospect", billed=True, cost=1.0))
    monkeypatch.setattr(email_cascade.hunter, "verify_email",
                        lambda e: EmailResult(email=e, status=NOT_FOUND,
                                              provider="hunter", billed=True, cost=0.5))
    monkeypatch.setattr(email_cascade.prospeo, "find_email",
                        lambda *a: calls.append("prospeo") or
                        EmailResult(status=NOT_FOUND, provider="prospeo"))
    monkeypatch.setattr(email_cascade.getprospect, "find_email",
                        lambda *a: calls.append("getprospect") or
                        EmailResult(email="k@acme.ma", status=VALID,
                                    provider="getprospect", billed=True, cost=1.0))
    monkeypatch.setattr(email_cascade.hunter, "find_email",
                        lambda *a: calls.append("hunter") or
                        EmailResult(status=NOT_FOUND, provider="hunter"))

    lead = _lead()
    email_cascade.resolve_email(lead, is_priority=True)
    assert calls == ["prospeo", "getprospect"], "Hunter n'est jamais atteint"
    assert lead["email_source"] == "getprospect"


def test_a_non_priority_lead_never_reaches_the_finders(monkeypatch):
    """Finder credits go to the top of the prescore queue (§7)."""
    monkeypatch.setattr(email_cascade.getprospect, "verify_email",
                        lambda e: EmailResult(email=e, status=NOT_FOUND,
                                              provider="getprospect", billed=True, cost=1.0))
    def _never(*a, **k):
        raise AssertionError("un lead non prioritaire ne consomme pas de crédit finder")
    monkeypatch.setattr(email_cascade.prospeo, "find_email", _never)

    lead = _lead()
    email_cascade.resolve_email(lead, is_priority=False)
    assert lead["email_status"] == "not_found"


def test_a_finder_returning_another_domain_is_flagged(monkeypatch):
    monkeypatch.setattr(email_cascade.getprospect, "verify_email",
                        lambda e: EmailResult(email=e, status=NOT_FOUND,
                                              provider="getprospect", billed=True, cost=1.0))
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
        raise QuotaExhausted("prospeo: INSUFFICIENT_CREDITS")
    monkeypatch.setattr(email_cascade.prospeo, "find_email", _boom)
    monkeypatch.setattr(email_cascade.getprospect, "find_email",
                        lambda *a: EmailResult(email="k@acme.ma", status=VALID,
                                               provider="getprospect", billed=True, cost=1.0))
    lead = _lead()
    email_cascade.resolve_email(lead, is_priority=True)
    assert lead["email_source"] == "getprospect"


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
