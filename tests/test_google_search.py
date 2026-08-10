from unittest.mock import patch

from enrichers.google_search import _clearbit_domain, _pick_website


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
