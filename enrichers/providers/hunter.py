"""
Hunter client - /v2/email-finder and /v2/email-verifier.

Three documented quirks drive this module:
  - 403 is a rate limit and 429 is an exhausted quota, the inverse of the
    usual convention (handled in enrichers/retry.py).
  - 202 means the verification is still running: poll the same endpoint, and
    the whole exchange is billed once.
  - 222 lives in the 2xx range but reports a remote SMTP failure, so
    raise_for_status() would wave it through as a success.

The finder and the verifier also expose different status vocabularies - three
values against six - so they get separate maps rather than a shared one.
"""
import logging
import time
from typing import Optional

import requests

import config
from enrichers.providers.base import (
    ACCEPT_ALL, NOT_FOUND, UNKNOWN, VALID, EmailResult, check_domain, miss,
)
from enrichers.retry import (
    AuthError, QuotaExhausted, RateLimited, RetryableRemoteFailure, retry_api_call,
)

logger = logging.getLogger(__name__)

PROVIDER = "hunter"
FIND_URL = "https://api.hunter.io/v2/email-finder"
VERIFY_URL = "https://api.hunter.io/v2/email-verifier"
ACCOUNT_URL = "https://api.hunter.io/v2/account"

COST_PER_EMAIL = 1.0
COST_PER_VERIFICATION = 0.5

VERIFY_POLL_ATTEMPTS = 6
VERIFY_POLL_DELAY = 5.0

# email-finder: verification.status has exactly three documented values.
_FINDER_STATUS = {"valid": VALID, "accept_all": ACCEPT_ALL, "unknown": UNKNOWN}

# email-verifier: status has exactly six. webmail is mapped to UNKNOWN rather
# than VALID - a personal mailbox at a free provider is deliverable but is not
# the corporate address the cascade is looking for.
_VERIFIER_STATUS = {
    "valid": VALID, "invalid": NOT_FOUND, "accept_all": ACCEPT_ALL,
    "webmail": UNKNOWN, "disposable": NOT_FOUND, "unknown": UNKNOWN,
}


def _raise_for_business_status(status: int, label: str) -> None:
    """Translate Hunter's non-standard status codes into the shared retry
    vocabulary.

    403 and 429 are inverted relative to the usual HTTP convention: 403 is
    the transient rate limit (RateLimited, retried with backoff) and 429 is
    the exhausted monthly quota (QuotaExhausted, never retried). 222 sits
    inside the 2xx range but reports a remote SMTP failure, so it has to be
    caught here, before raise_for_status() would treat it as a success.
    """
    if status == 401:
        raise AuthError(f"{PROVIDER}: invalid API key ({label})")
    if status == 429:
        raise QuotaExhausted(f"{PROVIDER}: monthly quota exhausted ({label})")
    if status == 403:
        raise RateLimited(f"{PROVIDER}: rate limited ({label})")
    if status == 222:
        raise RetryableRemoteFailure(f"{PROVIDER}: remote SMTP failure ({label})")
    if status >= 500:
        raise RetryableRemoteFailure(f"{PROVIDER}: HTTP {status} ({label})")


def find_email(first: str, last: str, domain: str) -> EmailResult:
    if config._is_placeholder(config.HUNTER_API_KEY):
        return miss(PROVIDER)
    if not first or not last or not domain:
        return miss(PROVIDER)

    params = {
        "first_name": first, "last_name": last, "domain": domain,
        "api_key": config.HUNTER_API_KEY, "max_duration": 10,
    }

    def _request():
        resp = requests.get(FIND_URL, params=params, timeout=30)
        if resp.status_code == 404:
            # No profile matches - a normal answer, not an outage.
            return miss(PROVIDER)
        _raise_for_business_status(resp.status_code, f"find {domain}")
        resp.raise_for_status()

        data = (resp.json() or {}).get("data") or {}
        address = data.get("email")
        if not address:
            return miss(PROVIDER)

        verification = data.get("verification") or {}
        raw = str(verification.get("status") or "").strip().lower()
        return EmailResult(
            email=address.strip().lower(),
            status=_FINDER_STATUS.get(raw, UNKNOWN),
            provider=PROVIDER, billed=True, cost=COST_PER_EMAIL,
            raw_status=raw or None, domain_mismatch=check_domain(address, domain),
        )

    return retry_api_call(_request, max_retries=2, operation_name=f"Hunter find ({domain})")


def verify_email(email: str) -> EmailResult:
    """Verify one address, polling through any 202 the API returns."""
    if config._is_placeholder(config.HUNTER_API_KEY) or not email:
        return miss(PROVIDER)

    params = {"email": email, "api_key": config.HUNTER_API_KEY}

    def _request():
        for attempt in range(VERIFY_POLL_ATTEMPTS):
            resp = requests.get(VERIFY_URL, params=params, timeout=30)
            _raise_for_business_status(resp.status_code, f"verify {email}")
            if resp.status_code == 202:
                # Still running. Polling the same endpoint is free: the whole
                # exchange counts as one billed request.
                time.sleep(VERIFY_POLL_DELAY)
                continue
            resp.raise_for_status()

            data = (resp.json() or {}).get("data") or {}
            raw = str(data.get("status") or "").strip().lower()
            return EmailResult(
                email=email.strip().lower(),
                status=_VERIFIER_STATUS.get(raw, UNKNOWN),
                provider=PROVIDER, billed=True, cost=COST_PER_VERIFICATION,
                raw_status=raw or None,
            )
        raise RetryableRemoteFailure(f"{PROVIDER}: verification still pending for {email}")

    return retry_api_call(_request, max_retries=1, operation_name=f"Hunter verify ({email})")
