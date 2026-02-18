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

        event = ProgressEvent(
            step=self._step,
            step_name=STEP_NAMES.get(self._step, ""),
            message=msg,
            progress=self._step_progress,
            total_progress=self._compute_total(self._step, self._step_progress),
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
    handler = _QueueLogHandler(loop, queue, job_id)
    handler.setFormatter(logging.Formatter("%(message)s"))
    root_logger = logging.getLogger()
    root_logger.addHandler(handler)

    try:
        _jobs[job_id].status = "running"

        # Run async pipeline steps in a new event loop for this thread
        new_loop = _asyncio.new_event_loop()
        _asyncio.set_event_loop(new_loop)

        # ── Step 2: Apollo scraping ───────────────────────────────────────────
        from scrapers.apollo_scraper import scrape_apollo
        leads = new_loop.run_until_complete(scrape_apollo(url, max_leads=max_leads))

        if not leads:
            raise RuntimeError("No leads scraped from Apollo. Check cookies and URL.")

        # ── Step 3a: Google enrichment ────────────────────────────────────────
        from enrichers.google_search import enrich_leads_google
        leads = enrich_leads_google(leads)

        # ── Step 3b: Dropcontact enrichment ───────────────────────────────────
        from enrichers.dropcontact import enrich_leads_dropcontact
        leads = enrich_leads_dropcontact(leads)

        # ── Step 4: Hit score ─────────────────────────────────────────────────
        from processors.hit_calculator import score_all_leads
        hit_leads, nohit_leads = score_all_leads(leads)

        # ── Step 5: AI enrichment (hit leads only) ────────────────────────────
        if not skip_gpt and hit_leads:
            from scrapers.linkedin_scraper import scrape_hit_leads
            hit_leads = new_loop.run_until_complete(scrape_hit_leads(hit_leads))

            from enrichers.gpt_enricher import enrich_leads_gpt
            hit_leads = enrich_leads_gpt(hit_leads)
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

        stats = JobStats(
            email_pct=pct("email"),
            linkedin_pct=pct("linkedin_url"),
            phone_pct=pct("phone"),
            website_pct=pct("website"),
            avg_score=round(sum(l.get("hit_score", 0) for l in leads) / total, 1) if total else 0.0,
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
        error_payload = json.dumps({"type": "error", "data": {"message": error_msg}})
        asyncio.run_coroutine_threadsafe(queue.put(error_payload), loop)
    finally:
        root_logger.removeHandler(handler)
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

    _executor.submit(
        _run_pipeline_sync,
        job_id, url, max_leads, skip_gpt, loop, queue,
    )

    return job_id
