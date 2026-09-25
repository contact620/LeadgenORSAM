import pytest

from enrichers import domain_intel


@pytest.fixture(autouse=True)
def clear_caches():
    domain_intel.reset_caches()
    yield
    domain_intel.reset_caches()


def _fake_mx(monkeypatch, hosts):
    class _Rec:
        def __init__(self, host): self.exchange = host
        def __str__(self): return self.exchange

    def _resolve(domain, record_type):
        if hosts is None:
            import dns.resolver
            raise dns.resolver.NoAnswer()
        return [_Rec(h) for h in hosts]

    monkeypatch.setattr(domain_intel.dns.resolver, "resolve", _resolve)


def test_google_workspace_is_detected(monkeypatch):
    _fake_mx(monkeypatch, ["aspmx.l.google.com.", "alt1.aspmx.l.google.com."])
    info = domain_intel.lookup_mx("acme.ma")
    assert info.has_mx is True
    assert info.provider == "google"


def test_microsoft_365_is_detected(monkeypatch):
    _fake_mx(monkeypatch, ["acme-ma.mail.protection.outlook.com."])
    assert domain_intel.lookup_mx("acme.ma").provider == "microsoft"


def test_an_unknown_host_is_autre(monkeypatch):
    _fake_mx(monkeypatch, ["mail.ovh.net."])
    assert domain_intel.lookup_mx("acme.ma").provider == "autre"


def test_a_domain_without_mx_is_flagged(monkeypatch):
    _fake_mx(monkeypatch, None)
    info = domain_intel.lookup_mx("acme.ma")
    assert info.has_mx is False
    assert info.provider is None


def test_mx_result_is_cached_per_domain(monkeypatch):
    calls = []

    class _Rec:
        exchange = "aspmx.l.google.com."
        def __str__(self): return self.exchange

    def _resolve(domain, record_type):
        calls.append(domain)
        return [_Rec()]

    monkeypatch.setattr(domain_intel.dns.resolver, "resolve", _resolve)
    domain_intel.lookup_mx("acme.ma")
    domain_intel.lookup_mx("acme.ma")
    assert len(calls) == 1


# ── Catch-all ─────────────────────────────────────────────────────────────────

def test_a_domain_accepting_a_random_address_is_catch_all():
    probes = []

    def verify(email):
        probes.append(email)
        return "valid"

    assert domain_intel.is_catch_all("acme.ma", verify) is True
    assert probes[0].endswith("@acme.ma")
    assert len(probes) == 1


def test_a_domain_rejecting_a_random_address_is_not_catch_all():
    assert domain_intel.is_catch_all("acme.ma", lambda e: "invalid") is False


def test_an_inconclusive_probe_yields_none():
    """Unknown means we could not tell. Recording it as False would send the
    cascade spending verifications on a domain that answers yes to everything."""
    assert domain_intel.is_catch_all("acme.ma", lambda e: "unknown") is None


def test_the_probe_runs_once_per_domain():
    probes = []

    def verify(email):
        probes.append(email)
        return "valid"

    domain_intel.is_catch_all("acme.ma", verify)
    domain_intel.is_catch_all("acme.ma", verify)
    domain_intel.is_catch_all("acme.ma", verify)
    assert len(probes) == 1, "un domaine se teste une fois, pas une fois par lead"


def test_different_domains_are_probed_separately():
    probes = []
    domain_intel.is_catch_all("acme.ma", lambda e: probes.append(e) or "valid")
    domain_intel.is_catch_all("other.ma", lambda e: probes.append(e) or "valid")
    assert len(probes) == 2


def test_a_verifier_that_raises_never_propagates():
    def boom(email):
        raise RuntimeError("quota")

    assert domain_intel.is_catch_all("acme.ma", boom) is None


def test_the_probe_address_is_random_enough_to_not_exist():
    seen = set()
    for domain in (f"d{i}.ma" for i in range(20)):
        domain_intel.is_catch_all(domain, lambda e: seen.add(e.split("@")[0]) or "invalid")
    assert len(seen) == 20
