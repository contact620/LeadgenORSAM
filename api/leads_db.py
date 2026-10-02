"""
SQLite persistence for lead deduplication + lead pool storage.
Tracks all leads seen across pipeline runs and stores scraped lead pools.
"""
import json
import os
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urlparse

import config as pipeline_config
from api.quota_db import normalize_name
from lead_schema import ENRICH_FIELDS

_DB_PATH = os.path.join(pipeline_config.OUTPUT_DIR, "history.db")

_CREATE_KNOWN_LEADS = """
CREATE TABLE IF NOT EXISTS known_leads (
    email        TEXT PRIMARY KEY,
    first_name   TEXT,
    last_name    TEXT,
    company      TEXT,
    first_seen_job_id TEXT,
    first_seen_at TEXT,
    seen_count   INTEGER DEFAULT 1
)
"""

_CREATE_LEAD_POOL = """
CREATE TABLE IF NOT EXISTS lead_pool (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    pool_id      TEXT NOT NULL,
    first_name   TEXT,
    last_name    TEXT,
    company      TEXT,
    job_title    TEXT,
    location     TEXT,
    email        TEXT,
    phone        TEXT,
    linkedin_url TEXT,
    website      TEXT,
    website_coherent INTEGER,
    website_rejected TEXT,
    website_check_reason TEXT,
    email_status TEXT,
    email_confidence INTEGER,
    hit_score    REAL,
    is_hit       INTEGER DEFAULT 0,
    is_duplicate INTEGER DEFAULT 0,
    first_seen_at TEXT,
    enriched     INTEGER DEFAULT 0,
    enrich_job_id TEXT,
    enriched_at  TEXT,
    enrich_data  TEXT
)
"""

# Columns added after the first pools were created. Scoring and export read
# them, so a pool stored without them exports empty cells for the whole
# enrich-only flow.
_LEAD_POOL_ADDED_COLUMNS = {
    "website_coherent": "INTEGER",
    "website_rejected": "TEXT",
    "website_check_reason": "TEXT",
    "email_status": "TEXT",
    "email_confidence": "INTEGER",
    # ── 2026-09-25 free-cascade rework ──────────────────────────────────────
    # CREATE TABLE IF NOT EXISTS leaves an existing table untouched, so a pool
    # created before this date would silently drop every one of these on
    # insert.
    "email_source": "TEXT",
    "email_type": "TEXT",
    "contact_source_url": "TEXT",
    "domain_catch_all": "INTEGER",
    "domain_mx_provider": "TEXT",
    "domain_mismatch": "INTEGER",
    "phone_type": "TEXT",
    "phone_source": "TEXT",
    "whatsapp": "INTEGER",
    "facebook_url": "TEXT",
    "instagram_url": "TEXT",
    "linkedin_company_url": "TEXT",
    "prescore": "REAL",
    "reachable": "INTEGER",
    "contact_level": "TEXT",
    # ── 2026-10-02 input integrity ──────────────────────────────────────────
    # The two Apollo cells the prescore reads, plus the flag raised when the
    # contact row holds a company rather than a person. Without them here,
    # the enrich-only flow exports three empty columns and the operator is
    # back to not knowing whether a prescore of 0 means "poor fit" or
    # "Apollo never showed the column".
    "apollo_industry": "TEXT",
    "employee_count": "INTEGER",
    "name_looks_like_company": "INTEGER",
}

_CREATE_POOL_META = """
CREATE TABLE IF NOT EXISTS pool_meta (
    pool_id      TEXT PRIMARY KEY,
    name         TEXT NOT NULL,
    apollo_url   TEXT,
    created_at   TEXT NOT NULL,
    scrape_job_id TEXT,
    total_leads  INTEGER DEFAULT 0,
    hit_leads    INTEGER DEFAULT 0,
    enriched_leads INTEGER DEFAULT 0
)
"""


def _conn() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(_DB_PATH), exist_ok=True)
    con = sqlite3.connect(_DB_PATH, timeout=5)
    con.row_factory = sqlite3.Row
    return con


