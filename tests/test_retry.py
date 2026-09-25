import pytest
import requests

from enrichers.retry import (
    AuthError,
    QuotaExhausted,
    RateLimited,
    RetryableRemoteFailure,
    retry_api_call,
)


def _http_error(status: int) -> requests.exceptions.HTTPError:
    response = requests.Response()
    response.status_code = status
    return requests.exceptions.HTTPError(response=response)


def test_401_raises_auth_error():
    def fn():
        raise _http_error(401)
    with pytest.raises(AuthError):
        retry_api_call(fn, max_retries=0, operation_name="test")


def test_403_is_a_rate_limit_not_an_auth_error():
    """Hunter uses 403 for rate limiting. Treating it as auth kills the
    provider for the whole run on a transient throughput spike."""
    def fn():
        raise _http_error(403)
    with pytest.raises(RateLimited):
        retry_api_call(fn, max_retries=0, base_delay=0, operation_name="test")


def test_429_is_quota_exhausted_and_never_retried():
    calls = []

    def fn():
        calls.append(1)
        raise _http_error(429)

    with pytest.raises(QuotaExhausted):
        retry_api_call(fn, max_retries=3, base_delay=0, operation_name="test")
    assert len(calls) == 1, "un quota épuisé ne doit jamais être réessayé"


def test_402_is_quota_exhausted():
    """GetProspect signals an exhausted credit balance with 402."""
    def fn():
        raise _http_error(402)
    with pytest.raises(QuotaExhausted):
        retry_api_call(fn, max_retries=0, operation_name="test")


def test_408_is_retryable():
    def fn():
        raise _http_error(408)
    with pytest.raises(RetryableRemoteFailure):
        retry_api_call(fn, max_retries=0, base_delay=0, operation_name="test")


def test_222_is_retryable():
    """Hunter's non-standard 222 sits inside the 2xx range but is a failure:
    the remote SMTP server misbehaved."""
    def fn():
        raise _http_error(222)
    with pytest.raises(RetryableRemoteFailure):
        retry_api_call(fn, max_retries=0, base_delay=0, operation_name="test")


def test_retryable_failure_is_actually_retried_then_succeeds():
    attempts = []

    def fn():
        attempts.append(1)
        if len(attempts) < 3:
            raise _http_error(503)
        return "ok"

    assert retry_api_call(fn, max_retries=3, base_delay=0, operation_name="test") == "ok"
    assert len(attempts) == 3
