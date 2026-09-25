import pytest

from api.provider_status import (
    ProviderFailure,
    ProviderRegistry,
    StepOutcome,
    PROVIDER_GROUPS,
)


def test_registry_records_and_exports():
    reg = ProviderRegistry()
    reg.record(StepOutcome("hunter", "ok", None, 50))
    assert reg.to_dict()["hunter"]["status"] == "ok"
    assert reg.to_dict()["hunter"]["leads_affected"] == 50


def test_registry_detects_critical_failure():
    # A critical group that has all members failed triggers has_critical_failure().
    reg = ProviderRegistry()
    for name in PROVIDER_GROUPS["email"]:
        reg.record(StepOutcome(name, "failed", "crédits épuisés", 0))
    assert reg.has_critical_failure() is True


def test_degraded_optional_provider_is_not_critical():
    reg = ProviderRegistry()
    reg.record(StepOutcome("perplexity", "degraded", "quota atteint", 12))
    assert reg.has_critical_failure() is False


def test_degraded_critical_provider_does_not_flag_the_run():
    # One member of a critical group being degraded does not trigger has_critical_failure()
    # because the group is still partially functional (other members are not down).
    reg = ProviderRegistry()
    members = sorted(PROVIDER_GROUPS["email"])
    reg.record(StepOutcome(members[0], "degraded", "3 lot(s) en échec sur 10", 120))
    for name in members[1:]:
        reg.record(StepOutcome(name, "ok", None, 5))
    assert reg.has_critical_failure() is False


def test_skipped_critical_provider_does_not_flag_the_run():
    # One member of a critical group being skipped does not trigger has_critical_failure()
    # when at least one other member is operational.
    reg = ProviderRegistry()
    members = sorted(PROVIDER_GROUPS["email"])
    reg.record(StepOutcome(members[0], "skipped", "clé API absente", 0))
    for name in members[1:]:
        reg.record(StepOutcome(name, "ok", None, 5))
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


def test_email_group_is_ok_when_every_member_answers():
    registry = ProviderRegistry()
    for name in PROVIDER_GROUPS["email"]:
        registry.record(StepOutcome(name, "ok", None, 5))
    assert registry.group_status("email") == "ok"


def test_email_group_is_degraded_when_one_member_fails():
    registry = ProviderRegistry()
    members = sorted(PROVIDER_GROUPS["email"])
    registry.record(StepOutcome(members[0], "failed", "clé rejetée", 3))
    for name in members[1:]:
        registry.record(StepOutcome(name, "ok", None, 5))
    assert registry.group_status("email") == "degraded"
    assert registry.has_critical_failure() is False


def test_email_group_fails_only_when_every_member_is_down():
    registry = ProviderRegistry()
    for name in PROVIDER_GROUPS["email"]:
        registry.record(StepOutcome(name, "failed", "quota épuisé", 10))
    assert registry.group_status("email") == "failed"
    assert registry.has_critical_failure() is True


def test_a_skipped_member_does_not_count_as_a_failure():
    """An operator who never configured GetProspect has not suffered an outage."""
    registry = ProviderRegistry()
    members = sorted(PROVIDER_GROUPS["email"])
    registry.record(StepOutcome(members[0], "skipped", "clé API absente", 0))
    for name in members[1:]:
        registry.record(StepOutcome(name, "ok", None, 5))
    assert registry.group_status("email") == "ok"


def test_group_status_is_skipped_when_no_member_was_configured():
    registry = ProviderRegistry()
    for name in PROVIDER_GROUPS["email"]:
        registry.record(StepOutcome(name, "skipped", "clé API absente", 0))
    assert registry.group_status("email") == "skipped"
    assert registry.has_critical_failure() is False


def test_unreported_members_are_ignored():
    """A provider the run never reached says nothing about the group's health."""
    registry = ProviderRegistry()
    registry.record(StepOutcome("prospeo", "ok", None, 2))
    assert registry.group_status("email") == "ok"


def test_impaired_groups_lists_only_what_is_worth_reporting():
    registry = ProviderRegistry()
    members = sorted(PROVIDER_GROUPS["email"])
    registry.record(StepOutcome(members[0], "degraded", "quota épuisé", 4))
    for name in members[1:]:
        registry.record(StepOutcome(name, "ok", None, 5))
    assert registry.impaired_groups() == {"email": "degraded"}


def test_one_member_degraded_others_unreported_is_degraded_not_failed():
    """The cascade stops at first success: unreported members are normal, not
    an anomaly. A single degraded report must not flip the group to failed."""
    registry = ProviderRegistry()
    registry.record(StepOutcome("prospeo", "degraded", "quota épuisé", 5))
    assert registry.group_status("email") == "degraded"
    assert registry.has_critical_failure() is False


def test_one_member_failed_others_unreported_is_degraded_not_failed():
    """Even with one member completely failed, the group is degraded (not
    failed) until all members have been tried and failed."""
    registry = ProviderRegistry()
    registry.record(StepOutcome("prospeo", "failed", "clé rejetée", 5))
    assert registry.group_status("email") == "degraded"
    assert registry.has_critical_failure() is False


def test_all_three_members_recorded_as_failed_is_failed():
    """The group is failed only when every member has reported and all are down."""
    registry = ProviderRegistry()
    for name in PROVIDER_GROUPS["email"]:
        registry.record(StepOutcome(name, "failed", "quota épuisé", 10))
    assert registry.group_status("email") == "failed"
    assert registry.has_critical_failure() is True


def test_two_members_failed_one_skipped_is_failed():
    """A skipped member counts as 'heard from' but is excluded from the
    active verdict. If all active members are down, the group is failed."""
    registry = ProviderRegistry()
    members = sorted(PROVIDER_GROUPS["email"])
    registry.record(StepOutcome(members[0], "failed", "clé rejetée", 10))
    registry.record(StepOutcome(members[1], "failed", "clé rejetée", 10))
    registry.record(StepOutcome(members[2], "skipped", "clé API absente", 0))
    assert registry.group_status("email") == "failed"
    assert registry.has_critical_failure() is True


def test_group_status_unknown_group_returns_skipped():
    """Calling group_status on a group not in PROVIDER_GROUPS returns skipped."""
    registry = ProviderRegistry()
    assert registry.group_status("nonexistent") == "skipped"


def test_group_status_empty_registry_returns_skipped():
    """Calling group_status with no recorded outcomes returns skipped."""
    registry = ProviderRegistry()
    assert registry.group_status("email") == "skipped"
    assert registry.has_critical_failure() is False
