"""POST /api/leads/linkedin-message — no test here reaches the network."""
import json
import pathlib

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import config
from api.routes import messages

ROUTE = "/api/leads/linkedin-message"

ANGLE = "Votre refonte du site en avril peut gagner en visibilité grâce à notre Marketing Digital."
FACTS = {
    "identite_confirmee": True,
    "pays": {"value": "Maroc", "source": "website"},
    "secteur": {"value": "immobilier", "source": "website"},
    "effectif": {"value": 45, "source": "perplexity"},
    "est_concurrent": None,
    "maturite_digitale": {"value": 4, "source": "perplexity"},
    "signaux": [{"type": "refonte", "date": "2026-04", "source": "website",
                 "citation": "Nouveau site lancé en avril"}],
}


class _Block:
    def __init__(self, text: str):
        self.text = text


class _Response:
    def __init__(self, text: str):
        self.content = [_Block(text)]


class _StubAnthropic:
    """Replaces anthropic.Anthropic; records every call, answers from a queue."""

    calls: list[dict] = []
    replies: list[str] = []

    def __init__(self, api_key: str):
        self.messages = self

    def create(self, **kwargs):
        type(self).calls.append(kwargs)
        return _Response(type(self).replies.pop(0))


@pytest.fixture
def stub(monkeypatch):
    import anthropic
    monkeypatch.setattr(anthropic, "Anthropic", _StubAnthropic)
    monkeypatch.setattr(_StubAnthropic, "calls", [])
    monkeypatch.setattr(_StubAnthropic, "replies", ["Bonjour Salma, votre refonte d'avril m'a interpellé."])
    monkeypatch.setattr(config, "ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setattr(config, "LLM_MODEL", "model-from-config")
    return _StubAnthropic


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(messages.router, prefix="/api")
    return TestClient(app)


def _payload(**overrides):
    body = {
        "first_name": "Salma", "last_name": "Benani", "job_title": "Directrice marketing",
        "company": "Atlas Immo", "location": "Casablanca, Maroc",
        "conversion_angle": ANGLE, "facts_json": json.dumps(FACTS),
    }
    body.update(overrides)
    return body


# ── No angle: a readable refusal, never a model call ─────────────────────────

@pytest.mark.parametrize("angle", [None, "", "   "])
def test_missing_angle_is_refused_without_a_model_call(client, stub, angle):
    response = client.post(ROUTE, json=_payload(conversion_angle=angle))
    assert response.status_code == 422
    assert "angle" in response.json()["detail"].lower()
    assert stub.calls == []


def test_missing_api_key_is_a_readable_503(client, stub, monkeypatch):
    monkeypatch.setattr(config, "ANTHROPIC_API_KEY", "")
    response = client.post(ROUTE, json=_payload())
    assert response.status_code == 503
    assert stub.calls == []


# ── Model identifier comes from config, never from the route ─────────────────

def test_the_model_is_config_llm_model(client, stub):
    assert client.post(ROUTE, json=_payload()).status_code == 200
    assert stub.calls[0]["model"] == "model-from-config"


def test_no_model_identifier_is_hardcoded_in_the_route():
    source = pathlib.Path(messages.__file__).read_text(encoding="utf-8")
    assert "claude-" not in source


# ── Language: deduced from country / location, never from the name ───────────

def test_language_follows_the_country_fact():
    assert messages.detect_language({"pays": {"value": "Allemagne", "source": "website"}}, None) == ("de", "pays")


def test_language_falls_back_to_the_declared_location():
    assert messages.detect_language({}, "Dubai, United Arab Emirates") == ("en", "localisation")


def test_country_fact_wins_over_location():
    facts = {"pays": {"value": "Maroc", "source": "website"}}
    assert messages.detect_language(facts, "London, United Kingdom") == ("fr", "pays")


def test_no_hint_defaults_to_french():
    assert messages.detect_language({}, None) == ("fr", "defaut")
    assert messages.detect_language({}, "Paris") == ("fr", "defaut")


def test_the_name_never_decides_the_language():
    # Both routes see an English-sounding and a German-sounding name with no
    # country data: the answer must be the French default either way.
    assert messages.detect_language({}, None)[0] == "fr"


def test_location_match_is_by_whole_segment():
    # "Indiana" must not be read as "India".
    assert messages.detect_language({}, "Indianapolis, Indiana") == ("fr", "defaut")


def test_unsourced_country_is_ignored():
    facts = {"pays": {"value": "Allemagne", "source": None}}
    assert messages.detect_language(facts, None) == ("fr", "defaut")


def test_the_prompt_asks_for_the_detected_language(client, stub):
    facts = {"pays": {"value": "Espagne", "source": "website"}}
    body = _payload(facts_json=json.dumps(facts), location=None)
    response = client.post(ROUTE, json=body).json()
    assert response["language"] == "es"
    assert response["language_label"] == "espagnol"
    assert "Spanish" in stub.calls[0]["system"]


def test_the_name_does_not_reach_the_language_choice(client, stub):
    body = _payload(first_name="Hans", last_name="Müller", facts_json=None, location=None)
    assert client.post(ROUTE, json=body).json()["language"] == "fr"


# ── "No source, no fact" ─────────────────────────────────────────────────────

def test_unsourced_facts_never_reach_the_model(client, stub):
    facts = dict(FACTS, secteur={"value": "aéronautique", "source": None},
                 signaux=[{"type": "levée", "date": "2026-01", "source": None,
                           "citation": "Levée de fonds de 5 M"}])
    client.post(ROUTE, json=_payload(facts_json=json.dumps(facts)))
    prompt = stub.calls[0]["messages"][0]["content"]
    assert "aéronautique" not in prompt
    assert "Levée de fonds" not in prompt
    assert "Maroc" in prompt  # the sourced country is still there


def test_internal_judgements_are_not_passed_on(client, stub):
    client.post(ROUTE, json=_payload())
    prompt = stub.calls[0]["messages"][0]["content"]
    assert "maturite_digitale" not in prompt
    assert "est_concurrent" not in prompt


def test_a_message_with_an_invented_number_is_rejected(client, stub):
    stub.replies[:] = ["Bonjour Salma, depuis 15 ans nous accompagnons des agences.",
                       "Bonjour Salma, nous existons depuis 2009."]
    response = client.post(ROUTE, json=_payload())
    assert response.status_code == 502
    assert "écarté" in response.json()["detail"]
    assert len(stub.calls) == 2


def test_a_rejected_first_draft_is_retried_once(client, stub):
    stub.replies[:] = ["Bonjour Salma, depuis 15 ans nous vous suivons.",
                       "Bonjour Salma, votre refonte d'avril m'a interpellé."]
    response = client.post(ROUTE, json=_payload())
    assert response.status_code == 200
    assert "15" not in response.json()["message"]
    assert len(stub.calls) == 2


def test_numbers_that_come_from_the_inputs_are_accepted():
    sources = f"{ANGLE} {json.dumps(FACTS)}"
    assert messages.invented_numbers("Votre site lancé en 2026-04", sources) == set()
    assert messages.invented_numbers("Vos 45 collaborateurs", sources) == set()
    assert messages.invented_numbers("Vos 450 collaborateurs", sources) == {"450"}


# ── Provider failures are readable, not stack traces ─────────────────────────

def test_a_provider_failure_is_a_readable_502(client, stub, monkeypatch):
    def boom(self, **kwargs):
        raise RuntimeError("connection reset")
    monkeypatch.setattr(_StubAnthropic, "create", boom)
    monkeypatch.setattr("enrichers.retry.time.sleep", lambda s: None)
    response = client.post(ROUTE, json=_payload())
    assert response.status_code == 502
    assert "Réessayez" in response.json()["detail"]
