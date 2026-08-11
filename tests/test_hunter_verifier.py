from unittest.mock import patch

import enrichers.hunter_verifier as hv
from api.provider_status import ProviderRegistry
from enrichers.hunter_verifier import enrich_leads_hunter


def _leads(with_email=True):
    return [
        {"first_name": "A", "last_name": "B", "email": "a@b.c" if with_email else None},
        {"first_name": "C", "last_name": "D", "email": "c@d.e" if with_email else None},
    ]


def test_missing_key_is_recorded_as_skipped():
    hv._reset_state()
    reg = ProviderRegistry()
    with patch("enrichers.hunter_verifier.config.HUNTER_API_KEY", ""):
        enrich_leads_hunter(_leads(), registry=reg)
    entry = reg.to_dict()["hunter"]
    assert entry["status"] == "skipped"
    assert "clé" in entry["reason"]


def test_no_email_to_verify_is_recorded_as_skipped():
    hv._reset_state()
    reg = ProviderRegistry()
    with patch("enrichers.hunter_verifier.config.HUNTER_API_KEY", "key"):
        enrich_leads_hunter(_leads(with_email=False), registry=reg)
    entry = reg.to_dict()["hunter"]
    assert entry["status"] == "skipped"
    assert "aucun email" in entry["reason"]


def test_key_rejected_mid_run_is_recorded_as_degraded():
    """A Hunter failure leaves email_status at None, and hit_calculator then
    grants the full 40 points to an unverified email. The inflation has to be
    visible somewhere."""
    hv._reset_state()
    reg = ProviderRegistry()

    def _fail(email):
        hv._hunter_disabled = True
        return None, None

    with patch("enrichers.hunter_verifier.config.HUNTER_API_KEY", "key"), \
         patch("enrichers.hunter_verifier._verify_email", side_effect=_fail), \
         patch("enrichers.hunter_verifier.time.sleep", return_value=None):
        try:
            enrich_leads_hunter(_leads(), registry=reg)
        finally:
            hv._reset_state()

    entry = reg.to_dict()["hunter"]
    assert entry["status"] == "degraded"
    assert entry["reason"]
    assert entry["leads_affected"] == 2


def test_healthy_run_is_recorded_as_ok():
    hv._reset_state()
    reg = ProviderRegistry()
    with patch("enrichers.hunter_verifier.config.HUNTER_API_KEY", "key"), \
         patch("enrichers.hunter_verifier._verify_email", return_value=("valid", 95)), \
         patch("enrichers.hunter_verifier.time.sleep", return_value=None):
        leads = enrich_leads_hunter(_leads(), registry=reg)

    entry = reg.to_dict()["hunter"]
    assert entry["status"] == "ok"
    assert entry["leads_affected"] == 2
    assert all(l["email_status"] == "valid" for l in leads)


def test_registry_stays_optional():
    """main.py and older callers pass no registry."""
    hv._reset_state()
    with patch("enrichers.hunter_verifier.config.HUNTER_API_KEY", ""):
        assert len(enrich_leads_hunter(_leads())) == 2


def test_hunter_is_not_a_critical_provider():
    """A degraded Hunter inflates scores but still produces a usable file:
    it must not abort the run the way Dropcontact does."""
    hv._reset_state()
    reg = ProviderRegistry()

    def _fail(email):
        hv._hunter_disabled = True
        return None, None

    with patch("enrichers.hunter_verifier.config.HUNTER_API_KEY", "key"), \
         patch("enrichers.hunter_verifier._verify_email", side_effect=_fail), \
         patch("enrichers.hunter_verifier.time.sleep", return_value=None):
        try:
            enrich_leads_hunter(_leads(), registry=reg)
        finally:
            hv._reset_state()

    assert reg.has_critical_failure() is False
