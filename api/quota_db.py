"""
Per-provider quota accounting.

The pipeline runs entirely on free tiers: 50 to 100 lookups a month across
three providers. A counter that drifts above the provider's real balance
spends credits the run does not have and fails mid-cascade; one that drifts
below leaves paid-for lookups unused. Both are silent, so the provider's own
number always wins (see sync_remaining) and the local counter only moves on a
result the provider actually billed.
"""
import os
import sqlite3
from datetime import date
from typing import Optional

import config as pipeline_config

_DB_PATH = os.path.join(pipeline_config.OUTPUT_DIR, "history.db")

_CREATE_PROVIDER_QUOTA = """
CREATE TABLE IF NOT EXISTS provider_quota (
    provider     TEXT PRIMARY KEY,
    allocation   REAL NOT NULL,
    consumed     REAL NOT NULL DEFAULT 0,
    remaining    REAL NOT NULL,
    reset_date   TEXT,
    rollover_cap REAL NOT NULL DEFAULT 0,
    synced_at    TEXT
)
"""


def _conn() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(_DB_PATH), exist_ok=True)
    con = sqlite3.connect(_DB_PATH, timeout=5)
    con.row_factory = sqlite3.Row
    return con


def init_quota_tables() -> None:
    with _conn() as con:
        con.execute(_CREATE_PROVIDER_QUOTA)
        for provider, allocation in pipeline_config.PROVIDER_ALLOCATIONS.items():
            cap = pipeline_config.PROVIDER_ROLLOVER_CAP.get(provider, 0.0)
            # allocation and rollover_cap belong to config, so they are
            # re-asserted on every start: editing .env has to actually take
            # effect, and the free-tier numbers this pipeline runs on are not
            # all documented (Prospeo publishes none), so the operator will
            # correct them. remaining, consumed and reset_date are runtime
            # state and are left alone — raising an allowance must never hand
            # out credits, it only changes what the next reset restores to.
            con.execute(
                """INSERT INTO provider_quota
                   (provider, allocation, consumed, remaining, rollover_cap)
                   VALUES (?, ?, 0, ?, ?)
                   ON CONFLICT(provider) DO UPDATE SET
                     allocation = excluded.allocation,
                     rollover_cap = excluded.rollover_cap""",
                (provider, allocation, allocation, cap),
            )


def get_quota(provider: str) -> dict:
    with _conn() as con:
        row = con.execute(
            "SELECT * FROM provider_quota WHERE provider = ?", (provider,)
        ).fetchone()
    if row is None:
        allocation = pipeline_config.PROVIDER_ALLOCATIONS.get(provider, 0.0)
        return {
            "provider": provider, "allocation": allocation, "consumed": 0.0,
            "remaining": allocation, "reset_date": None,
            "rollover_cap": pipeline_config.PROVIDER_ROLLOVER_CAP.get(provider, 0.0),
            "synced_at": None,
        }
    return dict(row)


def can_spend(provider: str, cost: float = 1.0) -> bool:
    return get_quota(provider)["remaining"] >= cost


def record_spend(provider: str, cost: float, billed: bool) -> None:
    """Decrement only when the provider actually charged us.

    All three providers return results they do not bill: Prospeo's 90-day
    re-enrichment (free_enrichment=true), GetProspect's automatic refund on
    not_found and accept_all, and every provider's "no result, no charge".
    Decrementing on those would exhaust a 50-credit month in a fraction of
    the lookups it can really afford.
    """
    if not billed:
        return
    with _conn() as con:
        con.execute(
            """UPDATE provider_quota
               SET consumed = consumed + ?, remaining = MAX(0, remaining - ?)
               WHERE provider = ?""",
            (cost, cost, provider),
        )


def sync_remaining(provider: str, remaining: float, reset_date: Optional[str]) -> None:
    """Adopt the provider's own balance, which always supersedes ours."""
    allocation = pipeline_config.PROVIDER_ALLOCATIONS.get(provider, remaining)
    cap = pipeline_config.PROVIDER_ROLLOVER_CAP.get(provider, 0.0)
    with _conn() as con:
        con.execute(
            """INSERT INTO provider_quota
               (provider, allocation, consumed, remaining, reset_date, rollover_cap, synced_at)
               VALUES (?, ?, ?, ?, ?, ?, datetime('now'))
               ON CONFLICT(provider) DO UPDATE SET
                 remaining = excluded.remaining,
                 consumed = MAX(0, provider_quota.allocation - excluded.remaining),
                 reset_date = COALESCE(excluded.reset_date, provider_quota.reset_date),
                 synced_at = excluded.synced_at""",
            (provider, allocation, max(0.0, allocation - remaining), remaining,
             reset_date, cap),
        )


def _next_month(today: date) -> date:
    return date(today.year + (today.month == 12), (today.month % 12) + 1, 1)


def apply_monthly_reset(provider: str, today: Optional[date] = None) -> None:
    """Restore the allowance when the reset date has passed.

    Rollover is expressed as a multiple of the allowance, so a provider that
    does not carry credits forward (Prospeo, Hunter) simply has a cap of 0
    and starts the month at exactly its allocation.
    """
    today = today or date.today()
    quota = get_quota(provider)
    reset_date = quota.get("reset_date")
    if not reset_date:
        return
    try:
        due = date.fromisoformat(str(reset_date)[:10])
    except ValueError:
        return
    if today < due:
        return

    allocation = quota["allocation"]
    carried = min(quota["remaining"], allocation * quota["rollover_cap"])
    with _conn() as con:
        con.execute(
            """UPDATE provider_quota
               SET remaining = ?, consumed = 0, reset_date = ?
               WHERE provider = ?""",
            (allocation + carried, _next_month(today).isoformat(), provider),
        )
