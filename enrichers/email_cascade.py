"""
Step 5 — Email acquisition cascade (replaces Dropcontact).

Ordered cheapest-first and stopping at the first success, because the whole
month's budget is 50 to 100 lookups:

  a. an address the company already published on its own site  — free
  b. a candidate generated from the company's format           — free to build
  c. verification of that candidate                            — 0.5 to 1 credit
  d. a finder, priority leads only                              — 1 credit
  e. nothing left to spend                                     — pending_quota

Every branch records what it cost so api/quota_db.py only ever decrements on
a result the provider actually billed.
"""
import logging
from typing import Callable, Optional
from urllib.parse import urlparse

from api import quota_db
from api.provider_status import StepOutcome
from enrichers import domain_intel, email_patterns
from enrichers.providers import getprospect, hunter, prospeo
from enrichers.providers.base import (
    ACCEPT_ALL, NOT_FOUND, UNKNOWN, VALID, EmailResult, check_domain,
)
from enrichers.retry import AuthError, QuotaExhausted, RateLimited, RetryableRemoteFailure

logger = logging.getLogger(__name__)

# Décision 7: GetProspect first — its verification quota (100/month) serves
# nothing else, while Hunter draws on a unified pool shared with its searches.
#
# Each entry wraps its provider call in a lambda rather than binding the
# function object directly. Binding `getprospect.verify_email` here would
# capture today's function at import time; a test (or a future call site)
# that monkeypatches the attribute on the `getprospect` module afterwards
# would then silently keep calling the original, since the tuple already
# holds its own reference. The lambda instead looks the attribute up on the
# module fresh on every call, so it always sees whatever is currently bound.
VERIFIER_ORDER = (
    ("getprospect_verify", lambda email: getprospect.verify_email(email),
     getprospect.COST_PER_VERIFICATION),
    ("hunter", lambda email: hunter.verify_email(email), hunter.COST_PER_VERIFICATION),
)

FINDER_ORDER = (
    ("prospeo", lambda first, last, domain: prospeo.find_email(first, last, domain),
     prospeo.COST_PER_EMAIL),
    ("getprospect", lambda first, last, domain: getprospect.find_email(first, last, domain),
     getprospect.COST_PER_EMAIL),
    ("hunter", lambda first, last, domain: hunter.find_email(first, last, domain),
     hunter.COST_PER_EMAIL),
)

EMAIL_STATUSES = frozenset({
    "valid_nominatif", "valid_generique", "catch_all",
    "unverified", "not_found", "pending_quota", "provider_failure",
})


def _domain_of(lead: dict) -> str:
    website = lead.get("website") or ""
    return urlparse(website).netloc.lower().removeprefix("www.")


def _set(lead: dict, *, email=None, status="not_found", source=None,
         email_type=None, mismatch=False) -> None:
    lead["email"] = email
    lead["email_status"] = status
    lead["email_source"] = source
    lead["email_type"] = email_type
    lead["domain_mismatch"] = mismatch



# GetProspect has no account endpoint: every one of its responses (find and
# verify alike) carries its own balance in metadata.credits and syncs it via
# absorb_getprospect_metadata before this function ever sees the result (see
# enrichers/providers/getprospect.py). Calling record_spend for these two
# labels on top of that sync double-decrements: absorb already lands the
# provider's authoritative post-call number, and record_spend would then
# subtract the cost again from a balance that already reflects this call.
_SYNCS_OWN_BALANCE = frozenset({"getprospect", "getprospect_verify"})


def _call(provider: str, fn: Callable, *args) -> Optional[EmailResult]:
    """Run one provider call, charging the local counter only when billed.

    A quota or auth failure returns None so the caller moves to the next
    provider: since Dropcontact was removed, no single provider is allowed to
    end the cascade on its own.

    The final `except Exception` is what makes that promise true rather than
    aspirational. Naming only the four typed failures left every other one —
    a read timeout above all — free to propagate out of the cascade and abort
    the whole run. That is not hypothetical: GetProspect's own documentation
    says verification "runs live and can take up to a minute", so a timeout is
    an expected answer from that endpoint, not an anomaly. A first real run
    died at step 6 on exactly that, after five free steps had already
    succeeded.
    """
    try:
        result = fn(*args)
    except (QuotaExhausted, AuthError) as exc:
        logger.warning(f"{provider} unavailable: {exc}")
        return None
    except (RateLimited, RetryableRemoteFailure) as exc:
        logger.warning(f"{provider} failed: {exc}")
        return None
    except Exception as exc:
        # Anything else — timeout, DNS failure, a shape we never anticipated.
        # The lead loses this provider, never the run.
        logger.warning(f"{provider} errored ({type(exc).__name__}): {exc}")
        return None
    if result is not None and result.billed and provider not in _SYNCS_OWN_BALANCE:
        quota_db.record_spend(provider, cost=result.cost, billed=True)
    return result


