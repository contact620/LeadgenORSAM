import json
from unittest.mock import MagicMock, patch

import enrichers.perplexity_enricher as px
from api.provider_status import ProviderRegistry
from enrichers.perplexity_enricher import (
    COMPANY_RESEARCH_FIELDS,
    RESEARCH_FIELDS,
    _call_perplexity,
    _call_perplexity_person,
    _reset_state,
    blank_research,
    enrich_leads_perplexity,
)
from enrichers.retry import QuotaExhausted

_EMPTY_COMPANY = {field: None for field in COMPANY_RESEARCH_FIELDS}


def _lead():
    return {
        "first_name": "A", "last_name": "B", "company": "Acme",
        "website": "acme.com", "location": "Paris", "job_title": "CEO",
    }


def _answer(payload: dict):
    resp = MagicMock()
    resp.status_code = 200
    resp.raise_for_status = lambda: None
    resp.json.return_value = {
        "object": "response",
        "output": [
            {"type": "search_results", "results": []},
            {"type": "message", "role": "assistant", "content": [
                {"type": "output_text", "text": json.dumps(payload)},
            ]},
        ],
    }
    return resp


def _mock_response():
    return _answer({
        "digital_maturity": "Score: 5/10 — présence correcte.",
        "estimated_budget": "50 employés — CA non communiqué",
        "business_signals": "- [2026-05] Levée de fonds de 2M€",
    })


# ── Agent API (Sonar chat completions retired: HTTP 403 since 2026-09) ───────

def test_calls_agent_api_responses_endpoint():
    """/chat/completions now answers 403 "chat_completions_not_available" for
    sonar — every lead came back empty and capped at evidence_level="weak"."""
    _reset_state()
    with patch("enrichers.perplexity_enricher.config.PERPLEXITY_API_KEY", "key"),          patch("enrichers.perplexity_enricher.requests.post",
               return_value=_mock_response()) as mock_post:
        _call_perplexity(_lead())
    assert mock_post.call_args.args[0] == "https://api.perplexity.ai/v1/responses"
    payload = mock_post.call_args.kwargs["json"]
    assert "messages" not in payload and "model" not in payload
    assert isinstance(payload["input"], str) and "Acme" in payload["input"]


def test_parses_message_text_from_agent_output():
    _reset_state()
    with patch("enrichers.perplexity_enricher.config.PERPLEXITY_API_KEY", "key"),          patch("enrichers.perplexity_enricher.requests.post",
               return_value=_mock_response()):
        research = _call_perplexity(_lead())
    assert research == {
        "digital_maturity": "Score: 5/10 — présence correcte.",
        "estimated_budget": "50 employés — CA non communiqué",
        "business_signals": "- [2026-05] Levée de fonds de 2M€",
    }


def test_retired_endpoint_403_disables_provider():
    """A 403 whose payload says the endpoint is gone will not recover within
    the run. Leaving the provider enabled keeps "perplexity" in the expected
    sources and caps every lead at "weak" — which silently suppresses every
    commercial angle."""
    _reset_state()
    with patch("enrichers.perplexity_enricher.config.PERPLEXITY_API_KEY", "key"),          patch("enrichers.perplexity_enricher.requests.post") as mock_post:
        resp = MagicMock()
        resp.status_code = 403
        resp.json.return_value = {"error": {
            "message": "Sonar is now the Agent API.",
            "type": "chat_completions_not_available", "code": 403,
        }}
        mock_post.return_value = resp

        result = _call_perplexity(_lead())

    assert result == _EMPTY_COMPANY
    assert px._perplexity_disabled is True
    assert mock_post.call_count == 1, "a retired endpoint must not be retried"


# ── Recency filter (the actual cause of "Aucun signal récent identifié") ─────

def test_search_recency_filter_is_year_not_month():
    """Regression: the prompt asks for signals from the last 6 months, but
    the API call restricted the search to "month" — a 1-month window. That
    mismatch, not a lack of real signals, is why 9 pilot leads out of 10 came
    back with "Aucun signal récent identifié". Freshness is arbitrated
    downstream by icp_rules.signal_recency_months, not by this filter, so
    widening it here is safe."""
    _reset_state()
    with patch("enrichers.perplexity_enricher.config.PERPLEXITY_API_KEY", "key"), \
         patch("enrichers.perplexity_enricher.requests.post",
               return_value=_mock_response()) as mock_post:
        _call_perplexity(_lead())
    payload = mock_post.call_args.kwargs["json"]
    web_search = next(t for t in payload["tools"] if t["type"] == "web_search")
    assert web_search["filters"]["search_recency_filter"] == "year"


