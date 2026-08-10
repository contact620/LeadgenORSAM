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

import config as pipeline_config
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


# ── Deduplication (existing) ─────────────────────────────────────────────────

def check_duplicates(leads: list[dict]) -> dict[str, dict]:
    emails = [l.get("email", "").strip().lower() for l in leads if l.get("email")]
    if not emails:
        return {}
    result = {}
    with _conn() as con:
        placeholders = ",".join("?" for _ in emails)
        rows = con.execute(
            f"SELECT email, first_seen_at, seen_count FROM known_leads WHERE email IN ({placeholders})",
            emails,
        ).fetchall()
        for row in rows:
            result[row["email"]] = {"first_seen_at": row["first_seen_at"], "seen_count": row["seen_count"]}
    return result


def register_leads(job_id: str, leads: list[dict]) -> tuple[int, int]:
    now = datetime.now(timezone.utc).isoformat()
    new_count = 0
    dup_count = 0
    with _conn() as con:
        for lead in leads:
            email = (lead.get("email") or "").strip().lower()
            if not email:
                continue
            existing = con.execute("SELECT seen_count FROM known_leads WHERE email = ?", (email,)).fetchone()
            if existing:
                con.execute("UPDATE known_leads SET seen_count = seen_count + 1 WHERE email = ?", (email,))
                dup_count += 1
            else:
                con.execute(
                    "INSERT INTO known_leads (email, first_name, last_name, company, first_seen_job_id, first_seen_at) VALUES (?,?,?,?,?,?)",
                    (email, lead.get("first_name"), lead.get("last_name"), lead.get("company"), job_id, now),
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
    hit_count = sum(1 for l in leads if l.get("is_hit"))

    with _conn() as con:
        con.execute(
            "INSERT INTO pool_meta (pool_id, name, apollo_url, created_at, scrape_job_id, total_leads, hit_leads) VALUES (?,?,?,?,?,?,?)",
            (pool_id, name, apollo_url, now, scrape_job_id, total, hit_count),
        )
        for lead in leads:
            con.execute(
                """INSERT INTO lead_pool
                   (pool_id, first_name, last_name, company, job_title, location,
                    email, phone, linkedin_url, website, hit_score, is_hit,
                    is_duplicate, first_seen_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (pool_id, lead.get("first_name"), lead.get("last_name"),
                 lead.get("company"), lead.get("job_title"), lead.get("location"),
                 lead.get("email"), lead.get("phone"), lead.get("linkedin_url"), lead.get("website"),
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


def get_pool_leads(pool_id: str, only_hit: bool = False, only_unenriched: bool = False, limit: int = 0) -> list[dict]:
    """Get leads from a pool with optional filters."""
    query = "SELECT * FROM lead_pool WHERE pool_id = ?"
    params: list = [pool_id]

    if only_hit:
        query += " AND is_hit = 1"
    if only_unenriched:
        query += " AND enriched = 0"
    query += " ORDER BY hit_score DESC"
    if limit > 0:
        query += " LIMIT ?"
        params.append(limit)

    with _conn() as con:
        rows = con.execute(query, params).fetchall()

    result = []
    for r in rows:
        d = dict(r)
        d["is_hit"] = bool(d["is_hit"])
        d["is_duplicate"] = bool(d["is_duplicate"])
        d["enriched"] = bool(d["enriched"])
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


def mark_leads_enriched(pool_id: str, lead_ids: list[int], enrich_job_id: str, enrich_data_map: dict[int, dict]) -> None:
    """Mark specific leads as enriched and store their enrichment data."""
    now = datetime.now(timezone.utc).isoformat()
    with _conn() as con:
        for lid in lead_ids:
            data_json = json.dumps(enrich_data_map.get(lid, {}))
            con.execute(
                "UPDATE lead_pool SET enriched = 1, enrich_job_id = ?, enriched_at = ?, enrich_data = ? WHERE id = ?",
                (enrich_job_id, now, data_json, lid),
            )
        # Update pool meta
        enriched_count = con.execute(
            "SELECT COUNT(*) as cnt FROM lead_pool WHERE pool_id = ? AND enriched = 1", (pool_id,)
        ).fetchone()["cnt"]
        con.execute("UPDATE pool_meta SET enriched_leads = ? WHERE pool_id = ?", (enriched_count, pool_id))


def delete_pool(pool_id: str) -> bool:
    with _conn() as con:
        con.execute("DELETE FROM lead_pool WHERE pool_id = ?", (pool_id,))
        cur = con.execute("DELETE FROM pool_meta WHERE pool_id = ?", (pool_id,))
    return cur.rowcount > 0
