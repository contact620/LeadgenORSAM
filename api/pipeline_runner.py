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
_cancelled: dict[str, bool] = {}

_executor = ThreadPoolExecutor(max_workers=4)


PIPELINE_TIMEOUT_SECONDS = 45 * 60  # 45 minutes max


class PipelineCancelled(Exception):
    pass


class PipelineTimeout(PipelineCancelled):
    pass


def cancel_job(job_id: str) -> bool:
    if job_id in _jobs:
        _cancelled[job_id] = True
        return True
    return False


def _check_cancelled(job_id: str) -> None:
    if _cancelled.get(job_id):
        raise PipelineCancelled("Pipeline annulé par l'utilisateur")
    # Check timeout
    meta = _job_meta.get(job_id)
    if meta and meta.get("started_at"):
        started = datetime.fromisoformat(meta["started_at"])
        elapsed = (datetime.now() - started).total_seconds()
        if elapsed > PIPELINE_TIMEOUT_SECONDS:
            raise PipelineTimeout(f"Pipeline timeout après {int(elapsed // 60)} minutes")


def get_job(job_id: str) -> Optional[JobResult]:
    return _jobs.get(job_id)


def get_queue(job_id: str) -> Optional[asyncio.Queue]:
    return _queues.get(job_id)


# ── Progress mapping ──────────────────────────────────────────────────────────
# Step weights for total_progress calculation (must sum to 1.0)
STEP_WEIGHTS = {1: 0.05, 2: 0.18, 3: 0.22, 4: 0.05, 5: 0.12, 6: 0.23, 7: 0.15}
STEP_NAMES = {
    1: "Input Apollo URL",
    2: "Scraping Apollo",
    3: "Enrichissement (Google + Dropcontact)",
    4: "Calcul du taux de hit",
    5: "Scoring ICP (profil client idéal)",
    6: "Enrichissement IA (Claude)",
    7: "Enrichissement Perplexity (maturité, budget, signaux)",
}

