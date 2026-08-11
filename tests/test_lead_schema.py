from lead_schema import CSV_COLUMNS, ENRICH_FIELDS


def test_columns_are_unique():
    assert len(CSV_COLUMNS) == len(set(CSV_COLUMNS))


def test_enrich_fields_are_all_exported():
    missing = [f for f in ENRICH_FIELDS if f not in CSV_COLUMNS]
    assert missing == []


def test_identity_columns_come_first():
    assert CSV_COLUMNS[:5] == ["first_name", "last_name", "company", "job_title", "location"]


def test_single_source_of_truth_is_used_everywhere():
    import api.pipeline_runner as runner
    import main
    assert main.CSV_COLUMNS is CSV_COLUMNS
    assert runner.CSV_COLUMNS is CSV_COLUMNS


def test_website_check_reason_is_exported():
    """The operator must be able to audit site rejections from the CSV alone."""
    assert "website_check_reason" in CSV_COLUMNS


def test_website_unreachable_is_exported():
    """website_unreachable decides evidence_level (Astrak: cold -> hot on this
    flag alone) but was invisible in the export — the exact failure mode this
    chantier exists to eliminate. It must sit alongside the other three
    site-verification columns.
    """
    assert "website_unreachable" in CSV_COLUMNS
    site_cols = {"website_coherent", "website_rejected", "website_check_reason",
                 "website_unreachable"}
    positions = [CSV_COLUMNS.index(c) for c in site_cols]
    assert max(positions) - min(positions) == len(site_cols) - 1, (
        "site-verification columns must stay contiguous in the export"
    )


def test_website_unreachable_round_trips_through_export_csv(tmp_path, monkeypatch):
    """An enriched lead keeps its real flag; a never-scraped lead reads back
    as missing (None/NaN), not as a stray False that would misreport it as
    'checked and reachable'.
    """
    import pandas as pd

    import config
    import main

    monkeypatch.setattr(config, "OUTPUT_DIR", str(tmp_path))
    leads = [
        {"first_name": "A", "last_name": "B", "company": "Astrak",
         "website": "https://astrakgroup.fr", "website_unreachable": True},
        {"first_name": "C", "last_name": "D", "company": "Acme",
         "website": "https://acme.example", "website_unreachable": False},
        {"first_name": "E", "last_name": "F", "company": "NoHit"},
    ]
    path = main.export_csv(leads, "roundtrip.csv")
    df = pd.read_csv(path)

    assert df.loc[0, "website_unreachable"] == True  # noqa: E712
    assert df.loc[1, "website_unreachable"] == False  # noqa: E712
    assert pd.isna(df.loc[2, "website_unreachable"])


def test_pool_round_trip_keeps_the_scoring_inputs(tmp_path, monkeypatch):
    """create_pool used to drop these, leaving the enrich-only export blank.

    website_coherent also feeds hit_calculator and evidence_level, so losing
    it silently changed the verdict of every pool-based run.
    """
    import api.leads_db as db

    monkeypatch.setattr(db, "_DB_PATH", str(tmp_path / "roundtrip.db"))
    db.init_leads_table()
    pool_id = db.create_pool("test", "url", "job", [
        {"first_name": "A", "last_name": "B", "company": "Acme",
         "email": "a@b.c", "email_status": "valid", "email_confidence": 96,
         "website": None, "website_coherent": False,
         "website_rejected": "https://autre.com",
         "website_check_reason": "Autre SARL ne mentionne pas « Acme »",
         "hit_score": 70, "is_hit": True},
    ])
    lead = db.get_pool_leads(pool_id)[0]
    assert lead["email_status"] == "valid"
    assert lead["email_confidence"] == 96
    assert lead["website_coherent"] is False
    assert lead["website_rejected"] == "https://autre.com"
    assert "Acme" in lead["website_check_reason"]


def test_pool_round_trip_keeps_unchecked_website_as_unknown(tmp_path, monkeypatch):
    """None means "not checked" and must not collapse into False.

    hit_calculator only withholds the website points on an explicit False.
    """
    import api.leads_db as db

    monkeypatch.setattr(db, "_DB_PATH", str(tmp_path / "unknown.db"))
    db.init_leads_table()
    pool_id = db.create_pool("test", "url", "job", [
        {"first_name": "A", "company": "Acme", "website": "https://acme.ma"},
    ])
    assert db.get_pool_leads(pool_id)[0]["website_coherent"] is None


def test_pool_db_created_before_the_new_columns_is_migrated(tmp_path, monkeypatch):
    """CREATE TABLE IF NOT EXISTS leaves an old table untouched."""
    import sqlite3

    import api.leads_db as db

    path = tmp_path / "legacy.db"
    monkeypatch.setattr(db, "_DB_PATH", str(path))
    con = sqlite3.connect(str(path))
    con.execute(
        """CREATE TABLE lead_pool (
               id INTEGER PRIMARY KEY AUTOINCREMENT, pool_id TEXT NOT NULL,
               first_name TEXT, last_name TEXT, company TEXT, job_title TEXT,
               location TEXT, email TEXT, phone TEXT, linkedin_url TEXT,
               website TEXT, hit_score REAL, is_hit INTEGER DEFAULT 0,
               is_duplicate INTEGER DEFAULT 0, first_seen_at TEXT,
               enriched INTEGER DEFAULT 0, enrich_job_id TEXT,
               enriched_at TEXT, enrich_data TEXT)"""
    )
    con.commit()
    con.close()

    db.init_leads_table()
    pool_id = db.create_pool("test", "url", "job", [
        {"first_name": "A", "company": "Acme", "email_status": "accept_all"},
    ])
    assert db.get_pool_leads(pool_id)[0]["email_status"] == "accept_all"


def test_pool_leads_expose_every_enrich_field(tmp_path, monkeypatch):
    import api.leads_db as db

    monkeypatch.setattr(db, "_DB_PATH", str(tmp_path / "t.db"))
    db.init_leads_table()
    pool_id = db.create_pool("test", "url", "job", [
        {"first_name": "A", "last_name": "B", "company": "Acme",
         "email": "a@b.c", "hit_score": 80, "is_hit": True},
    ])
    lead = db.get_pool_leads(pool_id)[0]
    for field in ENRICH_FIELDS:
        assert field in lead, f"{field} missing from pool lead"