def test_search_prompt_requires_an_iso_date_per_signal():
    """_months_between (processors/icp_scorer.py) expects "YYYY-MM"; a signal
    the model dates in prose can never be recognised as recent."""
    assert "AAAA-MM" in px.SEARCH_PROMPT


# ── HTTP 403 handling (task 2 fix) ─────────────────────────────────────────

def test_403_response_does_not_disable_provider():
    """HTTP 403 is rate limiting, not auth. It must not set _perplexity_disabled
    so that subsequent leads still attempt enrichment."""
    _reset_state()
    with patch("enrichers.perplexity_enricher.config.PERPLEXITY_API_KEY", "key"), \
         patch("enrichers.perplexity_enricher.requests.post") as mock_post:
        resp = MagicMock()
        resp.status_code = 403
        resp.raise_for_status.side_effect = Exception("403 Not Found")
        mock_post.return_value = resp

        result = _call_perplexity(_lead())

    assert result == _EMPTY_COMPANY, "403 should degrade gracefully"
    assert px._perplexity_disabled is False, "403 must not disable the provider"


def test_401_response_disables_provider():
    """HTTP 401 is auth failure. It must set _perplexity_disabled so no further
    leads are attempted."""
    _reset_state()
    with patch("enrichers.perplexity_enricher.config.PERPLEXITY_API_KEY", "key"), \
         patch("enrichers.perplexity_enricher.requests.post") as mock_post:
        resp = MagicMock()
        resp.status_code = 401
        mock_post.return_value = resp

        result = _call_perplexity(_lead())

    assert result == _EMPTY_COMPANY, "401 should degrade gracefully"
    assert px._perplexity_disabled is True, "401 must disable the provider"


# ── Honest run status (§8d) ──────────────────────────────────────────────────

def test_quota_exhausted_disables_the_provider():
    """retry_api_call maps 402/429 to QuotaExhausted and its contract says the
    balance will not come back within the run. Before, that exception landed
    in the generic branch: one doomed call per remaining company, then "ok"."""
    _reset_state()
    with patch("enrichers.perplexity_enricher.config.PERPLEXITY_API_KEY", "key"), \
         patch("enrichers.perplexity_enricher.retry_api_call",
               side_effect=QuotaExhausted("Perplexity: HTTP 429")):
        result = _call_perplexity(_lead())

    assert result == _EMPTY_COMPANY
    assert px._perplexity_disabled is True
    _reset_state()


def test_quota_exhausted_is_recorded_as_degraded_with_its_reason():
    _reset_state()
    reg = ProviderRegistry()
    leads = [dict(_lead(), company=f"Acme{i}") for i in range(4)]

    with patch("enrichers.perplexity_enricher.config.PERPLEXITY_API_KEY", "key"), \
         patch("enrichers.perplexity_enricher.retry_api_call",
               side_effect=QuotaExhausted("Perplexity: HTTP 429")), \
         patch("enrichers.perplexity_enricher.time.sleep", return_value=None):
        try:
            enrich_leads_perplexity(leads, registry=reg)
        finally:
            _reset_state()

    outcome = reg.to_dict()["perplexity"]
    assert outcome["status"] == "degraded"
    assert "quota" in outcome["reason"]


def test_every_call_failing_is_recorded_as_degraded_not_ok():
    """A transient-looking error is not AuthError, so the provider stayed
    enabled, every lead came back with three None fields, and the step
    recorded "ok" — indistinguishable from a provider that was never used."""
    _reset_state()
    reg = ProviderRegistry()
    leads = [dict(_lead(), company=f"Acme{i}") for i in range(3)]

    with patch("enrichers.perplexity_enricher.config.PERPLEXITY_API_KEY", "key"), \
         patch("enrichers.perplexity_enricher.retry_api_call",
               side_effect=RuntimeError("boom")), \
         patch("enrichers.perplexity_enricher.time.sleep", return_value=None):
        try:
            enrich_leads_perplexity(leads, registry=reg)
        finally:
            _reset_state()

    outcome = reg.to_dict()["perplexity"]
    assert outcome["status"] == "degraded"
    assert "6" in (outcome["reason"] or ""), (
        "say how many calls were lost — one company and one person search per lead"
    )