# Patterns to detect which step a log message belongs to
STEP_PATTERNS = [
    (2, re.compile(r"Step 2|Scraping Apollo|apollo|page \d+", re.I)),
    (3, re.compile(r"Step 3|Google enrichment|Dropcontact|dropcontact|batch \d+", re.I)),
    (4, re.compile(r"Step 4|hit score|Hit score complete", re.I)),
    (5, re.compile(r"Step 5|ICP scoring|ICP|icp_score", re.I)),
    (6, re.compile(r"Step 6|GPT|LinkedIn profile|Scraping hit lead|Claude AI", re.I)),
    (7, re.compile(r"Step 7|Perplexity|perplexity enrichment|digital_maturity", re.I)),
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
                       loop: asyncio.AbstractEventLoop, queue: asyncio.Queue,
                       enrich_instructions: str = ""):
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
        from enrichers.perplexity_enricher import _reset_state as _reset_perplexity
        from processors.icp_scorer import _reset_state as _reset_icp
        _reset_google()
        _reset_dc()
        _reset_gpt()
        _reset_perplexity()
        _reset_icp()

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
        _check_cancelled(job_id)

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

        # ── Deduplication ──────────────────────────────────────────────────
        try:
            from api.leads_db import check_duplicates
            known = check_duplicates(leads)
            new_count = 0
            for lead in leads:
                email = (lead.get("email") or "").strip().lower()
                if email and email in known:
                    lead["is_duplicate"] = True
                    lead["first_seen_at"] = known[email].get("first_seen_at")
                else:
                    lead["is_duplicate"] = False
                    lead["first_seen_at"] = None
                    if email:
                        new_count += 1
            dup_count = len(known)
            handler.set_explicit_progress(4, 1.0, f"{new_count} nouveaux leads, {dup_count} déjà vus")
        except Exception:
            for lead in leads:
                lead["is_duplicate"] = False
                lead["first_seen_at"] = None

        _check_cancelled(job_id)

        # ── Step 5: ICP scoring (hit leads only) ────────────────────────────
        if not skip_gpt and hit_leads:
            handler.set_explicit_progress(5, 0.0, "Scoring ICP en cours...")
            from processors.icp_scorer import score_leads_icp
            hit_leads = score_leads_icp(hit_leads, enrich_instructions=enrich_instructions)
            icp_scored = sum(1 for l in hit_leads if l.get("icp_score") is not None)
            handler.set_explicit_progress(5, 1.0, f"Scoring ICP terminé — {icp_scored}/{len(hit_leads)} leads scorés")
        else:
            for lead in hit_leads:
                lead.setdefault("icp_score", None)
                lead.setdefault("icp_tier", None)
                lead.setdefault("icp_rationale", None)
                lead.setdefault("icp_scores_detail", None)

        # ── Step 6: AI enrichment (hit leads only) ────────────────────────────
        if not skip_gpt and hit_leads:
            handler.set_explicit_progress(6, 0.0, "Scraping sites web des hit leads...")
            from scrapers.website_scraper import scrape_hit_leads
            hit_leads = new_loop.run_until_complete(scrape_hit_leads(hit_leads))

            handler.set_explicit_progress(6, 0.5, "Appel Claude AI — enrichissement IA...")
            from enrichers.gpt_enricher import enrich_leads_gpt
            hit_leads = enrich_leads_gpt(hit_leads, enrich_instructions=enrich_instructions)
            handler.set_explicit_progress(6, 1.0, "Enrichissement IA terminé")
            _check_cancelled(job_id)

            # ── Step 7: Perplexity enrichment ──────────────────────────────
            handler.set_explicit_progress(7, 0.0, "Enrichissement Perplexity (maturité digitale, budget, signaux)...")
            from enrichers.perplexity_enricher import enrich_leads_perplexity
            hit_leads = enrich_leads_perplexity(hit_leads, enrich_instructions=enrich_instructions)
            handler.set_explicit_progress(7, 1.0, "Enrichissement Perplexity terminé")
        else:
            for lead in hit_leads:
                lead.setdefault("activity_summary", None)
                lead.setdefault("conversion_angle", None)
                lead.setdefault("digital_maturity", None)
                lead.setdefault("estimated_budget", None)
                lead.setdefault("business_signals", None)

        new_loop.close()

        # ── Export CSV ────────────────────────────────────────────────────────
        os.makedirs(pipeline_config.OUTPUT_DIR, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        csv_filename = f"leads_final_{ts}_{job_id[:8]}.csv"
        csv_path = os.path.join(pipeline_config.OUTPUT_DIR, csv_filename)

        CSV_COLUMNS = [
            "first_name", "last_name", "company", "job_title", "location",
            "email", "phone", "linkedin_url", "website",
            "hit_score", "is_hit",
            "icp_score", "icp_tier", "icp_rationale", "icp_scores_detail",
            "activity_summary", "conversion_angle",
            "digital_maturity", "estimated_budget", "business_signals",
            "is_duplicate", "first_seen_at",
        ]
        df = pd.DataFrame(leads)
        for col in CSV_COLUMNS:
            if col not in df.columns:
                df[col] = None
        df[CSV_COLUMNS].to_csv(csv_path, index=False, encoding="utf-8-sig")

        # ── Register leads for deduplication ─────────────────────────────
        try:
            from api.leads_db import register_leads
            register_leads(job_id, leads)
        except Exception:
            pass  # dedup is best-effort

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
            icp_hot_count=sum(1 for l in leads if l.get("icp_tier") == "hot"),
            icp_warm_count=sum(1 for l in leads if l.get("icp_tier") == "warm"),
            icp_cold_count=sum(1 for l in leads if l.get("icp_tier") == "cold"),
        )

        # ── Executive summary (Claude) ───────────────────────────────────────
        executive_summary = None
        if not skip_gpt and not pipeline_config._is_placeholder(pipeline_config.ANTHROPIC_API_KEY):
            try:
                import anthropic as _anth
                _summary_client = _anth.Anthropic(api_key=pipeline_config.ANTHROPIC_API_KEY)

                # Build context for summary
                hot_count = sum(1 for l in leads if l.get("icp_tier") == "hot")
                warm_count = sum(1 for l in leads if l.get("icp_tier") == "warm")
                cold_count = sum(1 for l in leads if l.get("icp_tier") == "cold")
                top_companies = [l.get("company", "?") for l in leads if l.get("icp_tier") == "hot"][:10]
                sectors = {}
                for l in leads:
                    s = (l.get("job_title") or "").split("/")[0].split(",")[0].strip()
                    if s:
                        sectors[s] = sectors.get(s, 0) + 1

                summary_prompt = f"""Génère un résumé exécutif en 4-5 phrases pour ce run de lead generation.

Données :
- {total} prospects analysés
- {len(hit_leads)} leads qualifiés (hit score >= seuil)
- {len(nohit_leads)} non qualifiés
- ICP : {hot_count} haute pertinence, {warm_count} pertinence moyenne, {cold_count} faible pertinence
- Taux d'emails trouvés : {stats.email_pct}%
- Taux LinkedIn trouvés : {stats.linkedin_pct}%
- Score moyen : {stats.avg_score}/100
- Top entreprises haute pertinence : {', '.join(top_companies[:5]) if top_companies else 'aucune'}
- Instructions utilisateur : {enrich_instructions or 'aucune instruction spécifique'}

Rédige un résumé actionnable en français. Mentionne les chiffres clés, les tendances, et une recommandation concrète de prochaine action. Pas de markdown, juste du texte."""

                msg = _summary_client.messages.create(
                    model="claude-haiku-4-5-20251001",
                    max_tokens=300,
                    messages=[{"role": "user", "content": summary_prompt}],
                )
                executive_summary = msg.content[0].text.strip()
                handler.set_explicit_progress(7, 1.0, "Résumé exécutif généré")
            except Exception as e:
                logging.getLogger("pipeline_runner").warning(f"Executive summary failed: {e}")

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
            executive_summary=executive_summary,
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

    except PipelineCancelled:
        _jobs[job_id] = JobResult(job_id=job_id, status="error", error="Annulé")
        from api.history import save_job as _save_hist
        meta = _job_meta.get(job_id, {})
        _save_hist(
            job_id=job_id, status="error",
            apollo_url=meta.get("apollo_url", ""),
            max_leads=meta.get("max_leads", 0),
            skip_gpt=meta.get("skip_gpt", False),
            started_at=meta.get("started_at", ""),
            finished_at=datetime.now().isoformat(),
            error="Annulé par l'utilisateur",
        )
        cancel_payload = json.dumps({"type": "cancelled", "data": {"job_id": job_id}})
        asyncio.run_coroutine_threadsafe(queue.put(cancel_payload), loop)
        _cancelled.pop(job_id, None)
        return  # skip the generic error handler

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


