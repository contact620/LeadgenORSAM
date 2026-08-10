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
