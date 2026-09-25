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


_QUOTA_STATUSES = frozenset({402, 429})
_RATE_LIMIT_STATUSES = frozenset({403})
_RETRYABLE_STATUSES = frozenset({222, 408})


def retry_api_call(
    fn: Callable[[], T],
    max_retries: int = 3,
    base_delay: float = 1.0,
    operation_name: str = "API call",
) -> T:
    """
    Execute fn() with retry and exponential backoff.

    - On 401 HTTP errors or SDK auth errors: raise AuthError immediately
    - On 429/402 (quota exhausted): raise QuotaExhausted immediately, never retried
    - On 403 (rate limited): raise RateLimited, retried with backoff
    - On 408, 222, or 5xx: raise RetryableRemoteFailure, retried with backoff
    - Returns the result of fn() on success
    - Raises the last exception on exhaustion
    """
    last_exc: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            return fn()
        except AuthError:
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
