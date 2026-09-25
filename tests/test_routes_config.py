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
