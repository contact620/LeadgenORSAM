from unittest.mock import patch

import requests

import enrichers.google_search as gs
from api.provider_status import ProviderRegistry
from enrichers.google_search import PageFetch, _clearbit_domain, _pick_website, enrich_leads_google, verify_website
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
    html = "<html><head><title>Rentkasa</title></head><body>" + \
           "Rentkasa propose des locations saisonnieres en Espagne. " * 5 + \
           "</body></html>"

    class _Resp:
        status_code = 200
        text = html

        def raise_for_status(self):
            return None

    with patch("enrichers.google_search.requests.get", return_value=_Resp()):
        result, page = verify_website("https://rentkasa.com", "Houzing")
    assert result.coherent is False


def test_verify_website_is_inconclusive_when_fetch_fails():
    with patch("enrichers.google_search.requests.get", side_effect=OSError("boom")):
        result, page = verify_website("https://acme.ma", "Acme")
    assert result.coherent is True
    assert result.verified is False


def test_verify_website_reads_the_whole_page_not_just_the_first_1500_chars():
    """The legal name lives in the footer; the old 1500-char window missed it."""
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
        result, page = verify_website("https://zenith.ma", "Groupe Zenith Immobilier")
    assert result.coherent is True
    assert result.verified is True


def test_verify_website_returns_the_fetched_page(monkeypatch):
    html = "<html><head><title>Acme Maroc</title></head><body>" + "Acme Maroc " * 40 + "</body></html>"

    class _Resp:
        text = html
        def raise_for_status(self): pass

    monkeypatch.setattr("enrichers.google_search.requests.get", lambda *a, **k: _Resp())
    result, page = verify_website("https://acme.ma", "Acme Maroc")

    assert result.coherent is True
    assert isinstance(page, PageFetch)
    assert page.html == html
    assert page.title == "Acme Maroc"
    assert page.unreachable is False
    assert "Acme Maroc" in page.text


def test_an_unreachable_site_yields_an_empty_marked_fetch(monkeypatch):
    def _boom(*a, **k):
        raise requests.exceptions.ConnectionError("dns")

    monkeypatch.setattr("enrichers.google_search.requests.get", _boom)
    result, page = verify_website("https://nope.invalid", "Acme")

    assert result.coherent is True and result.verified is False
    assert page.unreachable is True
    assert page.html == ""


def test_no_url_is_neither_reachable_nor_unreachable():
    result, page = verify_website("", "Acme")
    assert page.unreachable is False
    assert page.html == ""


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


# ── HTML entities (2026-10-02) ────────────────────────────────────────────────

def test_a_numeric_entity_does_not_survive_as_a_token():
    """"SkyCrew &#8211; Fly with us" used to yield a token "8211", which counted
    as a word of the title and inflated the denominator of the overlap ratio."""
    title, text = gs._light_page_text(
        "<html><head><title>SkyCrew &#8211; Fly with us</title></head>"
        "<body><p>Formation &amp; placement d&#39;&eacute;quipages</p></body></html>"
    )
    assert title == "SkyCrew – Fly with us"
    assert "8211" not in title
    assert "8211" not in text
    assert "Formation & placement d'équipages" in text


def test_entities_are_unescaped_after_the_tags_are_stripped():
    """Order matters: unescaping first would turn an escaped tag into a real
    one, which the tag stripper has already run past."""
    _, text = gs._light_page_text(
        "<html><body>Exemple &lt;script&gt;alert(1)&lt;/script&gt; de code "
        "cite dans la page</body></html>"
    )
    assert "<script>alert(1)</script>" in text


# ── Serper titles and snippets (task 10) ─────────────────────────────────────

def _serper_payload(organic):
    class _Resp:
        def raise_for_status(self):
            return None

        def json(self):
            return {"organic": organic}

    return _Resp()


_ORGANIC = [
    {"link": "https://www.linkedin.com/in/amal-b",
     "title": "Amal Benali - Directrice marketing - Acme | LinkedIn",
     "snippet": "Directrice marketing chez Acme depuis juin 2026. "
                "Auparavant responsable acquisition."},
    {"link": "https://www.linkedin.com/posts/amal-b_refonte",
     "title": "Amal Benali on LinkedIn: notre nouveau site",
     "snippet": "Nous venons de livrer la refonte complète du site."},
]


def test_serper_keeps_the_title_and_the_snippet_of_each_result():
    """Only the URL used to survive the call. The title and the snippet of a
    site:linkedin.com/in search are Google's index of the profile and of the
    person's posts — free material on the contact, thrown away on every lead.
    """
    gs._reset_state()
    with patch("enrichers.google_search.config.SERPER_API_KEY", "key"), \
         patch("enrichers.google_search.requests.post",
               return_value=_serper_payload(_ORGANIC)):
        hits = gs._serper_search("Amal Benali Acme site:linkedin.com/in")

    assert [h.link for h in hits] == [r["link"] for r in _ORGANIC]
    assert "Directrice marketing" in hits[0].title
    assert "depuis juin 2026" in hits[0].snippet


