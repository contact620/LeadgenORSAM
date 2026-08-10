from unittest.mock import patch

from enrichers.google_search import _clearbit_domain, _pick_website
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
