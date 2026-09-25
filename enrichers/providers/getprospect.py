"""
GetProspect client - API v2.

Built against getprospect.com/api-docs, not getprospect.readme.io: the latter
documents an older generation with a different auth header and GET verbs.

Two things shape this client. "No result" is an HTTP 200 with success:false,
so the status code is never the predicate. And there is no account endpoint -
the balance rides along in metadata.credits, which is why every response,
successful or not, goes through absorb_getprospect_metadata before anything
else.
"""
import logging
from typing import Optional

import requests

import config
from enrichers.providers.base import (
    ACCEPT_ALL, NOT_FOUND, UNKNOWN, VALID, EmailResult, check_domain, miss,
)
from enrichers.providers.quota_sync import absorb_getprospect_metadata
from enrichers.retry import (
    AuthError, QuotaExhausted, RetryableRemoteFailure, retry_api_call,
)

logger = logging.getLogger(__name__)

PROVIDER = "getprospect"
FIND_URL = "https://api.getprospect.com/v2/email/find"
VERIFY_URL = "https://api.getprospect.com/v2/email/verify"
COST_PER_EMAIL = 1.0
COST_PER_VERIFICATION = 1.0

# Statuses attested in the documentation. Anything else degrades to UNKNOWN:
# the OpenAPI declares status as a bare string with no enum, so the list is
# known to be incomplete and must never be treated as exhaustive.
_STATUS_MAP = {
    "valid": VALID,
    "accept_all": ACCEPT_ALL,
    "invalid": NOT_FOUND,
    "not_found": NOT_FOUND,
}

_ERROR_NAMES_MISS = frozenset({"NOT_FOUND"})


def _post(url: str, payload: dict, label: str) -> dict:
    """Send one request, absorb the balance, and translate the envelope.

    Raises on auth, quota and retryable failures; returns the parsed body
    otherwise, including the success:false / NOT_FOUND case which is a normal
    answer rather than an error.
    """
    headers = {"Content-Type": "application/json", "x-api-key": config.GETPROSPECT_API_KEY}
    resp = requests.post(url, json=payload, headers=headers, timeout=60)
    try:
        body = resp.json()
    except ValueError:
        resp.raise_for_status()
        raise RetryableRemoteFailure(f"{PROVIDER}: non-JSON response")

    if isinstance(body, dict):
        absorb_getprospect_metadata(body.get("metadata"))

    status = resp.status_code
    if status == 401:
        raise AuthError(f"{PROVIDER}: unauthorized ({label})")
    if status == 402:
        raise QuotaExhausted(f"{PROVIDER}: credit limit reached ({label})")
    if status == 408 or status >= 500:
        raise RetryableRemoteFailure(f"{PROVIDER}: HTTP {status} ({label})")
    resp.raise_for_status()
    return body if isinstance(body, dict) else {}


def _errors_are_a_miss(body: dict) -> bool:
    errors = body.get("errors")
    if not isinstance(errors, list):
        return False
    return any(
        isinstance(e, dict) and str(e.get("name", "")).upper() in _ERROR_NAMES_MISS
        for e in errors
    )


def find_email(first: str, last: str, domain: str) -> EmailResult:
    if config._is_placeholder(config.GETPROSPECT_API_KEY):
        return miss(PROVIDER)
    if not first or not last or not domain:
        return miss(PROVIDER)

    payload = {"data": {"first_name": first, "last_name": last, "domain": domain}}

    def _request():
        body = _post(FIND_URL, payload, f"find {domain}")
        if not body.get("success") or _errors_are_a_miss(body):
            # not_found and accept_all are both refunded automatically.
            return miss(PROVIDER)

        data = body.get("data") or {}
        address = data.get("email")
        if not address:
            return miss(PROVIDER)

        raw = str(data.get("status") or "").strip().lower()
        status = _STATUS_MAP.get(raw, UNKNOWN)
        billed = status == VALID
        return EmailResult(
            email=address.strip().lower(), status=status, provider=PROVIDER,
            billed=billed, cost=COST_PER_EMAIL if billed else 0.0,
            raw_status=raw or None, domain_mismatch=check_domain(address, domain),
        )

    return retry_api_call(_request, max_retries=2, operation_name=f"GetProspect find ({domain})")


def verify_email(email: str) -> EmailResult:
    """Verify one address. Draws on the verification quota, not the search one."""
    if config._is_placeholder(config.GETPROSPECT_API_KEY) or not email:
        return miss(PROVIDER)

    def _request():
        body = _post(VERIFY_URL, {"data": {"email": email}}, f"verify {email}")
        if not body.get("success"):
            return miss(PROVIDER)
        data = body.get("data") or {}
        raw = str(data.get("status") or "").strip().lower()
        return EmailResult(
            email=email.strip().lower(),
            status=_STATUS_MAP.get(raw, UNKNOWN),
            provider=PROVIDER, billed=True, cost=COST_PER_VERIFICATION,
            raw_status=raw or None,
        )

    return retry_api_call(_request, max_retries=2, operation_name=f"GetProspect verify ({email})")