def test_a_missing_key_is_recorded_as_skipped_not_absent():
    """An unconfigured provider is not an outage, but it is not silence
    either: without a record, the IA group has no member to report on."""
    _reset_state()
    reg = ProviderRegistry()

    with patch("enrichers.perplexity_enricher.config.PERPLEXITY_API_KEY", ""):
        enrich_leads_perplexity([_lead()], registry=reg)

    assert reg.to_dict()["perplexity"]["status"] == "skipped"


def test_a_successful_run_is_recorded_as_ok():
    _reset_state()
    reg = ProviderRegistry()

    with patch("enrichers.perplexity_enricher.config.PERPLEXITY_API_KEY", "key"), \
         patch("enrichers.perplexity_enricher.requests.post",
               return_value=_mock_response()), \
         patch("enrichers.perplexity_enricher.time.sleep", return_value=None):
        try:
            enrich_leads_perplexity([_lead()], registry=reg)
        finally:
            _reset_state()

    assert reg.to_dict()["perplexity"]["status"] == "ok"


def test_a_disabling_error_does_not_leak_into_the_next_run():
    """_perplexity_disabled is module state and enrich_leads_perplexity never
    reset it: one 401 in run N skipped Perplexity in every later run of the
    same server process, and would now report run N's outage as run N+1's."""
    _reset_state()
    px._perplexity_disabled = True
    px._disabled_reason = "clé Perplexity refusée ou endpoint indisponible"
    reg = ProviderRegistry()

    with patch("enrichers.perplexity_enricher.config.PERPLEXITY_API_KEY", "key"), \
         patch("enrichers.perplexity_enricher.requests.post",
               return_value=_mock_response()), \
         patch("enrichers.perplexity_enricher.time.sleep", return_value=None):
        try:
            leads = enrich_leads_perplexity([_lead()], registry=reg)
        finally:
            _reset_state()

    assert reg.to_dict()["perplexity"]["status"] == "ok"
    assert leads[0]["digital_maturity"], "the new run must actually be enriched"


# ── Person research (task 10) ────────────────────────────────────────────────

def _person_answer():
    return _answer({
        "poste_actuel": "Directrice marketing depuis 2026-06 (arrivée dans l'entreprise)",
        "perimetre": "Équipe de 6 personnes, budget acquisition Maroc",
        "realisations": ["[2026-07] Refonte du site (lesechos.ma)"],
        "prises_de_parole": "Non disponible",
    })


def test_the_person_search_is_a_second_prompt_about_the_contact():
    """The company search answers nothing about the contact. The client asked
    for the person: role, scope, what they have done publicly."""
    _reset_state()
    with patch("enrichers.perplexity_enricher.config.PERPLEXITY_API_KEY", "key"), \
         patch("enrichers.perplexity_enricher.requests.post",
               return_value=_person_answer()) as mock_post:
        research = _call_perplexity_person(_lead())

    prompt = mock_post.call_args.kwargs["json"]["input"]
    assert "PERSONNE" in prompt
    assert "A" in prompt and "Acme" in prompt
    assert research["person_research"]
    assert "Directrice marketing" in research["person_research"]
    assert "Refonte du site" in research["person_research"], "a list answer is kept"
    assert "Prises de parole" not in research["person_research"], (
        "an unavailable section must not pad the text"
    )


def test_the_person_prompt_asks_for_dated_sourced_facts():
    assert "AAAA-MM" in px.PERSON_PROMPT
    assert "Pas de source, pas d'élément" in px.PERSON_PROMPT