def start_job(url: str, max_leads: int, skip_gpt: bool, enrich_instructions: str = None) -> str:
    """Create a job, start the pipeline in background, return job_id."""
    job_id = str(uuid.uuid4())

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    queue: asyncio.Queue = asyncio.Queue()

    started_at = datetime.now().isoformat()

    _jobs[job_id] = JobResult(job_id=job_id, status="running")
    _queues[job_id] = queue
    _job_meta[job_id] = {
        "apollo_url": url,
        "max_leads": max_leads,
        "skip_gpt": skip_gpt,
        "started_at": started_at,
        "enrich_instructions": enrich_instructions or "",
    }

    # Persist running job to DB so it survives restarts
    from api.history import save_job as _save_hist
    _save_hist(
        job_id=job_id, status="running",
        apollo_url=url, max_leads=max_leads, skip_gpt=skip_gpt,
        started_at=started_at, finished_at="",
    )

    _executor.submit(
        _run_pipeline_sync,
        job_id, url, max_leads, skip_gpt, loop, queue,
        enrich_instructions or "",
    )

    return job_id


# ── Scrape-only pipeline ─────────────────────────────────────────────────────

def _run_scrape_only_sync(job_id: str, url: str, max_leads: int, pool_name: str,
                          loop: asyncio.AbstractEventLoop, queue: asyncio.Queue):
    """Runs steps 2-4 only (scrape + basic enrich + scoring). Stores leads in pool."""
    import asyncio as _asyncio

    handler = _QueueLogHandler(loop, queue, job_id)
    handler.setFormatter(logging.Formatter("%(message)s"))
    root_logger = logging.getLogger()
    saved_level = root_logger.level
    root_logger.setLevel(logging.DEBUG)
    root_logger.addHandler(handler)

    try:
        _jobs[job_id].status = "running"

        from enrichers.google_search import _reset_state as _reset_google
        from enrichers.dropcontact import _reset_state as _reset_dc
        _reset_google()
        _reset_dc()

        new_loop = _asyncio.new_event_loop()
        _asyncio.set_event_loop(new_loop)

        # Step 2: Apollo scraping
        handler.set_explicit_progress(2, 0.0, "Lancement scraping Apollo...")
        from scrapers.apollo_scraper import scrape_apollo
        leads = new_loop.run_until_complete(scrape_apollo(url, max_leads=max_leads))
        if not leads:
            raise RuntimeError("No leads scraped from Apollo. Check cookies and URL.")
        handler.set_explicit_progress(2, 1.0, f"Scraping terminé — {len(leads)} leads extraits")
        _check_cancelled(job_id)

        # Step 3a: Google
        handler.set_explicit_progress(3, 0.0, "Enrichissement Google...")
        from enrichers.google_search import enrich_leads_google
        leads = enrich_leads_google(leads)
        handler.set_explicit_progress(3, 0.5, "Google terminé. Lancement Dropcontact...")

        # Step 3b: Dropcontact
        from enrichers.dropcontact import enrich_leads_dropcontact
        leads = enrich_leads_dropcontact(leads)
        handler.set_explicit_progress(3, 1.0, "Enrichissement contact terminé")
        _check_cancelled(job_id)

        # Step 4: Hit score
        handler.set_explicit_progress(4, 0.0, "Calcul des hit scores...")
        from processors.hit_calculator import score_all_leads
        hit_leads, nohit_leads = score_all_leads(leads)
        handler.set_explicit_progress(4, 1.0, f"{len(hit_leads)} hit leads, {len(nohit_leads)} no-hit")

        # Dedup
        try:
            from api.leads_db import check_duplicates
            known = check_duplicates(leads)
            for lead in leads:
                email = (lead.get("email") or "").strip().lower()
                lead["is_duplicate"] = bool(email and email in known)
                lead["first_seen_at"] = known.get(email, {}).get("first_seen_at") if lead["is_duplicate"] else None
        except Exception:
            for lead in leads:
                lead["is_duplicate"] = False
                lead["first_seen_at"] = None

        new_loop.close()

        # Store in pool
        from api.leads_db import create_pool, register_leads
        pool_id = create_pool(pool_name, url, job_id, leads)
        register_leads(job_id, leads)

        # Update job
        total = len(leads)
        _jobs[job_id] = JobResult(
            job_id=job_id, status="done",
            total_leads=total, hit_leads=len(hit_leads), nohit_leads=len(nohit_leads),
            leads=leads,
        )

        # Persist to history
        from api.history import save_job as _save_hist
        meta = _job_meta.get(job_id, {})
        _save_hist(
            job_id=job_id, status="done",
            apollo_url=url, max_leads=max_leads, skip_gpt=True,
            started_at=meta.get("started_at", ""),
            finished_at=datetime.now().isoformat(),
            total_leads=total, hit_leads=len(hit_leads), nohit_leads=len(nohit_leads),
        )

        done_payload = json.dumps({"type": "done", "data": {"job_id": job_id, "pool_id": pool_id}})
        asyncio.run_coroutine_threadsafe(queue.put(done_payload), loop)

    except PipelineCancelled:
        _jobs[job_id] = JobResult(job_id=job_id, status="error", error="Annulé")
        cancel_payload = json.dumps({"type": "cancelled", "data": {"job_id": job_id}})
        asyncio.run_coroutine_threadsafe(queue.put(cancel_payload), loop)
        _cancelled.pop(job_id, None)
        return

    except Exception as exc:
        error_msg = str(exc)
        _jobs[job_id] = JobResult(job_id=job_id, status="error", error=error_msg)
        error_payload = json.dumps({"type": "error", "data": {"message": error_msg}})
        asyncio.run_coroutine_threadsafe(queue.put(error_payload), loop)

    finally:
        root_logger.removeHandler(handler)
        root_logger.setLevel(saved_level)
        asyncio.run_coroutine_threadsafe(queue.put(None), loop)


