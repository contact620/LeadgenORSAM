import json
from unittest.mock import MagicMock, patch

import enrichers.perplexity_enricher as px
from enrichers.perplexity_enricher import _call_perplexity, _reset_state


def _lead():
    return {
        "first_name": "A", "last_name": "B", "company": "Acme",
        "website": "acme.com", "location": "Paris", "job_title": "CEO",
    }


def _mock_response():
    resp = MagicMock()
    resp.status_code = 200
    resp.raise_for_status = lambda: None
    resp.json.return_value = {
        "choices": [{"message": {"content": json.dumps({
            "digital_maturity": "Score: 5/10 — présence correcte.",
            "estimated_budget": "50 employés — CA non communiqué",
            "business_signals": "- [2026-05] Levée de fonds de 2M€",
        })}}]
    }
    return resp


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
    assert payload["search_recency_filter"] == "year"


def test_search_prompt_requires_an_iso_date_per_signal():
    """_months_between (processors/icp_scorer.py) expects "YYYY-MM"; a signal
    the model dates in prose can never be recognised as recent."""
    assert "AAAA-MM" in px.SEARCH_PROMPT
