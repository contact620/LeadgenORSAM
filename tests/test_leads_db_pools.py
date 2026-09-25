import pytest

from api import leads_db


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(leads_db, "_DB_PATH", str(tmp_path / "h.db"))
    leads_db.init_leads_table()


def _lead(**over):
    base = {"first_name": "Karim", "last_name": "El Amrani", "company": "Acme",
            "website": "https://acme.ma", "email": "k@acme.ma",
            "email_status": "valid_nominatif", "email_source": "website",
            "prescore": 50, "reachable": True, "contact_level": "direct",
            "whatsapp": False, "domain_catch_all": False}
    base.update(over)
    return base


def test_new_columns_survive_a_round_trip():
    pool_id = leads_db.create_pool("P", "url", "job-1", [_lead(
        email_source="prospeo", email_type="nominatif_lead", phone_type="mobile",
        whatsapp=True, domain_mx_provider="google", domain_mismatch=False,
        prescore=73, contact_source_url="https://acme.ma/contact",
    )])
    stored = leads_db.get_pool_leads(pool_id)[0]
    assert stored["email_source"] == "prospeo"
    assert stored["phone_type"] == "mobile"
    assert stored["whatsapp"] is True
    assert stored["domain_mx_provider"] == "google"
    assert stored["prescore"] == 73
    assert stored["contact_source_url"] == "https://acme.ma/contact"


def test_a_pool_created_before_the_migration_still_loads(monkeypatch):
    """Pools predating this refactor must keep opening: missing columns come
    back as None, never as an exception."""
    with leads_db._conn() as con:
        con.execute("DROP TABLE lead_pool")
        con.execute("""CREATE TABLE lead_pool (
            id INTEGER PRIMARY KEY AUTOINCREMENT, pool_id TEXT NOT NULL,
            first_name TEXT, last_name TEXT, company TEXT, hit_score REAL,
            is_hit INTEGER DEFAULT 0, enriched INTEGER DEFAULT 0)""")
        con.execute("INSERT INTO lead_pool (pool_id, first_name) VALUES ('old', 'Ancien')")
    rows = leads_db.get_pool_leads("old")
    assert rows[0]["first_name"] == "Ancien"
    assert rows[0]["prescore"] is None
    assert rows[0]["email_source"] is None


def test_selection_is_ordered_by_prescore_descending():
    pool_id = leads_db.create_pool("P", "url", "job-1", [
        _lead(company="Faible", prescore=10),
        _lead(company="Fort", prescore=90),
        _lead(company="Moyen", prescore=50),
    ])
    assert [l["company"] for l in leads_db.get_pool_leads(pool_id)] == \
        ["Fort", "Moyen", "Faible"]


def test_pending_quota_leads_come_first_after_a_reset():
    """§10: they were never asked the question — they get the next batch."""
    pool_id = leads_db.create_pool("P", "url", "job-1", [
        _lead(company="Fort", prescore=90, email_status="valid_nominatif"),
        _lead(company="EnAttente", prescore=20, email_status="pending_quota"),
    ])
    batch = leads_db.get_pool_leads(pool_id, only_unenriched=True, limit=2)
    assert batch[0]["company"] == "EnAttente"


def test_only_reachable_filters_out_the_unreachable_but_keeps_pending():
    pool_id = leads_db.create_pool("P", "url", "job-1", [
        _lead(company="Joignable", reachable=True),
        _lead(company="Non", reachable=False, email=None, email_status="not_found"),
        _lead(company="Attente", reachable=None, email_status="pending_quota"),
    ])
    names = {l["company"] for l in leads_db.get_pool_leads(pool_id, only_reachable=True)}
    assert names == {"Joignable", "Attente"}


def test_pending_quota_are_counted():
    pool_id = leads_db.create_pool("P", "url", "job-1", [
        _lead(email_status="pending_quota"), _lead(email_status="valid_nominatif"),
    ])
    assert leads_db.count_pending_quota(pool_id) == 1
