import pytest

from api import leads_db, suppression_db


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    path = str(tmp_path / "h.db")
    monkeypatch.setattr(leads_db, "_DB_PATH", path)
    monkeypatch.setattr(suppression_db, "_DB_PATH", path)
    leads_db.init_leads_table()
    suppression_db.init_suppression_table()


def _lead(**over):
    base = {"first_name": "Karim", "last_name": "El Amrani",
            "email": "karim@acme.ma", "linkedin_url": "https://linkedin.com/in/karim",
            "website": "https://acme.ma"}
    base.update(over)
    return base


# ── Clés de dédoublonnage ─────────────────────────────────────────────────────

def test_email_is_the_primary_key():
    assert leads_db.dedupe_key(_lead())[0] == "email"


def test_linkedin_is_the_first_fallback():
    assert leads_db.dedupe_key(_lead(email=None))[0] == "linkedin"


def test_name_plus_domain_is_the_last_fallback():
    """Most leads will now have no email at all: without this the dedupe table
    would report every one of them as new, forever."""
    kind, value = leads_db.dedupe_key(_lead(email=None, linkedin_url=None))
    assert kind == "name_domain"
    assert "acme.ma" in value


def test_a_lead_with_no_identifier_at_all_has_no_key():
    assert leads_db.dedupe_key({"first_name": "", "last_name": ""}) == ("", "")


def test_keys_are_normalized():
    a = leads_db.dedupe_key(_lead(email="  KARIM@ACME.MA "))
    b = leads_db.dedupe_key(_lead(email="karim@acme.ma"))
    assert a == b


def test_distinct_emails_never_collide_on_the_same_key():
    """normalize_name folds punctuation to spaces and dedupe_key used to
    strip those spaces out entirely, so a.b@x.ma and ab@x.ma both collapsed
    to the same "abxma" key — two different people registered as one."""
    a = leads_db.dedupe_key(_lead(email="a.b@x.ma"))
    b = leads_db.dedupe_key(_lead(email="ab@x.ma"))
    assert a != b


def test_a_lead_seen_by_linkedin_is_recognized_on_a_later_run():
    leads_db.register_leads("job-1", [_lead(email=None)])
    known = leads_db.check_duplicates([_lead(email=None)])
    assert leads_db.dedupe_key(_lead(email=None)) in known


def test_a_legacy_known_leads_row_is_backfilled_not_re_inserted():
    """Mirrors test_a_pool_created_before_the_migration_still_loads for
    lead_pool: a known_leads row from before dedupe_kind/dedupe_value existed
    must be backfilled by the migration, not left NULL — otherwise
    check_duplicates() never matches it, register_leads() tries to re-INSERT
    the same email (the table's PRIMARY KEY), and the whole batch's
    registration raises and rolls back silently."""
    with leads_db._conn() as con:
        con.execute("DROP TABLE known_leads")
        con.execute("""CREATE TABLE known_leads (
            email TEXT PRIMARY KEY, first_name TEXT, last_name TEXT, company TEXT,
            first_seen_job_id TEXT, first_seen_at TEXT, seen_count INTEGER DEFAULT 1)""")
        con.execute(
            "INSERT INTO known_leads (email, first_name, last_name, company, "
            "first_seen_job_id, first_seen_at) VALUES "
            "('karim@acme.ma', 'Karim', 'El Amrani', 'Acme', 'job-0', '2026-01-01T00:00:00Z')"
        )

    new_count, dup_count = leads_db.register_leads("job-1", [_lead(email="karim@acme.ma")])
    assert new_count == 0
    assert dup_count == 1

    known = leads_db.check_duplicates([_lead(email="karim@acme.ma")])
    assert leads_db.dedupe_key(_lead(email="karim@acme.ma")) in known


# ── Liste de suppression ──────────────────────────────────────────────────────

def test_a_suppressed_email_is_detected():
    suppression_db.add_entry(email="karim@acme.ma", motif="client existant")
    assert suppression_db.is_suppressed(_lead()) == "client existant"


def test_a_suppressed_linkedin_is_detected():
    suppression_db.add_entry(linkedin_url="https://linkedin.com/in/karim", motif="opt-out")
    assert suppression_db.is_suppressed(_lead(email=None)) == "opt-out"


def test_a_suppressed_domain_covers_every_lead_of_that_company():
    """Blacklisting a client company must cover colleagues we have never seen."""
    suppression_db.add_entry(domaine="acme.ma", motif="client BoxCom")
    assert suppression_db.is_suppressed(_lead(email=None, linkedin_url=None)) == "client BoxCom"
    assert suppression_db.is_suppressed(
        _lead(first_name="Sara", last_name="Bennani", email="sara@acme.ma")
    ) == "client BoxCom"


def test_an_unlisted_lead_is_not_suppressed():
    suppression_db.add_entry(email="autre@ailleurs.ma", motif="opt-out")
    assert suppression_db.is_suppressed(_lead()) is None


def test_matching_is_case_and_space_insensitive():
    suppression_db.add_entry(email="  KARIM@ACME.MA  ", motif="opt-out")
    assert suppression_db.is_suppressed(_lead()) == "opt-out"


# ── Import CSV ────────────────────────────────────────────────────────────────

def test_csv_import_reads_the_documented_columns():
    csv_text = (
        "email,linkedin_url,domaine,motif\n"
        "a@acme.ma,,,client existant\n"
        ",https://linkedin.com/in/b,,opt-out\n"
        ",,concurrent.ma,concurrent\n"
    )
    report = suppression_db.import_csv(csv_text)
    assert report["imported"] == 3
    assert len(suppression_db.list_entries()) == 3


def test_csv_import_skips_rows_with_no_identifier():
    report = suppression_db.import_csv("email,linkedin_url,domaine,motif\n,,,rien\n")
    assert report["imported"] == 0
    assert report["skipped"] == 1


def test_csv_import_is_idempotent():
    csv_text = "email,motif\na@acme.ma,client\n"
    suppression_db.import_csv(csv_text)
    suppression_db.import_csv(csv_text)
    assert len(suppression_db.list_entries()) == 1


def test_a_missing_motif_column_defaults_rather_than_failing():
    report = suppression_db.import_csv("email\na@acme.ma\n")
    assert report["imported"] == 1