def test_no_linkedin_page_is_ever_fetched_for_the_person():
    """scrapers/website_scraper.py forces linkedin_text = "" so the account
    does not get banned. The person search must stay a Perplexity query."""
    _reset_state()
    with patch("enrichers.perplexity_enricher.config.PERPLEXITY_API_KEY", "key"), \
         patch("enrichers.perplexity_enricher.requests.post",
               return_value=_person_answer()) as mock_post:
        _call_perplexity_person(_lead())

    assert mock_post.call_args.args[0] == px.PERPLEXITY_API_URL
    assert mock_post.call_count == 1


def test_a_contact_row_holding_a_company_costs_no_person_call():
    """Three of the twenty demo contacts were legal entities ("Delta Btp").
    Asking what Delta Btp has achieved in their career cannot succeed, and the
    call is billed all the same."""
    _reset_state()
    lead = dict(_lead(), first_name="Delta", last_name="Btp",
                name_looks_like_company=True)
    with patch("enrichers.perplexity_enricher.config.PERPLEXITY_API_KEY", "key"), \
         patch("enrichers.perplexity_enricher.requests.post") as mock_post:
        research = _call_perplexity_person(lead)

    assert research == {"person_research": None}
    assert mock_post.call_count == 0


def test_a_nameless_row_costs_no_person_call():
    _reset_state()
    lead = dict(_lead(), first_name="", last_name="")
    with patch("enrichers.perplexity_enricher.config.PERPLEXITY_API_KEY", "key"), \
         patch("enrichers.perplexity_enricher.requests.post") as mock_post:
        assert _call_perplexity_person(lead) == {"person_research": None}
    assert mock_post.call_count == 0


def test_the_person_result_is_never_shared_between_two_colleagues():
    """The company answer is cached per company; a person is not. Caching it
    would attribute one person's career to their colleague."""
    _reset_state()
    answers = [_mock_response(), _person_answer(), _person_answer()]

    def _next(*a, **k):
        return answers.pop(0)

    leads = [dict(_lead(), first_name="Amal"), dict(_lead(), first_name="Youssef")]
    with patch("enrichers.perplexity_enricher.config.PERPLEXITY_API_KEY", "key"), \
         patch("enrichers.perplexity_enricher.requests.post", side_effect=_next) as mock_post, \
         patch("enrichers.perplexity_enricher.time.sleep", return_value=None):
        try:
            enrich_leads_perplexity(leads, registry=ProviderRegistry())
        finally:
            _reset_state()

    # One company call (cached for the second lead) + one person call per lead.
    assert mock_post.call_count == 3
    prompts = [c.kwargs["json"]["input"] for c in mock_post.call_args_list]
    assert sum(1 for p in prompts if "PERSONNE" in p) == 2
    assert all(l["person_research"] for l in leads)


def test_a_disabled_provider_skips_the_person_call_too():
    """One quota error must not cost a second doomed call per lead."""
    _reset_state()
    px._perplexity_disabled = True
    try:
        with patch("enrichers.perplexity_enricher.config.PERPLEXITY_API_KEY", "key"), \
             patch("enrichers.perplexity_enricher.requests.post") as mock_post:
            assert _call_perplexity_person(_lead()) == {"person_research": None}
        assert mock_post.call_count == 0
    finally:
        _reset_state()


def test_every_research_field_is_set_on_every_lead_of_a_run():
    """A key left missing crashes nothing visibly — it exports as an empty
    column, which is the failure mode this whole chantier exists to kill."""
    _reset_state()
    leads = [dict(_lead(), company=f"Acme{i}") for i in range(2)]
    with patch("enrichers.perplexity_enricher.config.PERPLEXITY_API_KEY", "key"), \
         patch("enrichers.perplexity_enricher.retry_api_call",
               side_effect=RuntimeError("boom")), \
         patch("enrichers.perplexity_enricher.time.sleep", return_value=None):
        try:
            enrich_leads_perplexity(leads, registry=ProviderRegistry())
        finally:
            _reset_state()

    for lead in leads:
        for field in RESEARCH_FIELDS:
            assert field in lead, field
            assert lead[field] is None


def test_blank_research_covers_the_whole_contract():
    assert set(blank_research()) == set(RESEARCH_FIELDS)
    assert all(v is None for v in blank_research().values())


def test_person_research_is_part_of_the_contract():
    assert "person_research" in RESEARCH_FIELDS
    assert "person_research" not in COMPANY_RESEARCH_FIELDS
