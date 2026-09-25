"""
Reachability — a boolean, not a score.

Until 2026-09-25 contact data earned points: an email was worth 40, a phone
20, a LinkedIn 30, and the total gated the expensive steps. That conflated two
unrelated questions — can we reach this person, and is this person worth
reaching — and let a perfectly irrelevant but well-documented lead outrank a
prime target whose email we simply had not found yet.

Relevance is now scored by processors/prescore.py and processors/icp_scorer.py.
Reachability is what remains: a lead either has a route to a human or it does
not. A pending_quota lead has neither answer yet, so it is None — not False.
"""
from typing import Optional

# Email statuses that actually let someone send mail. "unverified" is absent
# on purpose: the legacy "no verification ran, assume it works" fallback was
# removed with the hit score, because assuming is how invented contacts reach
# a CSV that looks exactly like a real one.
REACHABLE_EMAIL_STATUSES = frozenset({"valid_nominatif", "valid_generique", "catch_all"})

_DIRECT_EMAIL_STATUSES = frozenset({"valid_nominatif"})
_PENDING = "pending_quota"


def _has_email(lead: dict) -> bool:
    return bool(lead.get("email")) and lead.get("email_status") in REACHABLE_EMAIL_STATUSES


def is_reachable(lead: dict) -> bool:
    """True when at least one direct route to a human exists.

    LinkedIn is deliberately excluded: a profile URL is not a channel we can
    open on our own, and counting it would mark as reachable a lead nobody can
    actually contact.
    """
    if lead.get("email_status") == _PENDING:
        return False
    return _has_email(lead) or bool(lead.get("phone")) or bool(lead.get("whatsapp"))


def contact_level(lead: dict) -> str:
    """Grade the best available route: direct | indirect | aucun | indetermine."""
    if lead.get("email_status") == _PENDING:
        return "indetermine"
    if (lead.get("email_status") in _DIRECT_EMAIL_STATUSES and lead.get("email")) \
            or lead.get("phone_type") == "mobile" or lead.get("whatsapp"):
        return "direct"
    if _has_email(lead) or lead.get("phone"):
        return "indirect"
    return "aucun"


def apply_reachability(leads: list[dict]) -> tuple[list[dict], list[dict], list[dict]]:
    """Annotate every lead and split into (reachable, unreachable, pending).

    Pending leads form their own group rather than falling into unreachable:
    they were never asked the question, and burying them among the failures
    would lose them at the next monthly reset.
    """
    reachable: list[dict] = []
    unreachable: list[dict] = []
    pending: list[dict] = []

    for lead in leads:
        level = contact_level(lead)
        lead["contact_level"] = level
        if level == "indetermine":
            lead["reachable"] = None
            pending.append(lead)
        elif is_reachable(lead):
            lead["reachable"] = True
            reachable.append(lead)
        else:
            lead["reachable"] = False
            unreachable.append(lead)

    return reachable, unreachable, pending
