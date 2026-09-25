"""
Common contract for the three email providers.

They disagree on everything - Prospeo nests results under "person" and answers
400 for "nothing found", GetProspect wraps everything in a success envelope
and answers 200 for the same case, Hunter returns a flat payload and inverts
403/429. The cascade must not know any of that, so each client normalises into
EmailResult and nothing else escapes.
"""
from dataclasses import dataclass
from typing import Optional

# Statuses the cascade branches on. Deliberately narrower than any provider's
# own vocabulary: an unrecognised provider status maps to "unknown", never to
# an exception and never optimistically to "valid".
VALID = "valid"
ACCEPT_ALL = "accept_all"
UNKNOWN = "unknown"
NOT_FOUND = "not_found"


@dataclass(frozen=True)
class EmailResult:
    email: Optional[str] = None
    status: str = NOT_FOUND
    provider: Optional[str] = None
    billed: bool = False
    cost: float = 0.0
    raw_status: Optional[str] = None
    domain_mismatch: bool = False


def miss(provider: str) -> EmailResult:
    """The provider answered and had nothing. Never billed."""
    return EmailResult(status=NOT_FOUND, provider=provider, billed=False, cost=0.0)


def check_domain(email: Optional[str], expected_domain: str) -> bool:
    """True when the returned address does not belong to the company.

    A finder matching the wrong person returns a real, verifiable address on
    someone else's domain. Exporting it as this lead's contact is worse than
    returning nothing, so the mismatch travels with the result.
    """
    if not email or "@" not in email or not expected_domain:
        return False
    returned = email.rsplit("@", 1)[1].strip().lower().removeprefix("www.")
    return returned != expected_domain.strip().lower().removeprefix("www.")
