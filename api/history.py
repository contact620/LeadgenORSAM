"""
Lightweight SQLite persistence for pipeline job history.
DB file lives at output/history.db alongside CSVs.
"""
import os
import sqlite3
from typing import Optional

import config as pipeline_config

_DB_PATH = os.path.join(pipeline_config.OUTPUT_DIR, "history.db")

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS job_history (
    job_id       TEXT PRIMARY KEY,
    status       TEXT NOT NULL,
    apollo_url   TEXT NOT NULL,
    max_leads    INTEGER NOT NULL,
    skip_gpt     INTEGER NOT NULL,
    started_at   TEXT NOT NULL,
    finished_at  TEXT,
    total_leads  INTEGER DEFAULT 0,
    hit_leads    INTEGER DEFAULT 0,
    nohit_leads  INTEGER DEFAULT 0,
    email_pct    REAL DEFAULT 0,
    linkedin_pct REAL DEFAULT 0,
    phone_pct    REAL DEFAULT 0,
    website_pct  REAL DEFAULT 0,
    avg_score    REAL DEFAULT 0,
    csv_filename TEXT,
    error        TEXT
)
"""


def _conn() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(_DB_PATH), exist_ok=True)
    con = sqlite3.connect(_DB_PATH, timeout=5)
    con.row_factory = sqlite3.Row
    return con


def init_db() -> None:
    with _conn() as con:
        con.execute(_CREATE_TABLE)


def save_job(
    job_id: str,
    status: str,
    apollo_url: str,
    max_leads: int,
    skip_gpt: bool,
    started_at: str,
    finished_at: str,
    total_leads: int = 0,
    hit_leads: int = 0,
    nohit_leads: int = 0,
    email_pct: float = 0.0,
    linkedin_pct: float = 0.0,
    phone_pct: float = 0.0,
    website_pct: float = 0.0,
    avg_score: float = 0.0,
    csv_filename: Optional[str] = None,
    error: Optional[str] = None,
) -> None:
    with _conn() as con:
        con.execute(
            """INSERT OR REPLACE INTO job_history
               (job_id, status, apollo_url, max_leads, skip_gpt,
                started_at, finished_at,
                total_leads, hit_leads, nohit_leads,
                email_pct, linkedin_pct, phone_pct, website_pct, avg_score,
                csv_filename, error)
               VALUES (?,?,?,?,?, ?,?, ?,?,?, ?,?,?,?,?, ?,?)""",
            (job_id, status, apollo_url, max_leads, int(skip_gpt),
             started_at, finished_at,
             total_leads, hit_leads, nohit_leads,
             email_pct, linkedin_pct, phone_pct, website_pct, avg_score,
             csv_filename, error),
        )


def list_jobs(limit: int = 50, offset: int = 0) -> list[dict]:
    with _conn() as con:
        rows = con.execute(
            "SELECT * FROM job_history ORDER BY started_at DESC LIMIT ? OFFSET ?",
            (limit, offset),
        ).fetchall()
    return [_row_to_dict(r) for r in rows]


def get_job(job_id: str) -> Optional[dict]:
    with _conn() as con:
        row = con.execute(
            "SELECT * FROM job_history WHERE job_id = ?", (job_id,)
        ).fetchone()
    return _row_to_dict(row) if row else None


def delete_job(job_id: str) -> Optional[str]:
    """Delete history entry. Returns csv_filename if it existed."""
    entry = get_job(job_id)
    if not entry:
        return None
    with _conn() as con:
        con.execute("DELETE FROM job_history WHERE job_id = ?", (job_id,))
    return entry.get("csv_filename")


def _row_to_dict(row: sqlite3.Row) -> dict:
    d = dict(row)
    d["skip_gpt"] = bool(d["skip_gpt"])
    # Add csv_available flag
    fname = d.get("csv_filename")
    d["csv_available"] = bool(
        fname and os.path.exists(os.path.join(pipeline_config.OUTPUT_DIR, fname))
    )
    return d
