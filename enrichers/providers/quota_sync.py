"""
Quota synchronisation across three providers that expose their balance three
different ways.

Prospeo and Hunter each have a free account endpoint we can poll (pull mode).
GetProspect has none: its balance rides along in metadata.credits on every
successful response (piggyback mode). A single mode cannot cover both, and
guessing a balance we cannot read is exactly how a run spends credits it does
not have.
"""
import logging
from typing import Optional

import requests

import config
from api import quota_db
from api.provider_status import StepOutcome

logger = logging.getLogger(__name__)

PROSPEO_ACCOUNT_URL = "https://api.prospeo.io/account-information"
HUNTER_ACCOUNT_URL = "https://api.hunter.io/v2/account"


def _as_float(value) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _absorb_prospeo(payload) -> bool:
    """Read Prospeo's balance. Data sits under "response", not at the root."""
    if not isinstance(payload, dict) or payload.get("error"):
        return False
    response = payload.get("response")
    if not isinstance(response, dict):
        return False
    remaining = _as_float(response.get("remaining_credits"))
    if remaining is None:
        return False
    # "2023-06-18 20:52:28+00:00" — space separator, not ISO T.
    raw_date = response.get("next_quota_renewal_date")
    reset_date = str(raw_date)[:10] if raw_date else None
    quota_db.sync_remaining("prospeo", remaining, reset_date)
    return True


def _absorb_hunter(payload) -> bool:
    """Read Hunter's balance.

    requests.credits is present only on a unified bucket (the free plan's
    case); otherwise searches and verifications are tracked separately and
    the search bucket is the binding one for the cascade.
    """
    if not isinstance(payload, dict):
        return False
    data = payload.get("data")
    if not isinstance(data, dict):
        return False
    requests_block = data.get("requests")
    if not isinstance(requests_block, dict):
        return False

    bucket = requests_block.get("credits") or requests_block.get("searches")
    if not isinstance(bucket, dict):
        return False
    remaining = _as_float(bucket.get("remaining"))
    if remaining is None:
        return False
    reset_date = data.get("reset_date")
    quota_db.sync_remaining("hunter", remaining, str(reset_date)[:10] if reset_date else None)
    return True


def absorb_getprospect_metadata(metadata) -> bool:
    """Piggyback mode — called after every successful GetProspect response."""
    if not isinstance(metadata, dict):
        return False
    credits = metadata.get("credits")
    if not isinstance(credits, dict):
        return False
    raw_reset = credits.get("reset_at")
    reset_date = str(raw_reset)[:10] if raw_reset else None

    absorbed = False
    search = _as_float(credits.get("email_search"))
    if search is not None:
        quota_db.sync_remaining("getprospect", search, reset_date)
        absorbed = True
    verify = _as_float(credits.get("email_verification"))
    if verify is not None:
        quota_db.sync_remaining("getprospect_verify", verify, reset_date)
        absorbed = True
    return absorbed


def _pull(provider: str, url: str, headers: dict, params: dict, absorber) -> str:
    try:
        resp = requests.get(url, headers=headers, params=params, timeout=10)
        resp.raise_for_status()
        payload = resp.json()
    except Exception as exc:
        logger.warning(f"Quota sync unreachable for {provider}: {exc}")
        return "unreachable"

    if absorber(payload):
        return "synced"
    # Reachable but unreadable: the provider answered 200 with a body whose
    # shape we do not recognise. That is not an outage — it is the provider
    # having changed its API, which is the single scenario this module exists
    # to survive. Logging it distinctly is what lets an operator tell the two
    # apart, since both end up as the same "unreachable" status.
    logger.warning(
        f"Quota sync for {provider}: response did not match the expected "
        f"shape; keeping the local counter."
    )
    return "unreachable"


def sync_all(registry=None) -> dict[str, str]:
    """Refresh every pullable balance, then apply any due monthly reset.

    Both account endpoints are documented as free, so this costs nothing and
    runs unconditionally at the start of a run. A provider we cannot reach
    keeps its local counter rather than blocking the run.
    """
    outcomes: dict[str, str] = {}

    if config._is_placeholder(config.PROSPEO_API_KEY):
        outcomes["prospeo"] = "skipped"
    else:
        outcomes["prospeo"] = _pull(
            "prospeo", PROSPEO_ACCOUNT_URL,
            {"X-KEY": config.PROSPEO_API_KEY}, {}, _absorb_prospeo,
        )

    if config._is_placeholder(config.HUNTER_API_KEY):
        outcomes["hunter"] = "skipped"
    else:
        outcomes["hunter"] = _pull(
            "hunter", HUNTER_ACCOUNT_URL, {},
            {"api_key": config.HUNTER_API_KEY}, _absorb_hunter,
        )

    for provider in config.PROVIDER_ALLOCATIONS:
        quota_db.apply_monthly_reset(provider)

    if registry is not None:
        for provider, state in outcomes.items():
            if state == "unreachable":
                registry.record(StepOutcome(
                    provider, "degraded",
                    "solde non synchronisé — compteur local utilisé", 0,
                ))
    return outcomes