def init_leads_table() -> None:
    with _conn() as con:
        con.execute(_CREATE_KNOWN_LEADS)
        con.execute(_CREATE_LEAD_POOL)
        con.execute(_CREATE_POOL_META)
        _migrate_lead_pool(con)
        _migrate_known_leads(con)


def _migrate_known_leads(con: sqlite3.Connection) -> None:
    """Add the dedupe_kind/dedupe_value columns introduced by the 2026-09-25
    free cascade. Most leads it produces have no email at all, so email alone
    can no longer be the dedup key — see dedupe_key()."""
    existing = {row["name"] for row in con.execute("PRAGMA table_info(known_leads)")}
    if not existing:
        return  # table not created yet — init_leads_table() will create it complete
    for column in ("dedupe_kind", "dedupe_value"):
        if column not in existing:
            con.execute(f"ALTER TABLE known_leads ADD COLUMN {column} TEXT")
    # Backfill, not just add: a row from before this migration has
    # dedupe_kind/dedupe_value left NULL, so check_duplicates() never matches
    # it and register_leads() re-INSERTs the same email — the table's
    # PRIMARY KEY — which raises and rolls back the whole batch's
    # registration inside the caller's best-effort try/except, silently.
    # Idempotent: only rows still NULL are touched, so a repeat call is a
    # no-op once every row has been backfilled.
    con.execute(
        "UPDATE known_leads SET dedupe_kind = 'email', dedupe_value = LOWER(TRIM(email)) "
        "WHERE dedupe_kind IS NULL AND email IS NOT NULL"
    )


def _migrate_lead_pool(con: sqlite3.Connection) -> None:
    """Add columns introduced after a pool DB was first created.

    CREATE TABLE IF NOT EXISTS leaves an existing table untouched, so a DB
    from before these columns existed would keep silently dropping the
    values on insert.
    """
    existing = {row["name"] for row in con.execute("PRAGMA table_info(lead_pool)")}
    if not existing:
        return  # table not created yet — init_leads_table() will create it complete
    for column, sql_type in _LEAD_POOL_ADDED_COLUMNS.items():
        if column not in existing:
            con.execute(f"ALTER TABLE lead_pool ADD COLUMN {column} {sql_type}")


# ── Deduplication ─────────────────────────────────────────────────────────────

def dedupe_key(lead: dict) -> tuple[str, str]:
    """Identify a lead across runs, degrading through three fallbacks.

    Email first, as before. But the free cascade leaves many leads without one,
    and a key that is absent for most rows identifies nothing: every run would
    re-report the same people as new. LinkedIn comes next, then the weakest but
    always-available pair of name and company domain.
    """
    # normalize_name folds every run of non-alphanumeric characters (including
    # "@" and ".") to a single space and replace(" ", "") then removes them,
    # so "a.b@x.ma" and "ab@x.ma" both collapsed to "abxma" — the same
    # collision the domain-cache key already had to avoid. An email's
    # identity is exactly its characters, not a fuzzy name match.
    email = (lead.get("email") or "").strip().lower()
    if email:
        return ("email", email)

    linkedin = (lead.get("linkedin_url") or "").strip().lower().split("?")[0].rstrip("/")
    if linkedin:
        return ("linkedin", linkedin)

    first = normalize_name(lead.get("first_name") or "").replace(" ", "")
    last = normalize_name(lead.get("last_name") or "").replace(" ", "")
    domain = urlparse(lead.get("website") or "").netloc.lower().removeprefix("www.")
    if first and last and domain:
        return ("name_domain", f"{first}.{last}@{domain}")

    return ("", "")


def check_duplicates(leads: list[dict]) -> dict[tuple, dict]:
    """Look up each lead's dedupe_key() in known_leads. Keyed by (kind, value)
    rather than by email, since most leads coming out of the free cascade
    never had one (see dedupe_key)."""
    keys = [dedupe_key(lead) for lead in leads]
    keys = [k for k in keys if k != ("", "")]
    if not keys:
        return {}
    result: dict[tuple, dict] = {}
    with _conn() as con:
        _migrate_known_leads(con)
        placeholders = " OR ".join("(dedupe_kind = ? AND dedupe_value = ?)" for _ in keys)
        params = [value for key in keys for value in key]
        rows = con.execute(
            f"""SELECT dedupe_kind, dedupe_value, first_seen_at, seen_count
                FROM known_leads WHERE {placeholders}""",
            params,
        ).fetchall()
        for row in rows:
            result[(row["dedupe_kind"], row["dedupe_value"])] = {
                "first_seen_at": row["first_seen_at"], "seen_count": row["seen_count"],
            }
    return result


