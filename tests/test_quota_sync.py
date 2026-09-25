import pytest

from api import quota_db
from enrichers.providers import quota_sync


@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    monkeypatch.setattr(quota_db, "_DB_PATH", str(tmp_path / "quota.db"))
    quota_db.init_quota_tables()


def test_prospeo_pull_reads_the_nested_response_key():
    """Prospeo nests account data under "response", unlike /enrich-person
    which is flat. Reading the root would silently sync nothing."""
    payload = {
        "error": False,
        "response": {
            "current_plan": "FREE",
            "remaining_credits": 87,
            "used_credits": 13,
            "next_quota_renewal_days": 25,
            "next_quota_renewal_date": "2026-10-18 20:52:28+00:00",
        },
    }
    quota_sync._absorb_prospeo(payload)
    quota = quota_db.get_quota("prospeo")
    assert quota["remaining"] == 87.0
    assert quota["reset_date"] == "2026-10-18"


def test_prospeo_error_payload_is_ignored():
    quota_sync._absorb_prospeo({"error": True, "error_code": "INVALID_API_KEY"})
    assert quota_db.get_quota("prospeo")["remaining"] == 100.0


def test_hunter_pull_prefers_the_unified_credits_bucket():
    """requests.credits is present only on a unified bucket; when it is there
    it is the authoritative balance, not searches/verifications."""
    payload = {
        "data": {
            "plan_name": "Free",
            "reset_date": "2026-10-03",
            "requests": {
                "credits": {"used": 12.5, "available": 50.0, "remaining": 37.5},
                "searches": {"used": 10, "available": 50, "remaining": 40},
                "verifications": {"used": 5, "available": 50, "remaining": 45},
            },
        }
    }
    quota_sync._absorb_hunter(payload)
    assert quota_db.get_quota("hunter")["remaining"] == 37.5


def test_hunter_falls_back_to_searches_when_credits_is_absent():
    """Data Platform plans expose separate buckets and no unified one."""
    payload = {
        "data": {
            "reset_date": "2026-10-03",
            "requests": {
                "searches": {"used": 10, "available": 50, "remaining": 40},
                "verifications": {"used": 5, "available": 100, "remaining": 95},
            },
        }
    }
    quota_sync._absorb_hunter(payload)
    assert quota_db.get_quota("hunter")["remaining"] == 40.0


def test_hunter_fractional_credits_survive():
    payload = {"data": {"reset_date": "2026-10-03",
                        "requests": {"credits": {"used": 0.5, "available": 50.0,
                                                 "remaining": 49.5}}}}
    quota_sync._absorb_hunter(payload)
    assert quota_db.get_quota("hunter")["remaining"] == 49.5


def test_getprospect_piggyback_updates_both_counters():
    """GetProspect has no account endpoint: the balance rides along in
    metadata.credits on every successful response."""
    metadata = {
        "timestamp": "2026-09-25T14:07:55.000Z",
        "credits": {"email_search": 42, "email_verification": 98,
                    "reset_at": "2026-10-01T00:00:00.000Z"},
    }
    quota_sync.absorb_getprospect_metadata(metadata)
    assert quota_db.get_quota("getprospect")["remaining"] == 42.0
    assert quota_db.get_quota("getprospect_verify")["remaining"] == 98.0
    assert quota_db.get_quota("getprospect")["reset_date"] == "2026-10-01"


def test_getprospect_metadata_without_credits_is_a_no_op():
    quota_sync.absorb_getprospect_metadata({"timestamp": "2026-09-25T14:07:55.000Z"})
    assert quota_db.get_quota("getprospect")["remaining"] == 50.0


def test_absorbing_a_malformed_payload_never_raises():
    """A provider that changes its response shape must degrade the sync, not
    kill the run before a single lead is processed."""
    for payload in (None, [], "oops", {"data": None}, {"response": 42}):
        quota_sync._absorb_prospeo(payload)
        quota_sync._absorb_hunter(payload)
        quota_sync.absorb_getprospect_metadata(payload)


def test_sync_all_skips_providers_without_a_key(monkeypatch):
    monkeypatch.setattr("config.PROSPEO_API_KEY", "your_prospeo_api_key_here")
    monkeypatch.setattr("config.HUNTER_API_KEY", "")
    assert quota_sync.sync_all() == {"prospeo": "skipped", "hunter": "skipped"}