def test_a_result_without_a_link_is_still_dropped():
    gs._reset_state()
    with patch("enrichers.google_search.config.SERPER_API_KEY", "key"), \
         patch("enrichers.google_search.requests.post",
               return_value=_serper_payload([{"title": "no link", "snippet": "x"}])):
        assert gs._serper_search("q") == []


def test_person_snippets_keep_the_url_of_every_line():
    """The fact extractor has to source each fact it reports, so it must be
    able to point at the page it read."""
    text = gs.person_snippets([gs.SearchHit(**h) for h in _ORGANIC])
    assert text.count("\n") == 1
    assert "https://www.linkedin.com/in/amal-b" in text
    assert "refonte complète" in text


def test_person_snippets_are_bounded():
    flood = [gs.SearchHit(link="https://x", title="t" * 900, snippet="s" * 900)
             for _ in range(10)]
    assert len(gs.person_snippets(flood)) <= gs.MAX_PERSON_SNIPPET_CHARS


def test_person_snippets_of_an_empty_search_are_empty_not_none():
    assert gs.person_snippets([]) == ""


def test_the_linkedin_search_results_reach_the_lead():
    gs._reset_state()
    lead = {"first_name": "Amal", "last_name": "Benali", "company": "Acme",
            "location": "Casablanca"}
    with patch("enrichers.google_search._serper_search",
               return_value=[gs.SearchHit(**h) for h in _ORGANIC]), \
         patch("enrichers.google_search._ddg_search", return_value=[]), \
         patch("enrichers.google_search._clearbit_domain", return_value=None), \
         patch("enrichers.google_search.time.sleep", return_value=None):
        gs.find_linkedin_and_website(lead)

    assert lead["linkedin_url"] == "https://www.linkedin.com/in/amal-b"
    assert "Directrice marketing" in lead["linkedin_snippets"]


def test_snippets_are_kept_even_when_no_profile_url_could_be_picked():
    """A search returning the person's posts but no /in/ profile still says
    what they do."""
    gs._reset_state()
    posts_only = [gs.SearchHit(link="https://www.linkedin.com/posts/amal-b_refonte",
                               title="Amal Benali on LinkedIn",
                               snippet="Nous venons de livrer la refonte.")]
    lead = {"first_name": "Amal", "last_name": "Benali", "company": "Acme"}
    with patch("enrichers.google_search._serper_search", return_value=posts_only), \
         patch("enrichers.google_search._ddg_search", return_value=[]), \
         patch("enrichers.google_search._clearbit_domain", return_value=None), \
         patch("enrichers.google_search.time.sleep", return_value=None):
        gs.find_linkedin_and_website(lead)

    assert lead["linkedin_url"] is None
    assert "refonte" in lead["linkedin_snippets"]


def test_an_apollo_profile_url_still_costs_no_search():
    """The material is free precisely because it rides on a search we already
    make. A lead whose URL came from Apollo triggers no search, so it gets no
    snippets rather than an extra billed query."""
    gs._reset_state()
    lead = {"first_name": "Amal", "last_name": "Benali", "company": "Acme",
            "linkedin_url": "https://www.linkedin.com/in/amal-b"}
    with patch("enrichers.google_search._serper_search", return_value=[]) as mock_serper, \
         patch("enrichers.google_search._ddg_search", return_value=[]), \
         patch("enrichers.google_search._clearbit_domain", return_value=None), \
         patch("enrichers.google_search.time.sleep", return_value=None):
        gs.find_linkedin_and_website(lead)

    queries = [c.args[0] for c in mock_serper.call_args_list]
    assert not any("linkedin.com/in" in q for q in queries), (
        "no person search must be billed for a profile Apollo already gave us"
    )
    assert lead["linkedin_snippets"] == ""


def test_the_website_search_still_reads_links_only():
    """_pick_website works on URLs; the hits must be unwrapped for it."""
    gs._reset_state()
    hits = [gs.SearchHit(link="https://www.linkedin.com/company/acme", title="t"),
            gs.SearchHit(link="https://acme.ma", title="Acme")]
    with patch("enrichers.google_search.config.SERPER_API_KEY", "key"), \
         patch("enrichers.google_search._clearbit_domain", return_value=None), \
         patch("enrichers.google_search._serper_search", return_value=hits):
        assert gs._find_company_website("Acme", "Casablanca") == "https://acme.ma"
