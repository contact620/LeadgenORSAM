import pytest
from fastapi.testclient import TestClient

from api.server import app


@pytest.fixture
def client():
    return TestClient(app)


def test_config_exposes_the_two_new_providers(client):
    body = client.get("/api/config").json()
    assert "prospeo_api_key" in body
    assert "getprospect_api_key" in body


def test_dropcontact_is_gone_from_the_config_payload(client):
    assert "dropcontact_api_key" not in client.get("/api/config").json()


def test_config_reports_quota_balances(client):
    quotas = client.get("/api/config").json()["quotas"]
    for provider in ("prospeo", "hunter", "getprospect"):
        assert "remaining" in quotas[provider]
        assert "allocation" in quotas[provider]


def test_validating_an_empty_key_is_refused_without_a_network_call(client):
    body = client.post("/api/config/validate-key",
                       json={"type": "prospeo", "value": ""}).json()
    assert body["valid"] is False


class _StubAnthropic:
    """Replaces anthropic.Anthropic so no request leaves the test."""

    raised: Exception | None = None

    def __init__(self, api_key: str):
        self.messages = self

    def create(self, **kwargs):
        if type(self).raised is not None:
            raise type(self).raised
        return object()


@pytest.fixture
def stub_anthropic(monkeypatch):
    import anthropic
    monkeypatch.setattr(anthropic, "Anthropic", _StubAnthropic)
    monkeypatch.setattr(_StubAnthropic, "raised", None)
    return _StubAnthropic


class _SdkError(Exception):
    def __init__(self, status_code: int, message: str):
        self.status_code = status_code
        super().__init__(message)


def test_testing_a_working_anthropic_key_reports_valid(client, stub_anthropic):
    body = client.post("/api/config/validate-key",
                       json={"type": "anthropic", "value": "sk-ant-whatever"}).json()
    assert body["valid"] is True


def test_a_spent_anthropic_balance_is_reported_in_plain_words(client, stub_anthropic):
    """The operator reads this string in Settings. Before, the fallback handler
    answered with the SDK's English payload dump cut at 200 characters, in
    which a spent balance was indistinguishable from a rejected key."""
    stub_anthropic.raised = _SdkError(
        400,
        "Error code: 400 - {'type': 'error', 'error': {'type': "
        "'invalid_request_error', 'message': 'Your credit balance is too low "
        "to access the Anthropic API.'}}",
    )
    body = client.post("/api/config/validate-key",
                       json={"type": "anthropic", "value": "sk-ant-whatever"}).json()
    assert body["valid"] is False
    assert "crédits Anthropic épuisés" in body["error"]
    assert "Clé valide" in body["error"], "the key itself is fine — say so"


def test_a_rejected_anthropic_key_is_reported_as_invalid(client, stub_anthropic):
    stub_anthropic.raised = _SdkError(
        401, "Error code: 401 - {'error': {'message': 'invalid x-api-key'}}")
    body = client.post("/api/config/validate-key",
                       json={"type": "anthropic", "value": "sk-ant-wrong"}).json()
    assert body["valid"] is False
    assert body["error"] == "Clé invalide"


def test_an_unexpected_anthropic_failure_still_answers_instead_of_crashing(
        client, stub_anthropic):
    stub_anthropic.raised = _SdkError(500, "Error code: 500 - overloaded")
    body = client.post("/api/config/validate-key",
                       json={"type": "anthropic", "value": "sk-ant-whatever"}).json()
    assert body["valid"] is False
    assert body["error"]
