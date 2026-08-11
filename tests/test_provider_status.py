import pytest

from api.provider_status import (
    ProviderFailure,
    ProviderRegistry,
    StepOutcome,
)


def test_registry_records_and_exports():
    reg = ProviderRegistry()
    reg.record(StepOutcome("dropcontact", "ok", None, 50))
    assert reg.to_dict()["dropcontact"]["status"] == "ok"
    assert reg.to_dict()["dropcontact"]["leads_affected"] == 50


def test_registry_detects_critical_failure():
    reg = ProviderRegistry()
    reg.record(StepOutcome("dropcontact", "failed", "crédits épuisés", 0))
    assert reg.has_critical_failure() is True


def test_degraded_optional_provider_is_not_critical():
    reg = ProviderRegistry()
    reg.record(StepOutcome("perplexity", "degraded", "quota atteint", 12))
    assert reg.has_critical_failure() is False


def test_degraded_critical_provider_flags_the_run():
    reg = ProviderRegistry()
    reg.record(StepOutcome("dropcontact", "degraded", "3 lot(s) en échec sur 10", 120))
    assert reg.has_critical_failure() is True


def test_skipped_critical_provider_does_not_flag_the_run():
    reg = ProviderRegistry()
    reg.record(StepOutcome("dropcontact", "skipped", "clé API absente", 0))
    assert reg.has_critical_failure() is False


def test_last_record_wins_for_a_provider():
    reg = ProviderRegistry()
    reg.record(StepOutcome("hunter", "ok", None, 10))
    reg.record(StepOutcome("hunter", "degraded", "429", 3))
    assert reg.to_dict()["hunter"]["status"] == "degraded"


def test_provider_failure_carries_context():
    err = ProviderFailure("dropcontact", "HTTP 403")
    assert err.provider == "dropcontact"
    assert "403" in err.reason
