"""
Wraps the pipeline steps and emits progress events via asyncio.Queue.
Runs the pipeline in a thread (since parts are sync) and bridges
progress back to async SSE via queue_put callbacks.
"""
import asyncio
import json
import logging
import os
import re
import sys
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Optional

import pandas as pd

# Add project root to path so pipeline modules are importable
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import config as pipeline_config
from api.models import JobResult, JobStats, ProgressEvent

# ── In-memory job store ────────────────────────────────────────────────────────
_jobs: dict[str, JobResult] = {}
_queues: dict[str, asyncio.Queue] = {}
_job_meta: dict[str, dict] = {}  # apollo_url, max_leads, skip_gpt, started_at

_executor = ThreadPoolExecutor(max_workers=4)


def get_job(job_id: str) -> Optional[JobResult]:
    return _jobs.get(job_id)


def get_queue(job_id: str) -> Optional[asyncio.Queue]:
    return _queues.get(job_id)


# ── Progress mapping ──────────────────────────────────────────────────────────
# Step weights for total_progress calculation (must sum to 1.0)
STEP_WEIGHTS = {1: 0.05, 2: 0.25, 3: 0.30, 4: 0.05, 5: 0.35}
STEP_NAMES = {
    1: "Input Apollo URL",
    2: "Scraping Apollo",
    3: "Enrichissement (Google + Dropcontact)",
    4: "Calcul du taux de hit",
    5: "Enrichissement IA (GPT-4o-mini)",
}

# Patterns to detect which step a log message belongs to
STEP_PATTERNS = [
    (2, re.compile(r"Step 2|Scraping Apollo|apollo|page \d+", re.I)),
    (3, re.compile(r"Step 3|Google enrichment|Dropcontact|dropcontact|batch \d+", re.I)),
    (4, re.compile(r"Step 4|hit score|Hit score complete", re.I)),
    (5, re.compile(r"Step 5|GPT|LinkedIn profile|Scraping hit lead", re.I)),
]


class _QueueLogHandler(logging.Handler):
    """Captures pipeline log records and pushes them to the SSE queue."""

    def __init__(self, loop: asyncio.AbstractEventLoop, queue: asyncio.Queue, job_id: str):
        super().__init__()
        self._loop = loop
        self._queue = queue
        self._job_id = job_id
        self._step = 1
        self._step_progress = 0.0
        self._step_log_count = 0
        self._max_total = 0.0  # high-watermark: progress never goes backward

    def _detect_step(self, msg: str) -> int:
        for step, pattern in STEP_PATTERNS:
            if pattern.search(msg):
                return step
        return self._step  # keep current step if no match

    def _compute_total(self, step: int, step_prog: float) -> float:
        base = sum(STEP_WEIGHTS[s] for s in range(1, step))
        return min(base + STEP_WEIGHTS.get(step, 0) * step_prog, 0.99)

    def emit(self, record: logging.LogRecord):
        msg = self.format(record)
        new_step = self._detect_step(msg)
        if new_step != self._step:
            self._step = new_step
            self._step_progress = 0.0
            self._step_log_count = 0
        else:
            self._step_log_count += 1
            # Slowly advance within the step (asymptotic toward 0.90)
            self._step_progress = min(self._step_progress + 0.03, 0.90)

        raw_total = self._compute_total(self._step, self._step_progress)
        total = max(raw_total, self._max_total)
        self._max_total = total

        event = ProgressEvent(
            step=self._step,
            step_name=STEP_NAMES.get(self._step, ""),
            message=msg,
            progress=self._step_progress,
            total_progress=total,
        )

        payload = json.dumps({"type": "progress", "data": event.model_dump()})
        asyncio.run_coroutine_threadsafe(self._queue.put(payload), self._loop)

        # Forward WARNING+ logs as SSE warning events (shown as toasts in frontend)
        if record.levelno >= logging.WARNING:
            warning_payload = json.dumps({"type": "warning", "data": {"message": msg}})
            asyncio.run_coroutine_threadsafe(self._queue.put(warning_payload), self._loop)

    def set_explicit_progress(self, step: int, step_prog: float, message: str = "") -> None:
        """Emit a forced progress event at a step boundary (always advances the bar)."""
        self._step = step
        self._step_progress = step_prog
        self._step_log_count = 0
        total = self._compute_total(step, step_prog)
        self._max_total = max(total, self._max_total)

        event = ProgressEvent(
            step=step,
            step_name=STEP_NAMES.get(step, ""),
            message=message,
            progress=step_prog,
            total_progress=self._max_total,
        )
        payload = json.dumps({"type": "progress", "data": event.model_dump()})
        asyncio.run_coroutine_threadsafe(self._queue.put(payload), self._loop)


