"""
SQLite persistence for search templates.
Uses the same DB as history (output/history.db).
"""
import os
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Optional

import config as pipeline_config

_DB_PATH = os.path.join(pipeline_config.OUTPUT_DIR, "history.db")

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS templates (
    id           TEXT PRIMARY KEY,
    name         TEXT NOT NULL,
    apollo_url   TEXT NOT NULL,
    max_leads    INTEGER DEFAULT 200,
    skip_gpt     INTEGER DEFAULT 0,
    created_at   TEXT NOT NULL,
    last_used_at TEXT,
    run_count    INTEGER DEFAULT 0
)
"""


def _conn() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(_DB_PATH), exist_ok=True)
    con = sqlite3.connect(_DB_PATH, timeout=5)
    con.row_factory = sqlite3.Row
    return con


def init_templates_table() -> None:
    with _conn() as con:
        con.execute(_CREATE_TABLE)


def create_template(name: str, apollo_url: str, max_leads: int = 200, skip_gpt: bool = False) -> dict:
    tpl_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    with _conn() as con:
        con.execute(
            "INSERT INTO templates (id, name, apollo_url, max_leads, skip_gpt, created_at) VALUES (?,?,?,?,?,?)",
            (tpl_id, name, apollo_url, max_leads, int(skip_gpt), now),
        )
    return get_template(tpl_id)  # type: ignore


def list_templates() -> list[dict]:
    with _conn() as con:
        rows = con.execute("SELECT * FROM templates ORDER BY created_at DESC").fetchall()
    return [_row_to_dict(r) for r in rows]


def get_template(tpl_id: str) -> Optional[dict]:
    with _conn() as con:
        row = con.execute("SELECT * FROM templates WHERE id = ?", (tpl_id,)).fetchone()
    return _row_to_dict(row) if row else None


def update_template(tpl_id: str, name: str, apollo_url: str, max_leads: int, skip_gpt: bool) -> Optional[dict]:
    with _conn() as con:
        con.execute(
            "UPDATE templates SET name=?, apollo_url=?, max_leads=?, skip_gpt=? WHERE id=?",
            (name, apollo_url, max_leads, int(skip_gpt), tpl_id),
        )
    return get_template(tpl_id)


def delete_template(tpl_id: str) -> bool:
    with _conn() as con:
        cur = con.execute("DELETE FROM templates WHERE id = ?", (tpl_id,))
    return cur.rowcount > 0


def increment_usage(tpl_id: str) -> None:
    now = datetime.now(timezone.utc).isoformat()
    with _conn() as con:
        con.execute(
            "UPDATE templates SET run_count = run_count + 1, last_used_at = ? WHERE id = ?",
            (now, tpl_id),
        )


def _row_to_dict(row: sqlite3.Row) -> dict:
    d = dict(row)
    d["skip_gpt"] = bool(d["skip_gpt"])
    return d
