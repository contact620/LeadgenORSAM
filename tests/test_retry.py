import pytest
import requests

from enrichers.retry import (
    CREDIT_EXHAUSTED_MESSAGE,
    AuthError,
    CreditExhausted,
    QuotaExhausted,
    RateLimited,
    RetryableRemoteFailure,
    is_credit_exhausted,
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
    assert len(calls) == 1, "an exhausted quota must never be retried"


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


def test_quota_exhausted_raised_directly_is_never_retried():
    """Client code raises QuotaExhausted itself after parsing the provider's
    own error payload (Prospeo, GetProspect, Hunter all do this), rather than
    relying on requests.exceptions.HTTPError. That path fell into the generic
    `except Exception` branch and was retried with full backoff — up to 7s of
    dead sleep per lead per provider at the real base_delay=1.0 — which also
    contradicts QuotaExhausted's own docstring: never retried."""
    calls = []

    def fn():
        calls.append(1)
        raise QuotaExhausted("prospeo: INSUFFICIENT_CREDITS")

    with pytest.raises(QuotaExhausted):
        retry_api_call(fn, max_retries=3, base_delay=0.1, operation_name="test")
    assert len(calls) == 1, "a directly-raised QuotaExhausted must never be retried"


def test_retryable_failure_is_actually_retried_then_succeeds():
    attempts = []

    def fn():
        attempts.append(1)
        if len(attempts) < 3:
            raise _http_error(503)
        return "ok"

    assert retry_api_call(fn, max_retries=3, base_delay=0, operation_name="test") == "ok"
    assert len(attempts) == 3


class _FakeAnthropicBadRequest(Exception):
    """Stand-in for anthropic.BadRequestError: an SDK error exposes the HTTP
    status as .status_code and stringifies to the provider's payload."""

    status_code = 400

    def __init__(self, message: str):
        super().__init__(message)


_SPENT_BALANCE = (
    "Error code: 400 - {'type': 'error', 'error': {'type': 'invalid_request_error', "
    "'message': 'Your credit balance is too low to access the Anthropic API. "
    "Please go to Plans & Billing to upgrade or purchase credits.'}}"
)


def test_spent_anthropic_balance_is_a_hard_error_not_a_retry():
    """The symptom this closes: a spent balance was neither a 401 nor a 429,
    so it fell to the generic branch, was retried four times per lead, and
    then returned as an empty result — a green run with no AI columns."""
    calls = []

    def fn():
        calls.append(1)
        raise _FakeAnthropicBadRequest(_SPENT_BALANCE)

    with pytest.raises(CreditExhausted):
        retry_api_call(fn, max_retries=3, base_delay=0.1, operation_name="test")
    assert len(calls) == 1, "a spent credit balance must never be retried"


def test_spent_balance_error_carries_a_readable_message():
    def fn():
        raise _FakeAnthropicBadRequest(_SPENT_BALANCE)

    with pytest.raises(CreditExhausted) as excinfo:
        retry_api_call(fn, max_retries=0, operation_name="test")
    assert CREDIT_EXHAUSTED_MESSAGE in str(excinfo.value)


def test_credit_exhausted_is_an_auth_error_so_steps_disable_themselves():
    """Every AI step disables itself for the rest of the run on AuthError.
    Keeping CreditExhausted inside that hierarchy is what stops the pipeline
    from calling a keyless-balance API once per remaining lead."""
    assert issubclass(CreditExhausted, AuthError)


def test_an_unrelated_400_is_not_read_as_a_spent_balance():
    """Only a 400 that names the credit balance is a spent balance; other
    400s stay retryable-or-generic and must not disable the step."""
    def fn():
        raise _FakeAnthropicBadRequest(
            "Error code: 400 - {'error': {'message': 'max_tokens is too large'}}"
        )

    with pytest.raises(Exception) as excinfo:
        retry_api_call(fn, max_retries=0, base_delay=0, operation_name="test")
    assert not isinstance(excinfo.value, CreditExhausted)


def test_a_credit_balance_message_without_a_400_is_not_a_spent_balance():
    """The marker alone is not enough: the status has to agree, or any text
    quoting the phrase would disable the step."""
    def fn():
        raise RuntimeError("the docs mention a credit balance somewhere")

    with pytest.raises(Exception) as excinfo:
        retry_api_call(fn, max_retries=0, base_delay=0, operation_name="test")
    assert not isinstance(excinfo.value, CreditExhausted)


def test_is_credit_exhausted_reads_the_status_from_a_requests_response():
    """Unit test of the helper only: it reads the status from .response when
    the exception has no .status_code of its own.

    It does NOT cover retry_api_call. There, a requests HTTPError is caught by
    the dedicated clause before the generic branch that calls
    is_credit_exhausted, so a spent balance wrapped in an HTTPError is not
    turned into CreditExhausted by the retry loop. The Anthropic SDK never
    raises HTTPError, so this has no practical effect; the test used to claim
    otherwise through its name."""
    response = requests.Response()
    response.status_code = 400
    exc = requests.exceptions.HTTPError(_SPENT_BALANCE, response=response)
    assert is_credit_exhausted(exc) is True