def start_scrape_job(url: str, max_leads: int, pool_name: str) -> str:
    """Start a scrape-only job. Returns job_id."""
    job_id = str(uuid.uuid4())
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    queue: asyncio.Queue = asyncio.Queue()
    started_at = datetime.now().isoformat()

    _jobs[job_id] = JobResult(job_id=job_id, status="running")
    _queues[job_id] = queue
    _job_meta[job_id] = {"apollo_url": url, "max_leads": max_leads, "skip_gpt": True, "started_at": started_at}

    from api.history import save_job as _save_hist
    _save_hist(job_id=job_id, status="running", apollo_url=url, max_leads=max_leads, skip_gpt=True, started_at=started_at, finished_at="")

    _executor.submit(_run_scrape_only_sync, job_id, url, max_leads, pool_name, loop, queue)
    return job_id


# ── Enrich-only pipeline ─────────────────────────────────────────────────────

def _run_enrich_only_sync(job_id: str, pool_id: str, batch_size: int,
                          loop: asyncio.AbstractEventLoop, queue: asyncio.Queue):
    """Runs steps 5-7 (ICP + Claude + Perplexity) on leads from an existing pool."""
    import asyncio as _asyncio

    handler = _QueueLogHandler(loop, queue, job_id)
    handler.setFormatter(logging.Formatter("%(message)s"))
    root_logger = logging.getLogger()
    saved_level = root_logger.level
    root_logger.setLevel(logging.DEBUG)
    root_logger.addHandler(handler)

    try:
        _jobs[job_id].status = "running"

        from enrichers.gpt_enricher import _reset_state as _reset_gpt
        from enrichers.perplexity_enricher import _reset_state as _reset_perplexity
        from processors.icp_scorer import _reset_state as _reset_icp
        _reset_gpt()
        _reset_perplexity()
        _reset_icp()

        # Load unenriched hit leads from pool
        from api.leads_db import get_pool_leads, mark_leads_enriched
        leads = get_pool_leads(pool_id, only_hit=True, only_unenriched=True, limit=batch_size)

        if not leads:
            raise RuntimeError("Aucun lead hit non-enrichi dans ce pool.")

        lead_ids = [l["id"] for l in leads]
        handler.set_explicit_progress(5, 0.0, f"Enrichissement de {len(leads)} leads...")

        new_loop = _asyncio.new_event_loop()
        _asyncio.set_event_loop(new_loop)

        # Step 5: ICP scoring
        handler.set_explicit_progress(5, 0.0, "Scoring ICP en cours...")
        from processors.icp_scorer import score_leads_icp
        leads = score_leads_icp(leads)
        handler.set_explicit_progress(5, 1.0, "Scoring ICP terminé")
        _check_cancelled(job_id)

        # Step 6: Website scraping + Claude AI
        handler.set_explicit_progress(6, 0.0, "Scraping sites web...")
        from scrapers.website_scraper import scrape_hit_leads
        leads = new_loop.run_until_complete(scrape_hit_leads(leads))
        handler.set_explicit_progress(6, 0.5, "Appel Claude AI...")
        from enrichers.gpt_enricher import enrich_leads_gpt
        leads = enrich_leads_gpt(leads)
        handler.set_explicit_progress(6, 1.0, "Enrichissement IA terminé")
        _check_cancelled(job_id)

        # Step 7: Perplexity
        handler.set_explicit_progress(7, 0.0, "Enrichissement Perplexity...")
        from enrichers.perplexity_enricher import enrich_leads_perplexity
        leads = enrich_leads_perplexity(leads)
        handler.set_explicit_progress(7, 1.0, "Enrichissement Perplexity terminé")

        new_loop.close()

        # Store enrichment data back to pool
        enrich_data = {}
        enrich_fields = ["icp_score", "icp_tier", "icp_rationale", "icp_scores_detail",
                         "activity_summary", "conversion_angle",
                         "digital_maturity", "estimated_budget", "business_signals"]
        for i, lead in enumerate(leads):
            lid = lead_ids[i]
            enrich_data[lid] = {k: lead.get(k) for k in enrich_fields if lead.get(k) is not None}

        mark_leads_enriched(pool_id, lead_ids, job_id, enrich_data)

        # Export enriched leads to CSV
        os.makedirs(pipeline_config.OUTPUT_DIR, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        csv_filename = f"leads_enriched_{ts}_{job_id[:8]}.csv"
        csv_path = os.path.join(pipeline_config.OUTPUT_DIR, csv_filename)

        CSV_COLUMNS = [
            "first_name", "last_name", "company", "job_title", "location",
            "email", "phone", "linkedin_url", "website",
            "hit_score", "is_hit",
            "icp_score", "icp_tier", "icp_rationale", "icp_scores_detail",
            "activity_summary", "conversion_angle",
            "digital_maturity", "estimated_budget", "business_signals",
        ]
        df = pd.DataFrame(leads)
        for col in CSV_COLUMNS:
            if col not in df.columns:
                df[col] = None
        df[CSV_COLUMNS].to_csv(csv_path, index=False, encoding="utf-8-sig")

        _jobs[job_id] = JobResult(
            job_id=job_id, status="done",
            total_leads=len(leads), hit_leads=len(leads), nohit_leads=0,
            leads=leads, csv_path=csv_path,
        )

        from api.history import save_job as _save_hist
        meta = _job_meta.get(job_id, {})
        _save_hist(
            job_id=job_id, status="done",
            apollo_url=f"pool:{pool_id}", max_leads=batch_size, skip_gpt=False,
            started_at=meta.get("started_at", ""),
            finished_at=datetime.now().isoformat(),
            total_leads=len(leads), hit_leads=len(leads),
            csv_filename=csv_filename,
        )

        done_payload = json.dumps({"type": "done", "data": {"job_id": job_id}})
        asyncio.run_coroutine_threadsafe(queue.put(done_payload), loop)

    except PipelineCancelled:
        _jobs[job_id] = JobResult(job_id=job_id, status="error", error="Annulé")
        cancel_payload = json.dumps({"type": "cancelled", "data": {"job_id": job_id}})
        asyncio.run_coroutine_threadsafe(queue.put(cancel_payload), loop)
        _cancelled.pop(job_id, None)
        return

    except Exception as exc:
        error_msg = str(exc)
        _jobs[job_id] = JobResult(job_id=job_id, status="error", error=error_msg)
        error_payload = json.dumps({"type": "error", "data": {"message": error_msg}})
        asyncio.run_coroutine_threadsafe(queue.put(error_payload), loop)

    finally:
        root_logger.removeHandler(handler)
        root_logger.setLevel(saved_level)
        asyncio.run_coroutine_threadsafe(queue.put(None), loop)


def start_enrich_job(pool_id: str, batch_size: int) -> str:
    """Start an enrich-only job on an existing pool. Returns job_id."""
    job_id = str(uuid.uuid4())
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    queue: asyncio.Queue = asyncio.Queue()
    started_at = datetime.now().isoformat()

    _jobs[job_id] = JobResult(job_id=job_id, status="running")
    _queues[job_id] = queue
    _job_meta[job_id] = {"apollo_url": f"pool:{pool_id}", "max_leads": batch_size, "skip_gpt": False, "started_at": started_at}

    _executor.submit(_run_enrich_only_sync, job_id, pool_id, batch_size, loop, queue)
    return job_id
