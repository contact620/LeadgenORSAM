"""Simple retry helper with exponential backoff for API calls."""
import logging
import time
from typing import TypeVar, Callable

import requests

logger = logging.getLogger(__name__)

T = TypeVar('T')


class AuthError(Exception):
    """Raised when an API returns 401/403, signaling invalid credentials."""
    pass


def retry_api_call(
    fn: Callable[[], T],
    max_retries: int = 3,
    base_delay: float = 1.0,
    operation_name: str = "API call",
) -> T:
    """
    Execute fn() with retry and exponential backoff.

    - On 401/403 HTTP errors or SDK auth errors: raise AuthError immediately
    - On other errors: retry up to max_retries times with delays 1s, 2s, 4s
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
            if resp is not None and resp.status_code in (401, 403):
                raise AuthError(
                    f"{operation_name}: authentication failed (HTTP {resp.status_code}). "
                    f"Check your API key."
                ) from e
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