def _verify(candidate: str) -> Optional[EmailResult]:
    """Try each verifier in order until one gives a usable verdict."""
    for provider, fn, cost in VERIFIER_ORDER:
        if not quota_db.can_spend(provider, cost):
            continue
        result = _call(provider, fn, candidate)
        if result is not None and result.status in (VALID, ACCEPT_ALL, NOT_FOUND):
            return result
    return None


def resolve_email(lead: dict, is_priority: bool, registry=None) -> dict:
    """Run the cascade for one lead, writing its outcome onto the lead dict."""
    domain = _domain_of(lead)
    first = lead.get("first_name") or ""
    last = lead.get("last_name") or ""
    contacts = lead.get("_site_contacts") or {}
    site_emails = contacts.get("emails") or []

    mx = domain_intel.lookup_mx(domain)
    lead["domain_mx_provider"] = mx.provider
    lead["domain_catch_all"] = None
    _set(lead)

    # ── a. An address the company published itself ────────────────────────────
    for kind, status in (("nominatif_lead", "valid_nominatif"),
                         ("generique", "valid_generique")):
        found = next((e for e in site_emails if e.kind == kind), None)
        if found:
            _set(lead, email=found.value, status=status, source="website",
                 email_type=kind)
            lead["contact_source_url"] = found.source_url
            return lead

    if not domain or not mx.has_mx:
        # No MX means the domain receives no mail at all: generating a pattern
        # would spend a verification on an address that cannot exist.
        return _finders(lead, first, last, domain, is_priority, registry)

    # ── b. Candidates, collapsed to one when a colleague reveals the format ──
    colleague = lead.get("_site_colleague") or {}
    candidates = email_patterns.generate(
        first, last, domain,
        known_email=colleague.get("email"),
        known_first=colleague.get("first_name"),
        known_last=colleague.get("last_name"),
    )
    if not candidates:
        return _finders(lead, first, last, domain, is_priority, registry)

    # ── c. Verification, unless the domain accepts everything ────────────────
    catch_all = domain_intel.is_catch_all(domain, _probe_verifier())
    lead["domain_catch_all"] = catch_all
    if catch_all is True:
        # Verifying here buys no information: the domain says yes to anything.
        _set(lead, email=candidates[0], status="catch_all",
             source="pattern_verified", email_type="nominatif_lead")
        return lead

    for candidate in candidates:
        result = _verify(candidate)
        if result is None:
            break
        if result.status == VALID:
            _set(lead, email=candidate, status="valid_nominatif",
                 source="pattern_verified", email_type="nominatif_lead")
            return lead
        if result.status == ACCEPT_ALL:
            _set(lead, email=candidate, status="catch_all",
                 source="pattern_verified", email_type="nominatif_lead")
            return lead

    return _finders(lead, first, last, domain, is_priority, registry)


def _probe_verifier() -> Callable[[str], str]:
    """Adapter handing domain_intel a plain status string."""
    def _probe(email: str) -> str:
        result = _verify(email)
        return result.status if result is not None else "unknown"
    return _probe


def _finders(lead: dict, first: str, last: str, domain: str,
             is_priority: bool, registry=None) -> dict:
    """Step d, then e. Finder credits are reserved for priority leads (§7)."""
    if not is_priority:
        if domain and not lead.get("email"):
            _set(lead, status="pending_quota")   # credit withheld, not a negative answer
        return lead
    if not domain:
        return lead
    if not first or not last:
        # Every finder keys on (given name, surname, domain). Apollo sometimes
        # supplies only one of the two — a surname alone ("El Lyazidi"), or a
        # company name where the person should be — and the request is then
        # unanswerable by construction while still costing a credit.
        logger.info(
            f"Finders skipped for '{first} {last}'@{domain}: "
            f"an incomplete name cannot be resolved"
        )
        return lead

    quota_seen = False
    for provider, fn, cost in FINDER_ORDER:
        cached = quota_db.cache_lookup(first, last, domain, provider)
        if cached is not None:
            payload = cached["result"]
            if payload and payload.get("email"):
                status = payload.get("status")
                if status in (VALID, ACCEPT_ALL):
                    _set(lead, email=payload["email"],
                         status="valid_nominatif" if status == VALID else "catch_all",
                         source=provider, email_type="nominatif_lead",
                         mismatch=check_domain(payload["email"], domain))
                    return lead
            continue

        if not quota_db.can_spend(provider, cost):
            quota_seen = True
            continue

        result = _call(provider, fn, first, last, domain)
        if result is None:
            quota_seen = True
            continue

        quota_db.cache_store(
            first, last, domain, provider,
            {"email": result.email, "status": result.status} if result.email else None,
        )
        if registry is not None:
            registry.record(StepOutcome(provider, "ok", None, 1 if result.email else 0))
        if result.email and result.status in (VALID, ACCEPT_ALL):
            _set(lead, email=result.email,
                 status="valid_nominatif" if result.status == VALID else "catch_all",
                 source=provider, email_type="nominatif_lead",
                 mismatch=result.domain_mismatch)
            return lead

    if quota_seen and not lead.get("email"):
        # Not discarded — requeued at the head of the first batch after reset.
        _set(lead, status="pending_quota")
    return lead
