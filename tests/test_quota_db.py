from datetime import date, datetime, timedelta, timezone

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
    body runs. Re-running init_quota_tables() after the monkeypatch lands
    the pinned values onto that existing row: init_quota_tables() re-asserts
    allocation/rollover_cap on conflict (that is the very fix under test),
    so this is the same mechanism a real restart uses, not a test-only
    workaround.
    """
    monkeypatch.setitem(config.PROVIDER_ALLOCATIONS, "getprospect", 50.0)
    monkeypatch.setitem(config.PROVIDER_ROLLOVER_CAP, "getprospect", 1.0)
    quota_db.init_quota_tables()
    quota_db.sync_remaining("getprospect", 30.0, "2026-09-01")
    quota_db.apply_monthly_reset("getprospect", today=date(2026, 10, 1))
    quota = quota_db.get_quota("getprospect")
    assert quota["remaining"] == 80.0  # 50 allowance + 30 carried
    assert quota["reset_date"] == "2026-11-01"


def test_rollover_is_capped_at_one_allowance(monkeypatch):
    monkeypatch.setitem(config.PROVIDER_ALLOCATIONS, "getprospect", 50.0)
    monkeypatch.setitem(config.PROVIDER_ROLLOVER_CAP, "getprospect", 1.0)
    quota_db.init_quota_tables()
    quota_db.sync_remaining("getprospect", 90.0, "2026-09-01")
    quota_db.apply_monthly_reset("getprospect", today=date(2026, 10, 1))
    assert quota_db.get_quota("getprospect")["remaining"] == 100.0  # 50 allowance + 50 max carried


def test_provider_without_rollover_starts_from_scratch(monkeypatch):
    """Prospeo credits do not carry over."""
    monkeypatch.setitem(config.PROVIDER_ALLOCATIONS, "prospeo", 100.0)
    monkeypatch.setitem(config.PROVIDER_ROLLOVER_CAP, "prospeo", 0.0)
    quota_db.init_quota_tables()
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


def test_reinit_after_env_edit_updates_allocation_on_existing_row(monkeypatch):
    """Editing .env and restarting must actually change the stored
    allocation. Before the fix, init_quota_tables() used INSERT OR IGNORE,
    so a row created on the very first start kept its original allocation
    forever — Prospeo publishes no documented free-tier number at all, so
    the operator correcting the guessed default is expected, not an edge
    case."""
    monkeypatch.setitem(config.PROVIDER_ALLOCATIONS, "prospeo", 100.0)
    quota_db.init_quota_tables()
    assert quota_db.get_quota("prospeo")["allocation"] == 100.0

    monkeypatch.setitem(config.PROVIDER_ALLOCATIONS, "prospeo", 5000.0)
    quota_db.init_quota_tables()
    assert quota_db.get_quota("prospeo")["allocation"] == 5000.0


def test_reinit_leaves_remaining_and_consumed_untouched(monkeypatch):
    """allocation and rollover_cap are config-owned and re-asserted on every
    start; remaining and consumed are runtime state and must survive a
    restart untouched, spent credits included."""
    monkeypatch.setitem(config.PROVIDER_ALLOCATIONS, "prospeo", 100.0)
    quota_db.init_quota_tables()
    quota_db.record_spend("prospeo", cost=1.0, billed=True)
    before = quota_db.get_quota("prospeo")

    monkeypatch.setitem(config.PROVIDER_ALLOCATIONS, "prospeo", 5000.0)
    quota_db.init_quota_tables()
    after = quota_db.get_quota("prospeo")

    assert after["remaining"] == before["remaining"]
    assert after["consumed"] == before["consumed"]
    assert after["allocation"] == 5000.0


def test_reinit_updates_rollover_cap_on_existing_row(monkeypatch):
    """rollover_cap is config-owned exactly like allocation, and must follow
    the same re-assert-on-start rule."""
    monkeypatch.setitem(config.PROVIDER_ROLLOVER_CAP, "getprospect", 1.0)
    quota_db.init_quota_tables()
    assert quota_db.get_quota("getprospect")["rollover_cap"] == 1.0

    monkeypatch.setitem(config.PROVIDER_ROLLOVER_CAP, "getprospect", 0.5)
    quota_db.init_quota_tables()
    assert quota_db.get_quota("getprospect")["rollover_cap"] == 0.5


def test_apply_monthly_reset_uses_the_updated_allocation(monkeypatch):
    """The whole point of the fix: apply_monthly_reset must restore to
    whatever allocation is configured now, not whatever it was when the row
    was first created. Raising the allowance must not itself hand out
    credits — remaining stays put until the reset actually fires."""
    monkeypatch.setitem(config.PROVIDER_ALLOCATIONS, "prospeo", 100.0)
    monkeypatch.setitem(config.PROVIDER_ROLLOVER_CAP, "prospeo", 0.0)
    quota_db.init_quota_tables()
    quota_db.sync_remaining("prospeo", 10.0, "2026-09-01")

    monkeypatch.setitem(config.PROVIDER_ALLOCATIONS, "prospeo", 5000.0)
    quota_db.init_quota_tables()
    assert quota_db.get_quota("prospeo")["remaining"] == 10.0  # raising the cap grants nothing yet

    quota_db.apply_monthly_reset("prospeo", today=date(2026, 10, 1))
    assert quota_db.get_quota("prospeo")["remaining"] == 5000.0


def test_a_found_email_is_cached_and_read_back():
    quota_db.cache_store("Karim", "El Amrani", "acme.ma", "prospeo",
                         {"email": "k.elamrani@acme.ma", "status": "valid"})
    hit = quota_db.cache_lookup("Karim", "El Amrani", "acme.ma", "prospeo")
    assert hit["result"]["email"] == "k.elamrani@acme.ma"


def test_a_miss_is_cached_too():
    """A lookup that found nothing cost a call. Repeating it costs another."""
    quota_db.cache_store("Karim", "El Amrani", "acme.ma", "hunter", None)
    hit = quota_db.cache_lookup("Karim", "El Amrani", "acme.ma", "hunter")
    assert hit is not None
    assert hit["result"] is None


def test_names_are_normalized_before_matching():
    quota_db.cache_store("Karim", "El Amrani", "acme.ma", "prospeo",
                         {"email": "k@acme.ma"})
    assert quota_db.cache_lookup("  KARIM ", "el amrani", "ACME.MA", "prospeo") is not None


def test_accents_are_folded():
    quota_db.cache_store("Aïcha", "Benîtez", "acme.ma", "prospeo", {"email": "a@acme.ma"})
    assert quota_db.cache_lookup("Aicha", "Benitez", "acme.ma", "prospeo") is not None


def test_cache_is_scoped_per_provider():
    """Prospeo finding nothing says nothing about what Hunter would find."""
    quota_db.cache_store("Karim", "El Amrani", "acme.ma", "prospeo", None)
    assert quota_db.cache_lookup("Karim", "El Amrani", "acme.ma", "hunter") is None


def test_an_entry_older_than_ninety_days_is_a_miss():
    """Prospeo re-bills after 90 days, so our cache must re-ask at 90 days too."""
    quota_db.cache_store("Karim", "El Amrani", "acme.ma", "prospeo", {"email": "k@acme.ma"})
    stale = (datetime.now(timezone.utc) - timedelta(days=91)).isoformat()
    with quota_db._conn() as con:
        con.execute("UPDATE email_lookup_cache SET looked_up_at = ?", (stale,))
    assert quota_db.cache_lookup("Karim", "El Amrani", "acme.ma", "prospeo") is None


def test_an_entry_at_eighty_nine_days_is_still_a_hit():
    quota_db.cache_store("Karim", "El Amrani", "acme.ma", "prospeo", {"email": "k@acme.ma"})
    fresh = (datetime.now(timezone.utc) - timedelta(days=89)).isoformat()
    with quota_db._conn() as con:
        con.execute("UPDATE email_lookup_cache SET looked_up_at = ?", (fresh,))
    assert quota_db.cache_lookup("Karim", "El Amrani", "acme.ma", "prospeo") is not None


def test_storing_twice_replaces_rather_than_duplicates():
    quota_db.cache_store("Karim", "El Amrani", "acme.ma", "prospeo", None)
    quota_db.cache_store("Karim", "El Amrani", "acme.ma", "prospeo", {"email": "k@acme.ma"})
    hit = quota_db.cache_lookup("Karim", "El Amrani", "acme.ma", "prospeo")
    assert hit["result"]["email"] == "k@acme.ma"
