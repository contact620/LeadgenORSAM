from datetime import date

import pytest

import config
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


def test_reset_restores_the_allocation_plus_capped_rollover(monkeypatch):
    """GetProspect carries unused credits forward, capped at one allowance.

    The allocation/cap are pinned here rather than read off whatever an
    operator's .env happens to set, because the autouse fixture already
    seeded provider_quota with the ambient config default before this test
    body runs. sync_remaining's ON CONFLICT branch never rewrites the
    allocation/rollover_cap columns of an existing row, so patching the
    config dict alone would not reach them — the row is deleted first so
    the next sync_remaining call re-inserts it under the patched values.
    """
    monkeypatch.setitem(config.PROVIDER_ALLOCATIONS, "getprospect", 50.0)
    monkeypatch.setitem(config.PROVIDER_ROLLOVER_CAP, "getprospect", 1.0)
    with quota_db._conn() as con:
        con.execute("DELETE FROM provider_quota WHERE provider = ?", ("getprospect",))
    quota_db.sync_remaining("getprospect", 30.0, "2026-09-01")
    quota_db.apply_monthly_reset("getprospect", today=date(2026, 10, 1))
    quota = quota_db.get_quota("getprospect")
    assert quota["remaining"] == 80.0  # 50 allowance + 30 carried
    assert quota["reset_date"] == "2026-11-01"


def test_rollover_is_capped_at_one_allowance(monkeypatch):
    monkeypatch.setitem(config.PROVIDER_ALLOCATIONS, "getprospect", 50.0)
    monkeypatch.setitem(config.PROVIDER_ROLLOVER_CAP, "getprospect", 1.0)
    with quota_db._conn() as con:
        con.execute("DELETE FROM provider_quota WHERE provider = ?", ("getprospect",))
    quota_db.sync_remaining("getprospect", 90.0, "2026-09-01")
    quota_db.apply_monthly_reset("getprospect", today=date(2026, 10, 1))
    assert quota_db.get_quota("getprospect")["remaining"] == 100.0  # 50 allowance + 50 max carried


def test_provider_without_rollover_starts_from_scratch(monkeypatch):
    """Prospeo credits do not carry over."""
    monkeypatch.setitem(config.PROVIDER_ALLOCATIONS, "prospeo", 100.0)
    monkeypatch.setitem(config.PROVIDER_ROLLOVER_CAP, "prospeo", 0.0)
    with quota_db._conn() as con:
        con.execute("DELETE FROM provider_quota WHERE provider = ?", ("prospeo",))
    quota_db.sync_remaining("prospeo", 40.0, "2026-09-01")
    quota_db.apply_monthly_reset("prospeo", today=date(2026, 10, 1))
    assert quota_db.get_quota("prospeo")["remaining"] == 100.0


def test_reset_is_a_no_op_before_the_reset_date():
    quota_db.sync_remaining("prospeo", 40.0, "2026-10-01")
    quota_db.apply_monthly_reset("prospeo", today=date(2026, 9, 25))
    assert quota_db.get_quota("prospeo")["remaining"] == 40.0


def test_unknown_provider_reads_its_configured_allocation():
    assert quota_db.get_quota("hunter")["allocation"] == 50.0


def test_get_quota_for_a_provider_absent_from_the_table_does_not_raise():
    """A provider with no row (never configured, never synced) must return
    the same seven-key shape as a row that exists, not a partial dict that
    raises KeyError the moment a caller reads e.g. synced_at."""
    quota = quota_db.get_quota("inconnu")
    assert quota == {
        "provider": "inconnu",
        "allocation": 0.0,
        "consumed": 0.0,
        "remaining": 0.0,
        "reset_date": None,
        "rollover_cap": 0.0,
        "synced_at": None,
    }
