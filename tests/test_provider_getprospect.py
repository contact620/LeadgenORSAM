import pytest
import requests

from api import quota_db
from enrichers.providers import getprospect
from enrichers.providers.base import ACCEPT_ALL, NOT_FOUND, UNKNOWN, VALID
from enrichers.retry import AuthError, QuotaExhausted, RetryableRemoteFailure


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(quota_db, "_DB_PATH", str(tmp_path / "q.db"))
    quota_db.init_quota_tables()
    monkeypatch.setattr("config.GETPROSPECT_API_KEY", "real-key")


def _respond(monkeypatch, payload, status=200):
    class _Resp:
        status_code = status
        def json(self): return payload
        def raise_for_status(self):
            if status >= 400:
                raise requests.exceptions.HTTPError(response=self)

    monkeypatch.setattr(getprospect.requests, "post", lambda *a, **k: _Resp())


_CREDITS = {"email_search": 42, "email_verification": 98,
            "reset_at": "2026-10-01T00:00:00.000Z"}

_FOUND = {
    "success": True,
    "data": {"email": "karim.elamrani@acme.ma", "status": "valid",
             "account": "karim.elamrani", "domain": "acme.ma",
             "domain_status": "valid", "smtp_provider": "google",
             "free_email": False},
    "metadata": {"timestamp": "2026-09-25T14:07:55.000Z", "credits": _CREDITS},
}


def test_a_valid_email_is_returned(monkeypatch):
    _respond(monkeypatch, _FOUND)
    result = getprospect.find_email("Karim", "El Amrani", "acme.ma")
    assert result.email == "karim.elamrani@acme.ma"
    assert result.status == VALID
    assert result.billed is True


def test_not_found_is_http_200_with_success_false(monkeypatch):
    """The documentation is explicit: check success and errors, not the
    status code. A 404-based predicate would never fire."""
    _respond(monkeypatch, {
        "success": False,
        "data": {"email": None, "domain": "acme.ma", "domain_status": "valid"},
        "metadata": {"credits": _CREDITS},
        "errors": [{"name": "NOT_FOUND", "message": "No email found"}],
    }, status=200)
    result = getprospect.find_email("Karim", "El Amrani", "acme.ma")
    assert result.status == NOT_FOUND
    assert result.billed is False, "not_found is refunded automatically"


def test_accept_all_from_the_finder_is_refunded(monkeypatch):
    """The finder converts accept_all into not_found with domain_status
    accept_all, and refunds the credit."""
    _respond(monkeypatch, {
        "success": False,
        "data": {"email": None, "domain": "acme.ma", "domain_status": "accept_all"},
        "metadata": {"credits": _CREDITS},
        "errors": [{"name": "NOT_FOUND", "message": "accept-all"}],
    })
    result = getprospect.find_email("Karim", "El Amrani", "acme.ma")
    assert result.billed is False


def test_the_balance_is_absorbed_from_every_response(monkeypatch):
    """GetProspect has no account endpoint: this is the only sync channel."""
    _respond(monkeypatch, _FOUND)
    getprospect.find_email("Karim", "El Amrani", "acme.ma")
    assert quota_db.get_quota("getprospect")["remaining"] == 42.0
    assert quota_db.get_quota("getprospect_verify")["remaining"] == 98.0


def test_402_raises_quota_exhausted(monkeypatch):
    _respond(monkeypatch, {
        "success": False, "data": None, "metadata": {},
        "errors": [{"name": "PAYMENT_REQUIRED",
                    "message": "Insufficient email credits: have 0, need 1"}],
    }, status=402)
    with pytest.raises(QuotaExhausted):
        getprospect.find_email("Karim", "El Amrani", "acme.ma")


def test_401_raises_auth_error(monkeypatch):
    _respond(monkeypatch, {"success": False, "data": None,
                           "errors": [{"name": "UNAUTHORIZED", "message": "Unauthorized"}]},
             status=401)
    with pytest.raises(AuthError):
        getprospect.find_email("Karim", "El Amrani", "acme.ma")


def test_408_is_retryable(monkeypatch):
    _respond(monkeypatch, {"success": False, "data": None,
                           "errors": [{"name": "TIMEOUT", "message": "retry later"}]},
             status=408)
    with pytest.raises(RetryableRemoteFailure):
        getprospect.find_email("Karim", "El Amrani", "acme.ma")


# -- Verification -------------------------------------------------------

def test_verification_maps_valid(monkeypatch):
    _respond(monkeypatch, {**_FOUND, "data": {**_FOUND["data"], "status": "valid"}})
    assert getprospect.verify_email("karim@acme.ma").status == VALID


@pytest.mark.parametrize("raw,expected", [
    ("valid", VALID),
    ("accept_all", ACCEPT_ALL),
    ("invalid", NOT_FOUND),
    ("not_found", NOT_FOUND),
])
def test_known_verification_statuses_map(monkeypatch, raw, expected):
    _respond(monkeypatch, {"success": True, "data": {"email": "k@acme.ma", "status": raw},
                           "metadata": {"credits": _CREDITS}})
    assert getprospect.verify_email("k@acme.ma").status == expected


def test_an_undocumented_status_degrades_to_unknown(monkeypatch):
    """The OpenAPI declares status as a bare string with no enum. A value we
    have never seen must not be read as sendable, and must not crash."""
    _respond(monkeypatch, {"success": True, "data": {"email": "k@acme.ma", "status": "greylisted"},
                           "metadata": {"credits": _CREDITS}})
    result = getprospect.verify_email("k@acme.ma")
    assert result.status == UNKNOWN
    assert result.raw_status == "greylisted"


def test_the_request_shape_matches_the_v2_documentation(monkeypatch):
    captured = {}

    class _Resp:
        status_code = 200
        def json(self): return _FOUND
        def raise_for_status(self): pass

    def _post(url, json=None, headers=None, timeout=None):
        captured.update({"url": url, "json": json, "headers": headers})
        return _Resp()

    monkeypatch.setattr(getprospect.requests, "post", _post)
    getprospect.find_email("Karim", "El Amrani", "acme.ma")

    assert captured["url"] == "https://api.getprospect.com/v2/email/find"
    assert captured["headers"]["x-api-key"] == "real-key"
    assert captured["json"] == {"data": {"first_name": "Karim",
                                         "last_name": "El Amrani",
                                         "domain": "acme.ma"}}
