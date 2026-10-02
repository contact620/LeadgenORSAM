"""Simple retry helper with exponential backoff for API calls."""
import logging
import time
from typing import TypeVar, Callable

import requests

logger = logging.getLogger(__name__)

T = TypeVar('T')


class AuthError(Exception):
    """Raised when an API returns 401, signaling invalid credentials."""
    pass


class QuotaExhausted(Exception):
    """Monthly allowance spent. Never retried: the balance will not come back
    within this run. Hunter signals it with 429, GetProspect with 402."""


class RateLimited(Exception):
    """Throughput ceiling hit. Retried with backoff — this is transient.

    Hunter returns 403 here, not 429: the two are inverted relative to the
    usual HTTP convention. Reading 403 as an auth failure (as this module
    did until 2026-09-25) disabled the provider for the whole run on a
    transient spike.
    """


class RetryableRemoteFailure(Exception):
    """The remote side failed in a way that may not repeat: 408 timeout,
    Hunter's non-standard 222 (remote SMTP server misbehaved), or any 5xx."""


class CreditExhausted(AuthError):
    """The Anthropic key is well-formed but its prepaid balance is spent.

    Subclasses AuthError on purpose: retry_api_call re-raises AuthError
    without retrying, and every AI step already disables itself for the rest
    of the run when it sees one. A balance does not refill mid-run, so
    retrying three times per lead only burns minutes before producing the
    same emptiness — and leaves the operator with a green run and no data.
    """


_QUOTA_STATUSES = frozenset({402, 429})
_RATE_LIMIT_STATUSES = frozenset({403})
_RETRYABLE_STATUSES = frozenset({222, 408})

# Anthropic reports a spent balance as a 400 invalid_request_error whose
# message names the credit balance — not a 401, not a 429. Neither the status
# table above nor the class-name auth sniffing below recognises it, so until
# this marker existed the error fell through to the generic branch and was
# retried four times per lead before being swallowed as an empty result.
_CREDIT_EXHAUSTED_MARKER = "credit balance"

# Operator-facing, hence French: this string reaches the run's provider panel
# and the key-test button in Settings.
CREDIT_EXHAUSTED_MESSAGE = (
    "crédits Anthropic épuisés — rechargez le solde sur console.anthropic.com"
)


def _http_status(exc: Exception) -> int | None:
    """HTTP status carried by an SDK error or a requests error, if any."""
    status = getattr(exc, "status_code", None)
    if isinstance(status, int):
        return status
    status = getattr(getattr(exc, "response", None), "status_code", None)
    return status if isinstance(status, int) else None


def is_credit_exhausted(exc: Exception) -> bool:
    """True for the Anthropic SDK's spent-balance error (HTTP 400)."""
    return _http_status(exc) == 400 and _CREDIT_EXHAUSTED_MARKER in str(exc).lower()


def retry_api_call(
    fn: Callable[[], T],
    max_retries: int = 3,
    base_delay: float = 1.0,
    operation_name: str = "API call",
) -> T:
    """
    Execute fn() with retry and exponential backoff.

    - On 401 HTTP errors or SDK auth errors: raise AuthError immediately
    - On a 400 naming the credit balance (Anthropic's spent prepaid balance):
      raise CreditExhausted immediately, never retried
    - On 429/402 (quota exhausted): raise QuotaExhausted immediately, never retried
    - On 403 (rate limited): raise RateLimited, retried with backoff
    - On 408, 222, or 5xx: raise RetryableRemoteFailure, retried with backoff
    - A QuotaExhausted or AuthError raised directly by fn() (client code that
      parsed the provider's own error payload, rather than going through
      requests.exceptions.HTTPError) is re-raised immediately, never retried
    - Returns the result of fn() on success
    - Raises the last exception on exhaustion
    """
    last_exc: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            return fn()
        except (AuthError, QuotaExhausted):
            # Both are raised directly by client code that already parsed the
            # provider's own error payload (all three providers do this).
            # Retrying either is dead time: an exhausted quota will not come
            # back within this run, and a bad key will not fix itself between
            # attempts. RateLimited and RetryableRemoteFailure stay out of
            # this branch on purpose — those are transient by definition and
            # retrying them is the whole point of this function.
            raise
        except requests.exceptions.HTTPError as e:
            resp = e.response
            status = resp.status_code if resp is not None else None
            if status == 401:
                raise AuthError(
                    f"{operation_name}: authentication failed (HTTP 401). "
                    f"Check your API key."
                ) from e
            if status in _QUOTA_STATUSES:
                raise QuotaExhausted(
                    f"{operation_name}: provider quota exhausted (HTTP {status})."
                ) from e
            if status in _RATE_LIMIT_STATUSES:
                last_exc = RateLimited(f"{operation_name}: rate limited (HTTP {status}).")
            elif status is not None and (status in _RETRYABLE_STATUSES or status >= 500):
                last_exc = RetryableRemoteFailure(
                    f"{operation_name}: remote failure (HTTP {status})."
                )
            else:
                last_exc = e
        except Exception as e:
            if is_credit_exhausted(e):
                raise CreditExhausted(
                    f"{operation_name}: {CREDIT_EXHAUSTED_MESSAGE}"
                ) from e
            # Detect Anthropic SDK auth errors by class name
            err_type = type(e).__name__.lower()
            if 'authentication' in err_type or 'permission' in err_type:
                raise AuthError(f"{operation_name}: authentication failed ({e})") from e
            last_exc = e

        if attempt < max_retries:
            delay = base_delay * (2 ** attempt)
            logger.warning(
                f"{operation_name}: attempt {attempt + 1}/{max_retries + 1} failed "
                f"({last_exc}). Retrying in {delay:.0f}s..."
            )
            time.sleep(delay)

    logger.error(f"{operation_name}: all {max_retries + 1} attempts failed.")
    raise last_exc  # type: ignore[misc]
