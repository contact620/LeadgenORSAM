"""
Suppression list — checked before any enrichment, paid or free.

Existing BoxCom clients, people already contacted and opt-outs must never
reach a finder: contacting them is at best wasteful and at worst a breach of
an explicit request. The check therefore sits ahead of the cascade, not at
export time, so a suppressed lead costs nothing at all.
"""
import csv
import io
import os
import sqlite3
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urlparse

import config as pipeline_config

_DB_PATH = os.path.join(pipeline_config.OUTPUT_DIR, "history.db")

_CREATE_SUPPRESSION = """
CREATE TABLE IF NOT EXISTS suppression_list (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    email        TEXT,
    linkedin_url TEXT,
    domaine      TEXT,
    motif        TEXT NOT NULL DEFAULT 'non précisé',
    added_at     TEXT NOT NULL,
    UNIQUE (email, linkedin_url, domaine)
)
"""


def _conn() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(_DB_PATH), exist_ok=True)
    con = sqlite3.connect(_DB_PATH, timeout=5)
    con.row_factory = sqlite3.Row
    return con


def init_suppression_table() -> None:
    with _conn() as con:
        con.execute(_CREATE_SUPPRESSION)


def _norm(value: Optional[str]) -> Optional[str]:
    cleaned = (value or "").strip().lower().rstrip("/")
    return cleaned or None


def add_entry(email=None, linkedin_url=None, domaine=None, motif="non précisé") -> bool:
    """Insert one entry, returning False only when it carries no identifier.

    Existence is checked with IS rather than relying on the table's UNIQUE
    constraint under INSERT OR IGNORE: SQLite treats every NULL as distinct
    from every other NULL in a UNIQUE index, so two rows that both leave
    linkedin_url and domaine unset would not collide there and re-importing
    the same CSV would duplicate every email-only row.
    """
    email, linkedin_url, domaine = _norm(email), _norm(linkedin_url), _norm(domaine)
    if not (email or linkedin_url or domaine):
        return False
    with _conn() as con:
        existing = con.execute(
            """SELECT id FROM suppression_list
               WHERE email IS ? AND linkedin_url IS ? AND domaine IS ?""",
            (email, linkedin_url, domaine),
        ).fetchone()
        if existing is None:
            con.execute(
                """INSERT INTO suppression_list
                   (email, linkedin_url, domaine, motif, added_at) VALUES (?,?,?,?,?)""",
                (email, linkedin_url, domaine, motif or "non précisé",
                 datetime.now(timezone.utc).isoformat()),
            )
    return True


def is_suppressed(lead: dict) -> Optional[str]:
    """Return the suppression reason, or None. Domain matches cover colleagues."""
    email = _norm(lead.get("email"))
    linkedin = _norm((lead.get("linkedin_url") or "").split("?")[0])
    domain = _norm(urlparse(lead.get("website") or "").netloc.removeprefix("www."))
    if not domain and email and "@" in email:
        domain = email.rsplit("@", 1)[1]

    with _conn() as con:
        row = con.execute(
            """SELECT motif FROM suppression_list
               WHERE (email IS NOT NULL AND email = ?)
                  OR (linkedin_url IS NOT NULL AND linkedin_url = ?)
                  OR (domaine IS NOT NULL AND domaine = ?)
               LIMIT 1""",
            (email, linkedin, domain),
        ).fetchone()
    return row["motif"] if row else None


def import_csv(text: str) -> dict:
    """Import rows with columns email, linkedin_url, domaine, motif (all optional)."""
    reader = csv.DictReader(io.StringIO(text))
    imported = skipped = 0
    for row in reader:
        normalized = {(k or "").strip().lower(): v for k, v in row.items()}
        added = add_entry(
            email=normalized.get("email"),
            linkedin_url=normalized.get("linkedin_url"),
            domaine=normalized.get("domaine") or normalized.get("domain"),
            motif=normalized.get("motif") or normalized.get("reason") or "import CSV",
        )
        imported += int(added)
        skipped += int(not added)
    return {"imported": imported, "skipped": skipped}


def list_entries() -> list[dict]:
    with _conn() as con:
        return [dict(r) for r in con.execute(
            "SELECT * FROM suppression_list ORDER BY added_at DESC"
        ).fetchall()]


def delete_entry(row_id: int) -> bool:
    with _conn() as con:
        cur = con.execute("DELETE FROM suppression_list WHERE id = ?", (row_id,))
    return cur.rowcount > 0
