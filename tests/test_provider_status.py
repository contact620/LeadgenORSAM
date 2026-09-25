import pytest

from api.provider_status import (
    ProviderFailure,
    ProviderRegistry,
    StepOutcome,
)


def test_registry_records_and_exports():
    reg = ProviderRegistry()
    reg.record(StepOutcome("hunter", "ok", None, 50))
    assert reg.to_dict()["hunter"]["status"] == "ok"
    assert reg.to_dict()["hunter"]["leads_affected"] == 50


def test_registry_detects_critical_failure(monkeypatch):
    # CRITICAL_PROVIDERS is empty since Dropcontact's removal (Task 3 replaces
    # it with a group-based mechanism); a fake critical provider exercises the
    # has_critical_failure() logic in the interim.
    monkeypatch.setattr("api.provider_status.CRITICAL_PROVIDERS", frozenset({"fake_critical"}))
    reg = ProviderRegistry()
    reg.record(StepOutcome("fake_critical", "failed", "crédits épuisés", 0))
    assert reg.has_critical_failure() is True


def test_degraded_optional_provider_is_not_critical():
    reg = ProviderRegistry()
    reg.record(StepOutcome("perplexity", "degraded", "quota atteint", 12))
    assert reg.has_critical_failure() is False


def test_degraded_critical_provider_flags_the_run(monkeypatch):
    monkeypatch.setattr("api.provider_status.CRITICAL_PROVIDERS", frozenset({"fake_critical"}))
    reg = ProviderRegistry()
    reg.record(StepOutcome("fake_critical", "degraded", "3 lot(s) en échec sur 10", 120))
    assert reg.has_critical_failure() is True


def test_skipped_critical_provider_does_not_flag_the_run(monkeypatch):
    monkeypatch.setattr("api.provider_status.CRITICAL_PROVIDERS", frozenset({"fake_critical"}))
    reg = ProviderRegistry()
    reg.record(StepOutcome("fake_critical", "skipped", "clé API absente", 0))
    assert reg.has_critical_failure() is False


def test_last_record_wins_for_a_provider():
    reg = ProviderRegistry()
    reg.record(StepOutcome("hunter", "ok", None, 10))
    reg.record(StepOutcome("hunter", "degraded", "429", 3))
    assert reg.to_dict()["hunter"]["status"] == "degraded"


def test_provider_failure_carries_context():
    err = ProviderFailure("fake_provider", "HTTP 403")
    assert err.provider == "fake_provider"
    assert "403" in err.reason


def test_dropcontact_is_no_longer_a_provider():
    """Dropcontact must be gone from the codebase entirely."""
    import importlib
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("enrichers.dropcontact")


def test_no_dropcontact_reference_in_config():
    import config
    assert not hasattr(config, "DROPCONTACT_API_KEY")
    assert not hasattr(config, "DROPCONTACT_BATCH_SIZE")
