import pytest
import requests

from enrichers.providers import hunter
from enrichers.providers.base import ACCEPT_ALL, NOT_FOUND, UNKNOWN, VALID
from enrichers.retry import AuthError, QuotaExhausted, RateLimited, RetryableRemoteFailure


@pytest.fixture(autouse=True)
def key(monkeypatch):
    monkeypatch.setattr("config.HUNTER_API_KEY", "real-key")
    monkeypatch.setattr(hunter, "VERIFY_POLL_DELAY", 0)


def _respond(monkeypatch, payload, status=200):
    class _Resp:
        status_code = status
        def json(self): return payload
        def raise_for_status(self):
            if status >= 400:
                raise requests.exceptions.HTTPError(response=self)

    monkeypatch.setattr(hunter.requests, "get", lambda *a, **k: _Resp())


# -- Finder -------------------------------------------------------------

def test_a_found_email_is_valid(monkeypatch):
    _respond(monkeypatch, {"data": {"email": "karim@acme.ma", "score": 97,
                                    "domain": "acme.ma", "accept_all": False,
                                    "verification": {"date": "2026-09-01", "status": "valid"}},
                           "meta": {"params": {}}})
    result = hunter.find_email("Karim", "El Amrani", "acme.ma")
    assert result.email == "karim@acme.ma"
    assert result.status == VALID
    assert result.billed is True


def test_a_null_email_is_a_miss_and_is_not_billed(monkeypatch):
    """Hunter does not document the no-result body; the OpenAPI only
    guarantees data.email is present and nullable. Test the falsy value."""
    _respond(monkeypatch, {"data": {"email": None, "score": None,
                                    "verification": {"date": None, "status": None}},
                           "meta": {"params": {}}})
    result = hunter.find_email("Karim", "El Amrani", "acme.ma")
    assert result.status == NOT_FOUND
    assert result.billed is False


def test_a_404_is_a_miss_not_a_failure(monkeypatch):
    _respond(monkeypatch, {"errors": [{"id": "not_found", "code": 404, "details": "x"}]},
             status=404)
    assert hunter.find_email("Karim", "El Amrani", "acme.ma").status == NOT_FOUND


@pytest.mark.parametrize("raw,expected", [
    ("valid", VALID), ("accept_all", ACCEPT_ALL), ("unknown", UNKNOWN),
])
def test_finder_uses_its_own_three_value_enum(monkeypatch, raw, expected):
    """The finder's verification.status has three values; the verifier's has
    six. Sharing one map would mis-read one of the two."""
    _respond(monkeypatch, {"data": {"email": "k@acme.ma",
                                    "verification": {"date": "2026-09-01", "status": raw}},
                           "meta": {}})
    assert hunter.find_email("Karim", "El Amrani", "acme.ma").status == expected


# -- Verifier -------------------------------------------------------------

@pytest.mark.parametrize("raw,expected", [
    ("valid", VALID), ("invalid", NOT_FOUND), ("accept_all", ACCEPT_ALL),
    ("webmail", UNKNOWN), ("disposable", NOT_FOUND), ("unknown", UNKNOWN),
])
def test_verifier_maps_all_six_documented_statuses(monkeypatch, raw, expected):
    _respond(monkeypatch, {"data": {"status": raw, "score": 90, "email": "k@acme.ma"},
                           "meta": {}})
    assert hunter.verify_email("k@acme.ma").status == expected


def test_a_verification_costs_half_a_credit(monkeypatch):
    _respond(monkeypatch, {"data": {"status": "valid", "email": "k@acme.ma"}, "meta": {}})
    assert hunter.verify_email("k@acme.ma").cost == 0.5


def test_202_is_polled_until_the_result_arrives(monkeypatch):
    """A 202 means the verification is still running. Polling the same
    endpoint is free - the request is billed only once."""
    responses = [
        (202, {"data": {}, "meta": {"params": {}, "message": "pending"}}),
        (202, {"data": {}, "meta": {"params": {}, "message": "pending"}}),
        (200, {"data": {"status": "valid", "email": "k@acme.ma"}, "meta": {}}),
    ]
    calls = []

    class _Resp:
        def __init__(self, status, payload):
            self.status_code, self._p = status, payload
        def json(self): return self._p
        def raise_for_status(self): pass

    def _get(*a, **k):
        status, payload = responses[len(calls)]
        calls.append(1)
        return _Resp(status, payload)

    monkeypatch.setattr(hunter.requests, "get", _get)
    result = hunter.verify_email("k@acme.ma")
    assert result.status == VALID
    assert len(calls) == 3
    assert result.cost == 0.5, "a re-polled 202 is still billed only once"


def test_222_is_a_retryable_failure_despite_being_2xx(monkeypatch):
    """222 sits inside the success range but means the remote SMTP server
    misbehaved. A client reading it as 2xx would export a bogus verdict."""
    _respond(monkeypatch, {"errors": [{"id": "smtp", "code": 222, "details": "x"}]},
             status=222)
    with pytest.raises(RetryableRemoteFailure):
        hunter.verify_email("k@acme.ma")


def test_403_is_a_rate_limit(monkeypatch):
    """The original test only exercised the 429 branch under a name that
    promised both, so a wrong 403 handler could never fail it. Hunter
    inverts the usual convention: 403 is the transient rate limit, 429 is
    the exhausted quota (enrichers/retry.py's RateLimited docstring is
    explicit that this class exists for this exact Hunter case)."""
    _respond(monkeypatch, {"errors": []}, status=403)
    with pytest.raises(RateLimited):
        hunter.verify_email("k@acme.ma")


def test_429_is_a_quota_exhausted(monkeypatch):
    _respond(monkeypatch, {"errors": []}, status=429)
    with pytest.raises(QuotaExhausted):
        hunter.verify_email("k@acme.ma")


def test_401_raises_auth_error(monkeypatch):
    _respond(monkeypatch, {"errors": []}, status=401)
    with pytest.raises(AuthError):
        hunter.verify_email("k@acme.ma")


def test_request_shape(monkeypatch):
    captured = {}

    class _Resp:
        status_code = 200
        def json(self): return {"data": {"email": "k@acme.ma",
                                         "verification": {"status": "valid"}}, "meta": {}}
        def raise_for_status(self): pass

    def _get(url, params=None, timeout=None):
        captured.update({"url": url, "params": params})
        return _Resp()

    monkeypatch.setattr(hunter.requests, "get", _get)
    hunter.find_email("Karim", "El Amrani", "acme.ma")

    assert captured["url"] == "https://api.hunter.io/v2/email-finder"
    assert captured["params"]["first_name"] == "Karim"
    assert captured["params"]["last_name"] == "El Amrani"
    assert captured["params"]["domain"] == "acme.ma"
    assert captured["params"]["api_key"] == "real-key"
