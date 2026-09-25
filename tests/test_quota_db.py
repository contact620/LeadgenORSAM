from datetime import date

import pytest

from api import quota_db


@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    monkeypatch.setattr(quota_db, "_DB_PATH", str(tmp_path / "quota.db"))
    quota_db.init_quota_tables()


def test_spending_a_billed_result_decrements():
    quota_db.sync_remaining("prospeo", 100.0, "2026-10-01")
    quota_db.record_spend("prospeo", cost=1.0, billed=True)
    assert quota_db.get_quota("prospeo")["remaining"] == 99.0


def test_an_unbilled_result_never_decrements():
    """Prospeo returns free_enrichment=true, GetProspect refunds not_found,
    Hunter charges nothing when no email is found. None of these may cost us
    a unit of local budget, or the counter drifts below the provider's."""
    quota_db.sync_remaining("prospeo", 100.0, "2026-10-01")
    quota_db.record_spend("prospeo", cost=1.0, billed=False)
    assert quota_db.get_quota("prospeo")["remaining"] == 100.0


def test_fractional_cost_is_preserved():
    """Hunter charges 0.5 credit per verification: an integer column would
    silently round every verification to zero or one."""
    quota_db.sync_remaining("hunter", 50.0, "2026-10-01")
    quota_db.record_spend("hunter", cost=0.5, billed=True)
    quota_db.record_spend("hunter", cost=0.5, billed=True)
    assert quota_db.get_quota("hunter")["remaining"] == 49.0


def test_can_spend_is_false_when_remaining_is_below_cost():
    quota_db.sync_remaining("hunter", 0.4, "2026-10-01")
    assert quota_db.can_spend("hunter", cost=0.5) is False
    assert quota_db.can_spend("hunter", cost=0.4) is True


def test_sync_overrides_the_local_counter():
    """The provider is always right: a local counter that drifted must yield."""
    quota_db.sync_remaining("getprospect", 50.0, "2026-10-01")
    quota_db.record_spend("getprospect", cost=1.0, billed=True)
    quota_db.sync_remaining("getprospect", 12.0, "2026-10-01")
    assert quota_db.get_quota("getprospect")["remaining"] == 12.0


def test_reset_restores_the_allocation_plus_capped_rollover():
    """GetProspect carries unused credits forward, capped at one allowance."""
    quota_db.sync_remaining("getprospect", 30.0, "2026-09-01")
    quota_db.apply_monthly_reset("getprospect", today=date(2026, 10, 1))
    quota = quota_db.get_quota("getprospect")
    assert quota["remaining"] == 80.0  # 50 allocation + 30 reportés
    assert quota["reset_date"] == "2026-11-01"


def test_rollover_is_capped_at_one_allowance():
    quota_db.sync_remaining("getprospect", 90.0, "2026-09-01")
    quota_db.apply_monthly_reset("getprospect", today=date(2026, 10, 1))
    assert quota_db.get_quota("getprospect")["remaining"] == 100.0  # 50 + 50 max


def test_provider_without_rollover_starts_from_scratch():
    """Prospeo credits do not carry over."""
    quota_db.sync_remaining("prospeo", 40.0, "2026-09-01")
    quota_db.apply_monthly_reset("prospeo", today=date(2026, 10, 1))
    assert quota_db.get_quota("prospeo")["remaining"] == 100.0


def test_reset_is_a_no_op_before_the_reset_date():
    quota_db.sync_remaining("prospeo", 40.0, "2026-10-01")
    quota_db.apply_monthly_reset("prospeo", today=date(2026, 9, 25))
    assert quota_db.get_quota("prospeo")["remaining"] == 40.0


def test_unknown_provider_reads_its_configured_allocation():
    assert quota_db.get_quota("hunter")["allocation"] == 50.0
