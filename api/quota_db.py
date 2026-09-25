"""
Per-provider quota accounting and email lookup cache.

The pipeline runs entirely on free tiers: 50 to 100 lookups a month across
three providers. A counter that drifts above the provider's real balance
spends credits the run does not have and fails mid-cascade; one that drifts
below leaves paid-for lookups unused. Both are silent, so the provider's own
number always wins (see sync_remaining) and the local counter only moves on a
result the provider actually billed.

The email lookup cache prevents paying twice for the same question: a 90-day
TTL-backed store maps (first, last, domain, provider) to result payloads or
None. Both quota and cache are per-provider spend bookkeeping and belong here.
"""
import json
import os
import re
import sqlite3
import unicodedata
from datetime import date, datetime, timedelta, timezone
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

# Aligned on Prospeo's 90-day free re-enrichment window: past it the provider
# bills again, so a cache entry that outlived the window would keep us from
# re-asking a question that is now worth asking.
CACHE_TTL_DAYS = 90

_CREATE_EMAIL_CACHE = """
CREATE TABLE IF NOT EXISTS email_lookup_cache (
    first_name   TEXT NOT NULL,
    last_name    TEXT NOT NULL,
    domain       TEXT NOT NULL,
    provider     TEXT NOT NULL,
    result       TEXT,
    looked_up_at TEXT NOT NULL,
    PRIMARY KEY (first_name, last_name, domain, provider)
)
"""

_NON_WORD_RE = re.compile(r"[^a-z0-9]+")


def _conn() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(_DB_PATH), exist_ok=True)
    con = sqlite3.connect(_DB_PATH, timeout=5)
    con.row_factory = sqlite3.Row
    return con


def init_quota_tables() -> None:
    with _conn() as con:
        con.execute(_CREATE_PROVIDER_QUOTA)
        con.execute(_CREATE_EMAIL_CACHE)
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


# ── Email lookup cache ────────────────────────────────────────────────────────


def normalize_name(value: str) -> str:
    """Lowercase, strip accents and punctuation. Shared by cache keys so that
    "Aïcha" and "Aicha" never pay for the same lookup twice."""
    if not value:
        return ""
    decomposed = unicodedata.normalize("NFKD", str(value))
    deaccented = "".join(c for c in decomposed if not unicodedata.combining(c))
    return _NON_WORD_RE.sub(" ", deaccented.lower()).strip()


def normalize_domain(value: str) -> str:
    """Fold a domain to a stable cache key.

    Deliberately NOT normalize_name. That function collapses every run of
    non-alphanumeric characters to a single space, so "groupe-atlas.ma" and
    "groupe.atlas.ma" — a hyphenated domain and a subdomain of an unrelated
    company — would share one key. The cache would then hand one company's
    address back for the other's lookup, and a wrong contact in the export is
    worse than a wasted credit: the operator cannot tell it is wrong.
    """
    return (value or "").strip().lower().removeprefix("www.")


def cache_lookup(first: str, last: str, domain: str, provider: str) -> Optional[dict]:
    """Return {"result": <payload or None>} on a fresh hit, None on a miss.

    The two-level shape matters: a cached miss is a hit on the cache (we asked,
    the provider said no) and must not trigger another paid call, while None
    means we never asked.
    """
    cutoff = (datetime.now(timezone.utc) - timedelta(days=CACHE_TTL_DAYS)).isoformat()
    with _conn() as con:
        row = con.execute(
            """SELECT result FROM email_lookup_cache
               WHERE first_name = ? AND last_name = ? AND domain = ?
                 AND provider = ? AND looked_up_at >= ?""",
            (normalize_name(first), normalize_name(last),
             normalize_domain(domain), provider, cutoff),
        ).fetchone()
    if row is None:
        return None
    return {"result": json.loads(row["result"]) if row["result"] else None}


def cache_store(first: str, last: str, domain: str, provider: str,
                result: Optional[dict]) -> None:
    with _conn() as con:
        con.execute(
            """INSERT INTO email_lookup_cache
               (first_name, last_name, domain, provider, result, looked_up_at)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(first_name, last_name, domain, provider) DO UPDATE SET
                 result = excluded.result, looked_up_at = excluded.looked_up_at""",
            (normalize_name(first), normalize_name(last), normalize_domain(domain),
             provider, json.dumps(result, ensure_ascii=False) if result is not None else None,
             datetime.now(timezone.utc).isoformat()),
        )