def register_leads(job_id: str, leads: list[dict]) -> tuple[int, int]:
    now = datetime.now(timezone.utc).isoformat()
    new_count = 0
    dup_count = 0
    with _conn() as con:
        _migrate_known_leads(con)
        for lead in leads:
            kind, value = dedupe_key(lead)
            if not kind:
                continue
            existing = con.execute(
                "SELECT seen_count FROM known_leads WHERE dedupe_kind = ? AND dedupe_value = ?",
                (kind, value),
            ).fetchone()
            if existing:
                con.execute(
                    "UPDATE known_leads SET seen_count = seen_count + 1 "
                    "WHERE dedupe_kind = ? AND dedupe_value = ?",
                    (kind, value),
                )
                dup_count += 1
            else:
                con.execute(
                    """INSERT INTO known_leads
                       (email, first_name, last_name, company, first_seen_job_id,
                        first_seen_at, dedupe_kind, dedupe_value)
                       VALUES (?,?,?,?,?,?,?,?)""",
                    ((lead.get("email") or "").strip().lower() or None,
                     lead.get("first_name"), lead.get("last_name"), lead.get("company"),
                     job_id, now, kind, value),
                )
                new_count += 1
    return new_count, dup_count


def get_known_count() -> int:
    with _conn() as con:
        row = con.execute("SELECT COUNT(*) as cnt FROM known_leads").fetchone()
    return row["cnt"] if row else 0


# ── Lead Pool ────────────────────────────────────────────────────────────────

