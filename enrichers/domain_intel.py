"""
Step 4 — Domain-level checks that gate pattern generation.

Two questions decide whether generating an email candidate is worth a paid
verification: does the domain receive mail at all, and does it accept every
address thrown at it. Both are properties of the domain, not of the lead, so
both are answered once and reused for every lead sharing it — a company with
twelve contacts would otherwise pay twelve times for the same answer.
"""
import logging
import secrets
from dataclasses import dataclass
from typing import Callable, Optional

import dns.resolver

logger = logging.getLogger(__name__)

_MX_PROVIDERS = (
    ("google", ("google.com", "googlemail.com", "aspmx")),
    ("microsoft", ("outlook.com", "protection.outlook", "office365")),
)

_mx_cache: dict[str, "MxInfo"] = {}
_catch_all_cache: dict[str, Optional[bool]] = {}


@dataclass(frozen=True)
class MxInfo:
    has_mx: bool
    provider: Optional[str]     # "google" | "microsoft" | "autre" | None


def reset_caches() -> None:
    """Clear per-run domain caches. Called alongside the enricher resets."""
    _mx_cache.clear()
    _catch_all_cache.clear()


def lookup_mx(domain: str) -> MxInfo:
    """Resolve a domain's MX records once, then serve every later lead from cache."""
    key = (domain or "").strip().lower()
    if not key:
        return MxInfo(has_mx=False, provider=None)
    if key in _mx_cache:
        return _mx_cache[key]

    try:
        answers = dns.resolver.resolve(key, "MX")
        hosts = [str(getattr(r, "exchange", r)).lower() for r in answers]
    except Exception as exc:
        logger.debug(f"No MX for {key}: {exc}")
        info = MxInfo(has_mx=False, provider=None)
        _mx_cache[key] = info
        return info

    provider = "autre"
    for name, needles in _MX_PROVIDERS:
        if any(needle in host for host in hosts for needle in needles):
            provider = name
            break

    info = MxInfo(has_mx=bool(hosts), provider=provider if hosts else None)
    _mx_cache[key] = info
    return info


def is_catch_all(domain: str, verify_fn: Callable[[str], str]) -> Optional[bool]:
    """Probe one random, certainly-nonexistent address on the domain.

    Returns True (accepts anything), False (rejects unknown mailboxes) or None
    (the verifier could not tell). None is not False: recording an
    inconclusive probe as "not catch-all" would send the cascade paying to
    verify candidates on a domain that says yes to every one of them.
    """
    key = (domain or "").strip().lower()
    if not key:
        return None
    if key in _catch_all_cache:
        return _catch_all_cache[key]

    probe = f"zz{secrets.token_hex(8)}@{key}"
    try:
        status = (verify_fn(probe) or "").strip().lower()
    except Exception as exc:
        logger.debug(f"Catch-all probe failed for {key}: {exc}")
        _catch_all_cache[key] = None
        return None

    if status in ("valid", "accept_all"):
        result: Optional[bool] = True
    elif status in ("invalid", "not_found"):
        result = False
    else:
        result = None

    _catch_all_cache[key] = result
    return result