# ── Pipeline execution ────────────────────────────────────────────────────────

def _run_pipeline_sync(job_id: str, url: str, max_leads: int, skip_gpt: bool,
                       loop: asyncio.AbstractEventLoop, queue: asyncio.Queue):
    """
    Runs the full pipeline synchronously in a thread.
    Emits progress to the queue and updates the job state when done.
    """
    import asyncio as _asyncio

    # Attach log handler to root logger for this thread
    # Set level to DEBUG so INFO logs from scrapers reach the handler
    handler = _QueueLogHandler(loop, queue, job_id)
    handler.setFormatter(logging.Formatter("%(message)s"))
    root_logger = logging.getLogger()
    saved_level = root_logger.level
    root_logger.setLevel(logging.DEBUG)
    root_logger.addHandler(handler)

    try:
        _jobs[job_id].status = "running"

        # Reset enricher state from any previous run
        from enrichers.google_search import _reset_state as _reset_google
        from enrichers.dropcontact import _reset_state as _reset_dc
        from enrichers.gpt_enricher import _reset_state as _reset_gpt
        _reset_google()
        _reset_dc()
        _reset_gpt()

        # Run async pipeline steps in a new event loop for this thread
        new_loop = _asyncio.new_event_loop()
        _asyncio.set_event_loop(new_loop)

        # ── Step 2: Apollo scraping ───────────────────────────────────────────
        handler.set_explicit_progress(2, 0.0, "Lancement scraping Apollo...")
        from scrapers.apollo_scraper import scrape_apollo
        leads = new_loop.run_until_complete(scrape_apollo(url, max_leads=max_leads))

        if not leads:
            raise RuntimeError("No leads scraped from Apollo. Check cookies and URL.")
        handler.set_explicit_progress(2, 1.0, f"Scraping terminé — {len(leads)} leads extraits")

        # ── Step 3a: Google enrichment ────────────────────────────────────────
        handler.set_explicit_progress(3, 0.0, "Enrichissement Google (LinkedIn URL + site web)...")
        from enrichers.google_search import enrich_leads_google
        leads = enrich_leads_google(leads)

        linkedin_count = sum(1 for l in leads if l.get("linkedin_url"))
        website_count = sum(1 for l in leads if l.get("website"))
        handler.set_explicit_progress(
            3, 0.5,
            f"Google terminé — {linkedin_count}/{len(leads)} LinkedIn, "
            f"{website_count}/{len(leads)} sites web. Lancement Dropcontact..."
        )

        # ── Step 3b: Dropcontact enrichment ───────────────────────────────────
        from enrichers.dropcontact import enrich_leads_dropcontact
        leads = enrich_leads_dropcontact(leads)

        email_count = sum(1 for l in leads if l.get("email"))
        phone_count = sum(1 for l in leads if l.get("phone"))
        handler.set_explicit_progress(
            3, 1.0,
            f"Enrichissement terminé — {email_count}/{len(leads)} emails, "
            f"{phone_count}/{len(leads)} téléphones"
        )

        # ── Step 4: Hit score ─────────────────────────────────────────────────
        handler.set_explicit_progress(4, 0.0, "Calcul des hit scores...")
        from processors.hit_calculator import score_all_leads
        hit_leads, nohit_leads = score_all_leads(leads)
        handler.set_explicit_progress(4, 1.0, f"{len(hit_leads)} hit leads identifiés (seuil {pipeline_config.HIT_THRESHOLD})")

        # ── Step 5: AI enrichment (hit leads only) ────────────────────────────
        if not skip_gpt and hit_leads:
            handler.set_explicit_progress(5, 0.0, "Scraping sites web des hit leads...")
            from scrapers.website_scraper import scrape_hit_leads
            hit_leads = new_loop.run_until_complete(scrape_hit_leads(hit_leads))

            handler.set_explicit_progress(5, 0.5, "Appel Claude AI — enrichissement IA...")
            from enrichers.gpt_enricher import enrich_leads_gpt
            hit_leads = enrich_leads_gpt(hit_leads)
            handler.set_explicit_progress(5, 1.0, "Enrichissement IA terminé")
        else:
            for lead in hit_leads:
                lead.setdefault("activity_summary", None)
                lead.setdefault("conversion_angle", None)

        new_loop.close()

        # ── Export CSV ────────────────────────────────────────────────────────
        os.makedirs(pipeline_config.OUTPUT_DIR, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        csv_filename = f"leads_final_{ts}_{job_id[:8]}.csv"
        csv_path = os.path.join(pipeline_config.OUTPUT_DIR, csv_filename)

        CSV_COLUMNS = [
            "first_name", "last_name", "company", "job_title", "location",
            "email", "phone", "linkedin_url", "website",
            "hit_score", "is_hit", "activity_summary", "conversion_angle",
        ]
        df = pd.DataFrame(leads)
        for col in CSV_COLUMNS:
            if col not in df.columns:
                df[col] = None
        df[CSV_COLUMNS].to_csv(csv_path, index=False, encoding="utf-8-sig")

        # ── Compute stats ─────────────────────────────────────────────────────
        total = len(leads)
        def pct(field):
            return round(100 * sum(1 for l in leads if l.get(field)) / total, 1) if total else 0.0

        def cnt(field):
            return sum(1 for l in leads if l.get(field))

        stats = JobStats(
            email_pct=pct("email"),
            linkedin_pct=pct("linkedin_url"),
            phone_pct=pct("phone"),
            website_pct=pct("website"),
            avg_score=round(sum(l.get("hit_score", 0) for l in leads) / total, 1) if total else 0.0,
            email_count=cnt("email"),
            linkedin_count=cnt("linkedin_url"),
            phone_count=cnt("phone"),
            website_count=cnt("website"),
        )

        # ── Update job state ──────────────────────────────────────────────────
        _jobs[job_id] = JobResult(
            job_id=job_id,
            status="done",
            total_leads=total,
            hit_leads=len(hit_leads),
            nohit_leads=len(nohit_leads),
            stats=stats,
            leads=leads,
            csv_path=csv_path,
        )

        # ── Persist to history DB ────────────────────────────────────────────
        from api.history import save_job as _save_hist
        meta = _job_meta.get(job_id, {})
        _save_hist(
            job_id=job_id, status="done",
            apollo_url=meta.get("apollo_url", ""),
            max_leads=meta.get("max_leads", 0),
            skip_gpt=meta.get("skip_gpt", False),
            started_at=meta.get("started_at", ""),
            finished_at=datetime.now().isoformat(),
            total_leads=total,
            hit_leads=len(hit_leads),
            nohit_leads=len(nohit_leads),
            email_pct=stats.email_pct,
            linkedin_pct=stats.linkedin_pct,
            phone_pct=stats.phone_pct,
            website_pct=stats.website_pct,
            avg_score=stats.avg_score,
            csv_filename=csv_filename,
        )

        # Signal done
        done_payload = json.dumps({"type": "done", "data": {"job_id": job_id}})
        asyncio.run_coroutine_threadsafe(queue.put(done_payload), loop)

    except Exception as exc:
        error_msg = str(exc)
        logging.getLogger("pipeline_runner").error(f"Pipeline error: {error_msg}")
        _jobs[job_id] = JobResult(
            job_id=job_id,
            status="error",
            error=error_msg,
        )
        # Persist error to history
        from api.history import save_job as _save_hist
        meta = _job_meta.get(job_id, {})
        _save_hist(
            job_id=job_id, status="error",
            apollo_url=meta.get("apollo_url", ""),
            max_leads=meta.get("max_leads", 0),
            skip_gpt=meta.get("skip_gpt", False),
            started_at=meta.get("started_at", ""),
            finished_at=datetime.now().isoformat(),
            error=error_msg,
        )
        error_payload = json.dumps({"type": "error", "data": {"message": error_msg}})
        asyncio.run_coroutine_threadsafe(queue.put(error_payload), loop)
    finally:
        root_logger.removeHandler(handler)
        root_logger.setLevel(saved_level)
        # Signal queue end
        asyncio.run_coroutine_threadsafe(queue.put(None), loop)


def start_job(url: str, max_leads: int, skip_gpt: bool) -> str:
    """Create a job, start the pipeline in background, return job_id."""
    job_id = str(uuid.uuid4())

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    queue: asyncio.Queue = asyncio.Queue()

    _jobs[job_id] = JobResult(job_id=job_id, status="running")
    _queues[job_id] = queue
    _job_meta[job_id] = {
        "apollo_url": url,
        "max_leads": max_leads,
        "skip_gpt": skip_gpt,
        "started_at": datetime.now().isoformat(),
    }

    _executor.submit(
        _run_pipeline_sync,
        job_id, url, max_leads, skip_gpt, loop, queue,
    )

    return job_id
