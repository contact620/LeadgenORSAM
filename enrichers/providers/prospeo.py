"""
Prospeo client - POST /enrich-person.

The documented /email-finder endpoint no longer exists; /enrich-person is its
functional replacement. Prospeo has no email-verification endpoint at all, so
this client only ever finds.
"""
import logging
from typing import Optional

import requests

import config
from enrichers.providers.base import (
    ACCEPT_ALL, NOT_FOUND, UNKNOWN, VALID, EmailResult, check_domain, miss,
)
from enrichers.retry import AuthError, QuotaExhausted, RetryableRemoteFailure, retry_api_call

logger = logging.getLogger(__name__)

PROVIDER = "prospeo"
ENRICH_URL = "https://api.prospeo.io/enrich-person"
COST_PER_EMAIL = 1.0

# Prospeo answers HTTP 400 for every business outcome, "found nothing"
# included, so error_code is the only usable signal.
_QUOTA_CODES = frozenset({"INSUFFICIENT_CREDITS"})
_AUTH_CODES = frozenset({"INVALID_API_KEY"})
_MISS_CODES = frozenset({"NO_MATCH", "INVALID_DATAPOINTS"})


def find_email(first: str, last: str, domain: str) -> EmailResult:
    """Look one person up. Returns a miss rather than raising when nothing matches."""
    if config._is_placeholder(config.PROSPEO_API_KEY):
        return miss(PROVIDER)
    if not first or not last or not domain:
        return miss(PROVIDER)

    payload = {
        "only_verified_email": True,   # free filter: NO_MATCH instead of a charge
        "enrich_mobile": False,        # a mobile costs 10 credits, a tenth of the monthly allowance
        "data": {
            "first_name": first,
            "last_name": last,
            "company_website": domain,
        },
    }
    headers = {"Content-Type": "application/json", "X-KEY": config.PROSPEO_API_KEY}

    def _request():
        resp = requests.post(ENRICH_URL, json=payload, headers=headers, timeout=30)
        try:
            body = resp.json()
        except ValueError:
            resp.raise_for_status()
            raise RetryableRemoteFailure(f"{PROVIDER}: non-JSON response")

        if isinstance(body, dict) and body.get("error"):
            code = str(body.get("error_code") or "")
            if code in _AUTH_CODES:
                raise AuthError(f"{PROVIDER}: {code}")
            if code in _QUOTA_CODES:
                raise QuotaExhausted(f"{PROVIDER}: {code}")
            if code in _MISS_CODES:
                return miss(PROVIDER)
            raise RetryableRemoteFailure(f"{PROVIDER}: {code or 'unknown error'}")

        resp.raise_for_status()
        return _parse(body, domain)

    return retry_api_call(_request, max_retries=2, operation_name=f"Prospeo ({domain})")


def _parse(body: dict, domain: str) -> EmailResult:
    """Normalise a success payload. Every nested object may be null."""
    person = (body or {}).get("person") or {}
    email_block = person.get("email") or {}

    address = email_block.get("email")
    revealed = bool(email_block.get("revealed"))
    raw_status = str(email_block.get("status") or "")

    # An unrevealed address is masked ("karim.*****@acme.ma") and unusable;
    # UNAVAILABLE means Prospeo has no verified address for this person.
    if not address or not revealed or raw_status.upper() != "VERIFIED":
        return miss(PROVIDER)

    billed = not bool(body.get("free_enrichment"))
    return EmailResult(
        email=address.strip().lower(),
        status=VALID,
        provider=PROVIDER,
        billed=billed,
        cost=COST_PER_EMAIL if billed else 0.0,
        raw_status=raw_status,
        domain_mismatch=check_domain(address, domain),
    )
