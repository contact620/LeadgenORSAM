from unittest.mock import patch

import enrichers.google_search as gs
from api.provider_status import ProviderRegistry
from enrichers.google_search import _clearbit_domain, _pick_website, enrich_leads_google
from processors.coherence import CoherenceResult


def test_clearbit_rejects_generic_word_match():
    # Real failure: "Alp Financial" accepted "Financial Times" -> ft.com
    fake = [{"name": "Financial Times", "domain": "ft.com"}]
    with patch("enrichers.google_search.retry_api_call", return_value=fake):
        assert _clearbit_domain("Alp Financial") is None


def test_clearbit_accepts_real_match():
    fake = [{"name": "Acme Solutions SARL", "domain": "acme-solutions.ma"}]
    with patch("enrichers.google_search.retry_api_call", return_value=fake):
        assert _clearbit_domain("Acme Solutions") == "https://acme-solutions.ma"


def test_clearbit_scans_all_candidates_not_only_the_first():
    fake = [
        {"name": "Unrelated Corp", "domain": "unrelated.com"},
        {"name": "Houzing", "domain": "houzing.eu"},
    ]
    with patch("enrichers.google_search.retry_api_call", return_value=fake):
        assert _clearbit_domain("Houzing") == "https://houzing.eu"


def test_clearbit_returns_none_on_empty_results():
    with patch("enrichers.google_search.retry_api_call", return_value=[]):
        assert _clearbit_domain("Whatever") is None


def test_pick_website_skips_blocked_domains():
    urls = [
        "https://www.linkedin.com/company/acme",
        "https://fr.wikipedia.org/wiki/Acme",
        "https://acme.ma/about",
    ]
    assert _pick_website(urls) == "https://acme.ma/about"


def test_pick_website_does_not_truncate_domain_names():
    # Regression on lstrip("www."): "wework.com" must not become "ework.com"
    assert _pick_website(["https://wework.com"]) == "https://wework.com"


def test_verify_website_rejects_unrelated_page():
    from enrichers.google_search import verify_website
    html = "<html><head><title>Rentkasa</title></head><body>" + \
           "Rentkasa propose des locations saisonnieres en Espagne. " * 5 + \
           "</body></html>"

    class _Resp:
        status_code = 200
        text = html

        def raise_for_status(self):
            return None

    with patch("enrichers.google_search.requests.get", return_value=_Resp()):
        result = verify_website("https://rentkasa.com", "Houzing", "Paris, France")
    assert result.coherent is False


def test_verify_website_is_inconclusive_when_fetch_fails():
    from enrichers.google_search import verify_website
    with patch("enrichers.google_search.requests.get", side_effect=OSError("boom")):
        result = verify_website("https://acme.ma", "Acme", "Casablanca, Maroc")
    assert result.coherent is True
    assert result.verified is False


def test_verify_website_reads_the_whole_page_not_just_the_first_1500_chars():
    """The legal name lives in the footer; the old 1500-char window missed it."""
    from enrichers.google_search import verify_website

    filler = "<p>Nous accompagnons les investisseurs dans leurs projets.</p>" * 60
    html = ("<html><head><title>Accueil</title></head><body>"
            + filler
            + "<footer>Groupe Zenith Immobilier SARL — Casablanca</footer>"
            + "</body></html>")

    class _Resp:
        status_code = 200
        text = html

        def raise_for_status(self):
            return None

    with patch("enrichers.google_search.requests.get", return_value=_Resp()):
        result = verify_website("https://zenith.ma", "Groupe Zenith Immobilier",
                                "Casablanca, Maroc")
    assert result.coherent is True
    assert result.verified is True


# ── Serper provider health ───────────────────────────────────────────────────

def _minimal_leads():
    return [{"first_name": "A", "last_name": "B", "company": "Acme", "location": ""}]


def _no_network():
    """Neutralise every outbound call and the inter-request sleeps."""
    return (
        patch("enrichers.google_search._serper_search", return_value=[]),
        patch("enrichers.google_search._ddg_search", return_value=[]),
        patch("enrichers.google_search._clearbit_domain", return_value=None),
        patch("enrichers.google_search.time.sleep", return_value=None),
    )


def _run_google(registry):
    patches = _no_network()
    for p in patches:
        p.start()
    try:
        enrich_leads_google(_minimal_leads(), registry=registry)
    finally:
        for p in patches:
            p.stop()


def test_serper_missing_key_is_recorded_as_skipped():
    gs._reset_state()
    reg = ProviderRegistry()
    with patch("enrichers.google_search.config.SERPER_API_KEY", ""):
        _run_google(reg)
    assert reg.to_dict()["serper"]["status"] == "skipped"


def test_serper_key_rejected_mid_run_is_recorded_as_degraded():
    """The original symptom: 30 points per lead lost, provider_status empty."""
    gs._reset_state()
    reg = ProviderRegistry()
    with patch("enrichers.google_search.config.SERPER_API_KEY", "key"):
        gs._serper_disabled = True
        try:
            _run_google(reg)
        finally:
            gs._reset_state()
    entry = reg.to_dict()["serper"]
    assert entry["status"] == "degraded"
    assert entry["reason"]


def test_serper_healthy_run_is_recorded_as_ok():
    gs._reset_state()
    reg = ProviderRegistry()
    with patch("enrichers.google_search.config.SERPER_API_KEY", "key"):
        _run_google(reg)
    assert reg.to_dict()["serper"]["status"] == "ok"


def test_enrich_leads_google_without_registry_still_works():
    """The CLI used to call this with no registry; keep the argument optional."""
    gs._reset_state()
    patches = _no_network()
    for p in patches:
        p.start()
    try:
        assert len(enrich_leads_google(_minimal_leads())) == 1
    finally:
        for p in patches:
            p.stop()
