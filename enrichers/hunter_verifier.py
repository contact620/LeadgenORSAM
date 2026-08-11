"""
Step 3c — Hunter.io email verification.

For each lead with an email returned by Dropcontact, calls the Hunter.io
Email Verifier API to confirm deliverability and stores:
  - email_status       : valid | invalid | accept_all | webmail | disposable | unknown
  - email_confidence   : 0-100 score returned by Hunter
  - email_verification_provider : "hunter.io"

Docs: https://hunter.io/api-documentation/v2#email-verifier
Pricing: ~$0.01 per verification on the Starter plan.
"""
import logging
import time
from typing import Optional

import requests

import config
from api.provider_status import ProviderRegistry, StepOutcome
from enrichers.retry import retry_api_call, AuthError

logger = logging.getLogger(__name__)

BASE_URL = "https://api.hunter.io/v2/email-verifier"
THROTTLE_DELAY = 0.15  # ~10 req/s ceiling on standard plans

# Hunter status values we map directly
_VALID_STATUSES = {"valid", "invalid", "accept_all", "webmail", "disposable", "unknown"}

_hunter_disabled = False


def _reset_state():
    """Reset module state between pipeline runs."""
    global _hunter_disabled
    _hunter_disabled = False


def _verify_email(email: str) -> tuple[Optional[str], Optional[int]]:
    """Call Hunter.io for a single email with retry. Returns (status, confidence)."""
    global _hunter_disabled
    if _hunter_disabled:
        return None, None

    params = {"email": email, "api_key": config.HUNTER_API_KEY}

    def _do_request():
        resp = requests.get(BASE_URL, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json().get("data", {})
        status = data.get("status")
        score = data.get("score")
        if status not in _VALID_STATUSES:
            status = "unknown"
        try:
            score = int(score) if score is not None else None
        except (TypeError, ValueError):
            score = None
        return status, score

    try:
        return retry_api_call(_do_request, max_retries=3, operation_name=f"Hunter.io ({email})")
    except AuthError as e:
        _hunter_disabled = True
        logger.error(f"Hunter.io auth failed — disabled for this run: {e}")
        return None, None
    except Exception as e:
        logger.error(f"Hunter.io verification failed for {email}: {e}")
        return None, None


def enrich_leads_hunter(leads: list[dict], registry: ProviderRegistry | None = None) -> list[dict]:
    """
    Verify emails on every lead that has one. Modifies leads in place.

    Adds keys: email_status, email_confidence, email_verification_provider.
    Skips silently if HUNTER_API_KEY is absent (sets all three to None).

    Records a Hunter outcome on `registry`. This matters beyond reporting:
    processors/hit_calculator.py grants an unverified email the full 40
    points, so a Hunter failure inflates every hit score in the run. The
    operator has to be able to see that it happened.
    """
    if config._is_placeholder(config.HUNTER_API_KEY):
        logger.info("HUNTER_API_KEY not set. Skipping email verification.")
        for lead in leads:
            lead.setdefault("email_status", None)
            lead.setdefault("email_confidence", None)
            lead.setdefault("email_verification_provider", None)
        if registry:
            registry.record(StepOutcome("hunter", "skipped", "clé API absente", 0))
        return leads

    total_with_email = sum(1 for l in leads if l.get("email"))
    if total_with_email == 0:
        logger.info("Hunter.io: no email to verify, skipping.")
        for lead in leads:
            lead.setdefault("email_status", None)
            lead.setdefault("email_confidence", None)
            lead.setdefault("email_verification_provider", None)
        if registry:
            registry.record(StepOutcome("hunter", "skipped", "aucun email à vérifier", 0))
        return leads

    logger.info(f"Hunter.io: verifying {total_with_email} emails...")

    verified = 0
    valid = 0
    for i, lead in enumerate(leads, 1):
        email = lead.get("email")
        if not email:
            lead["email_status"] = None
            lead["email_confidence"] = None
            lead["email_verification_provider"] = None
            continue

        status, score = _verify_email(email)
        lead["email_status"] = status
        lead["email_confidence"] = score
        lead["email_verification_provider"] = "hunter.io" if status else None

        if status:
            verified += 1
            if status == "valid":
                valid += 1

        if _hunter_disabled:
            logger.warning(f"Hunter.io disabled — skipping remaining {total_with_email - i} emails")
            for remaining in leads[i:]:
                remaining.setdefault("email_status", None)
                remaining.setdefault("email_confidence", None)
                remaining.setdefault("email_verification_provider", None)
            break

        time.sleep(THROTTLE_DELAY)

    logger.info(
        f"Hunter.io verification complete: {verified}/{total_with_email} verified, "
        f"{valid} valid."
    )
    if registry:
        if _hunter_disabled:
            registry.record(StepOutcome(
                "hunter", "degraded",
                "clé rejetée en cours de run — emails restants non vérifiés "
                "(hit score potentiellement surévalué)",
                total_with_email - verified,
            ))
        else:
            registry.record(StepOutcome("hunter", "ok", None, verified))
    return leads


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    test_leads = [
        {"first_name": "Test", "last_name": "Valid", "email": "florian@orsam.fr"},
        {"first_name": "Test", "last_name": "Invalid", "email": "nope@nopedomain12345.xyz"},
        {"first_name": "Test", "last_name": "NoEmail", "email": None},
    ]
    result = enrich_leads_hunter(test_leads)
    for l in result:
        print(f"{l['first_name']} {l['last_name']} — {l.get('email')} → "
              f"status={l.get('email_status')} score={l.get('email_confidence')}")
