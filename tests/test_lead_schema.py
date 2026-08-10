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
