import pytest
import requests

from api import quota_db
from enrichers.providers import prospeo
from enrichers.retry import AuthError, QuotaExhausted


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(quota_db, "_DB_PATH", str(tmp_path / "q.db"))
    quota_db.init_quota_tables()
    monkeypatch.setattr("config.PROSPEO_API_KEY", "real-key")


def _respond(monkeypatch, payload, status=200):
    class _Resp:
        status_code = status
        def json(self): return payload
        def raise_for_status(self):
            if status >= 400:
                raise requests.exceptions.HTTPError(response=self)

    monkeypatch.setattr(prospeo.requests, "post", lambda *a, **k: _Resp())


# -- Success ---------------------------------------------------------------

_FOUND = {
    "error": False,
    "free_enrichment": False,
    "person": {
        "first_name": "Karim", "last_name": "El Amrani",
        "email": {
            "status": "VERIFIED", "revealed": True,
            "email": "karim.elamrani@acme.ma",
            "verification_method": "SMTP", "email_mx_provider": "Google",
        },
    },
    "company": {"domain": "acme.ma"},
}


def test_a_verified_email_is_returned_as_valid(monkeypatch):
    _respond(monkeypatch, _FOUND)
    result = prospeo.find_email("Karim", "El Amrani", "acme.ma")
    assert result.email == "karim.elamrani@acme.ma"
    assert result.status == "valid"
    assert result.billed is True


def test_free_enrichment_marks_the_result_unbilled(monkeypatch):
    """Re-enriching the same record within 90 days costs nothing. Decrementing
    the local counter anyway would end the month early for no reason."""
    _respond(monkeypatch, {**_FOUND, "free_enrichment": True})
    assert prospeo.find_email("Karim", "El Amrani", "acme.ma").billed is False


def test_an_unrevealed_email_is_not_usable(monkeypatch):
    payload = {**_FOUND, "person": {"email": {"status": "VERIFIED", "revealed": False,
                                              "email": "karim.*****@acme.ma"}}}
    _respond(monkeypatch, payload)
    assert prospeo.find_email("Karim", "El Amrani", "acme.ma").status == "not_found"


def test_an_unavailable_status_is_not_usable(monkeypatch):
    payload = {**_FOUND, "person": {"email": {"status": "UNAVAILABLE", "revealed": False,
                                              "email": None}}}
    _respond(monkeypatch, payload)
    assert prospeo.find_email("Karim", "El Amrani", "acme.ma").status == "not_found"


def test_a_null_person_never_raises(monkeypatch):
    """Prospeo documents that any property can be null, including top-level
    objects. Reaching into person.email without a guard crashes the run."""
    _respond(monkeypatch, {"error": False, "free_enrichment": False,
                           "person": None, "company": None})
    assert prospeo.find_email("Karim", "El Amrani", "acme.ma").status == "not_found"


# -- Errors ------------------------------------------------------------------

def test_no_match_is_a_miss_not_an_error(monkeypatch):
    """Prospeo answers HTTP 400 for "found nothing". Treating the status code
    as the signal would mark a perfectly healthy provider as failed."""
    _respond(monkeypatch, {"error": True, "error_code": "NO_MATCH"}, status=400)
    result = prospeo.find_email("Karim", "El Amrani", "acme.ma")
    assert result.status == "not_found"
    assert result.billed is False


def test_insufficient_credits_raises_quota_exhausted(monkeypatch):
    _respond(monkeypatch, {"error": True, "error_code": "INSUFFICIENT_CREDITS"}, status=400)
    with pytest.raises(QuotaExhausted):
        prospeo.find_email("Karim", "El Amrani", "acme.ma")


def test_invalid_api_key_raises_auth_error(monkeypatch):
    _respond(monkeypatch, {"error": True, "error_code": "INVALID_API_KEY"}, status=400)
    with pytest.raises(AuthError):
        prospeo.find_email("Karim", "El Amrani", "acme.ma")


# -- Request -------------------------------------------------------------

def test_the_request_shape_matches_the_documentation(monkeypatch):
    captured = {}

    class _Resp:
        status_code = 200
        def json(self): return _FOUND
        def raise_for_status(self): pass

    def _post(url, json=None, headers=None, timeout=None):
        captured.update({"url": url, "json": json, "headers": headers})
        return _Resp()

    monkeypatch.setattr(prospeo.requests, "post", _post)
    prospeo.find_email("Karim", "El Amrani", "acme.ma")

    assert captured["url"] == "https://api.prospeo.io/enrich-person"
    assert captured["headers"]["X-KEY"] == "real-key"
    assert captured["headers"]["Content-Type"] == "application/json"
    assert captured["json"]["only_verified_email"] is True
    assert captured["json"]["enrich_mobile"] is False, "a mobile costs 10 credits"
    assert captured["json"]["data"] == {
        "first_name": "Karim", "last_name": "El Amrani", "company_website": "acme.ma",
    }


def test_a_missing_key_skips_the_call_entirely(monkeypatch):
    monkeypatch.setattr("config.PROSPEO_API_KEY", "")
    def _boom(*a, **k):
        raise AssertionError("no call must go out without a key")
    monkeypatch.setattr(prospeo.requests, "post", _boom)
    assert prospeo.find_email("Karim", "El Amrani", "acme.ma").status == "not_found"