def create_pool(name: str, apollo_url: str, scrape_job_id: str, leads: list[dict]) -> str:
    """Store scraped leads in a pool. Returns pool_id."""
    pool_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    total = len(leads)
    # is_hit no longer exists (reachability replaced the hit score on
    # 2026-09-25) — nothing sets it any more, so summing it always produced 0
    # and made the paid-enrich panel in LeadPools.tsx believe every pool was
    # already fully enriched. hit_leads now just mirrors total_leads.
    hit_count = total

    with _conn() as con:
        _migrate_lead_pool(con)
        con.execute(
            "INSERT INTO pool_meta (pool_id, name, apollo_url, created_at, scrape_job_id, total_leads, hit_leads) VALUES (?,?,?,?,?,?,?)",
            (pool_id, name, apollo_url, now, scrape_job_id, total, hit_count),
        )
        for lead in leads:

            def _bool_or_none(field: str) -> Optional[int]:
                # None stays None: "not checked"/"undetermined" and "checked,
                # false" are different states and reachability distinguishes
                # them (a pending_quota lead is reachable=None, not False).
                value = lead.get(field)
                return None if value is None else int(bool(value))

            con.execute(
                """INSERT INTO lead_pool
                   (pool_id, first_name, last_name, company, job_title, location,
                    email, phone, linkedin_url, website,
                    website_coherent, website_rejected, website_check_reason,
                    email_status, email_confidence,
                    email_source, email_type, contact_source_url,
                    domain_catch_all, domain_mx_provider, domain_mismatch,
                    phone_type, phone_source, whatsapp,
                    facebook_url, instagram_url, linkedin_company_url,
                    prescore, apollo_industry, employee_count,
                    name_looks_like_company, reachable, contact_level,
                    hit_score, is_hit, is_duplicate, first_seen_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (pool_id, lead.get("first_name"), lead.get("last_name"),
                 lead.get("company"), lead.get("job_title"), lead.get("location"),
                 lead.get("email"), lead.get("phone"), lead.get("linkedin_url"), lead.get("website"),
                 _bool_or_none("website_coherent"),
                 lead.get("website_rejected"), lead.get("website_check_reason"),
                 lead.get("email_status"), lead.get("email_confidence"),
                 lead.get("email_source"), lead.get("email_type"), lead.get("contact_source_url"),
                 _bool_or_none("domain_catch_all"), lead.get("domain_mx_provider"),
                 _bool_or_none("domain_mismatch"),
                 lead.get("phone_type"), lead.get("phone_source"), _bool_or_none("whatsapp"),
                 lead.get("facebook_url"), lead.get("instagram_url"), lead.get("linkedin_company_url"),
                 lead.get("prescore"), lead.get("apollo_industry"),
                 lead.get("employee_count"), _bool_or_none("name_looks_like_company"),
                 _bool_or_none("reachable"), lead.get("contact_level"),
                 lead.get("hit_score", 0), int(lead.get("is_hit", False)),
                 int(lead.get("is_duplicate", False)), lead.get("first_seen_at")),
            )
    return pool_id


def list_pools() -> list[dict]:
    with _conn() as con:
        rows = con.execute("SELECT * FROM pool_meta ORDER BY created_at DESC").fetchall()
    return [dict(r) for r in rows]


def get_pool(pool_id: str) -> Optional[dict]:
    with _conn() as con:
        row = con.execute("SELECT * FROM pool_meta WHERE pool_id = ?", (pool_id,)).fetchone()
    return dict(row) if row else None


def get_pool_leads(pool_id: str, only_reachable: bool = False,
                   only_unenriched: bool = False, limit: int = 0,
                   order_by: str = "prescore") -> list[dict]:
    """Read leads from a pool, ordered for spending.

    pending_quota leads sort first: they never got their question asked, and
    the monthly reset is precisely when they should. Everything else follows
    by prescore descending — the free relevance estimate that decides where
    the month's credits go (see processors/prescore.py).
    """
    query = "SELECT * FROM lead_pool WHERE pool_id = ?"
    params: list = [pool_id]

    if only_reachable:
        # reachable IS NULL is pending_quota: undetermined, never excluded.
        query += " AND (reachable = 1 OR reachable IS NULL)"
    if only_unenriched:
        query += " AND enriched = 0"

    query += (" ORDER BY CASE WHEN email_status = 'pending_quota' THEN 0 ELSE 1 END, "
              "COALESCE(prescore, 0) DESC, id ASC")
    if limit > 0:
        query += " LIMIT ?"
        params.append(limit)

    with _conn() as con:
        _migrate_lead_pool(con)
        rows = con.execute(query, params).fetchall()

    def _bool_or_none(value):
        return None if value is None else bool(value)

    result = []
    for r in rows:
        d = dict(r)
        # .get(), not [] : a pool table predating even the base schema (no
        # is_duplicate column at all, as opposed to merely NULL) must still
        # load rather than raising KeyError on these flag columns.
        d["is_hit"] = bool(d.get("is_hit") or 0)
        d["is_duplicate"] = bool(d.get("is_duplicate") or 0)
        d["enriched"] = bool(d.get("enriched") or 0)
        for field_name in ("website_coherent", "domain_catch_all", "domain_mismatch",
                           "whatsapp", "reachable", "name_looks_like_company"):
            if field_name in d:
                d[field_name] = _bool_or_none(d[field_name])
        # Parse enrich_data JSON if present; absent keys stay None so pools
        # created before the ICP rework keep loading.
        for field_name in ENRICH_FIELDS:
            d.setdefault(field_name, None)
        if d.get("enrich_data"):
            try:
                d.update(json.loads(d["enrich_data"]))
            except (json.JSONDecodeError, TypeError):
                pass
        result.append(d)
    return result


def count_pending_quota(pool_id: str) -> int:
    """How many leads in this pool never got a finder's credit spent on them."""
    with _conn() as con:
        _migrate_lead_pool(con)
        row = con.execute(
            "SELECT COUNT(*) AS cnt FROM lead_pool WHERE pool_id = ? "
            "AND email_status = 'pending_quota'", (pool_id,)
        ).fetchone()
    return row["cnt"] if row else 0


# Cascade/reachability outcomes, written back to their own columns rather
# than left inside the enrich_data JSON blob only. create_pool() inserts a
# lead before /api/enrich ever runs the cascade on it, so these columns start
# NULL; get_pool_leads' only_reachable filter reads the raw `reachable`
# column in SQL, and a value that only ever lived inside enrich_data would
# leave that filter permanently blind to the real outcome.
CASCADE_POOL_COLUMNS: tuple[str, ...] = (
    "email", "email_status", "email_confidence", "email_source", "email_type",
    "contact_source_url", "domain_catch_all", "domain_mx_provider", "domain_mismatch",
    "phone", "phone_type", "phone_source", "whatsapp",
    "facebook_url", "instagram_url", "linkedin_company_url",
    "reachable", "contact_level",
)

_CASCADE_BOOL_COLUMNS = frozenset({"domain_catch_all", "domain_mismatch", "whatsapp", "reachable"})


def mark_leads_enriched(pool_id: str, lead_ids: list[int], enrich_job_id: str, enrich_data_map: dict[int, dict]) -> None:
    """Mark specific leads as enriched and store their enrichment data.

    Any key in enrich_data_map that names a CASCADE_POOL_COLUMNS column is
    additionally written to that column directly (see its docstring).
    """
    now = datetime.now(timezone.utc).isoformat()
    with _conn() as con:
        _migrate_lead_pool(con)
        for lid in lead_ids:
            data = enrich_data_map.get(lid, {})
            data_json = json.dumps(data)
            con.execute(
                "UPDATE lead_pool SET enriched = 1, enrich_job_id = ?, enriched_at = ?, enrich_data = ? WHERE id = ?",
                (enrich_job_id, now, data_json, lid),
            )
            updates = {col: data[col] for col in CASCADE_POOL_COLUMNS if col in data}
            if updates:
                values = [
                    (None if v is None else int(bool(v))) if col in _CASCADE_BOOL_COLUMNS else v
                    for col, v in updates.items()
                ]
                set_clause = ", ".join(f"{col} = ?" for col in updates)
                con.execute(f"UPDATE lead_pool SET {set_clause} WHERE id = ?", (*values, lid))
        # Update pool meta
        enriched_count = con.execute(
            "SELECT COUNT(*) as cnt FROM lead_pool WHERE pool_id = ? AND enriched = 1", (pool_id,)
        ).fetchone()["cnt"]
        con.execute("UPDATE pool_meta SET enriched_leads = ? WHERE pool_id = ?", (enriched_count, pool_id))


def update_cascade_columns(lead_ids: list[int], data_map: dict[int, dict]) -> None:
    """Write cascade outcome columns for leads without marking them enriched.

    pending_quota leads must never go through mark_leads_enriched: setting
    enriched=1 would drop them from get_pool_leads(only_unenriched=True) and
    they would never resurface for the batch after the monthly reset (§10).
    But mark_leads_enriched is the only path that writes CASCADE_POOL_COLUMNS
    (email_status in particular), so without this helper a pending lead's row
    keeps email_status = NULL forever: the "pending_quota sorts first" ORDER
    BY in get_pool_leads can never match it, and count_pending_quota() stays
    at 0 no matter how many leads are actually waiting on a reset.
    """
    with _conn() as con:
        _migrate_lead_pool(con)
        for lid in lead_ids:
            data = data_map.get(lid, {})
            updates = {col: data[col] for col in CASCADE_POOL_COLUMNS if col in data}
            if not updates:
                continue
            values = [
                (None if v is None else int(bool(v))) if col in _CASCADE_BOOL_COLUMNS else v
                for col, v in updates.items()
            ]
            set_clause = ", ".join(f"{col} = ?" for col in updates)
            con.execute(f"UPDATE lead_pool SET {set_clause} WHERE id = ?", (*values, lid))


def delete_pool(pool_id: str) -> bool:
    with _conn() as con:
        con.execute("DELETE FROM lead_pool WHERE pool_id = ?", (pool_id,))
        cur = con.execute("DELETE FROM pool_meta WHERE pool_id = ?", (pool_id,))
    return cur.rowcount > 0
