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
from urllib.parse import urlparse

import pandas as pd

# Add project root to path so pipeline modules are importable
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import config as pipeline_config
from api import quota_db
from api.models import JobResult, JobStats, ProgressEvent
# Imported at module level, not inside the run functions: the `except
# ProviderFailure` clauses below must resolve the name even when the failure
# happens before the function body reaches its own imports.
from api.provider_status import ProviderFailure, ProviderRegistry, StepOutcome
from lead_schema import CSV_COLUMNS, ENRICH_FIELDS

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
# Rebalanced for the free cascade: Apollo and the site crawl now carry most of
# the work, while the former "Dropcontact batch" step is gone. Weights reflect
# observed wall-clock, not importance.
STEP_WEIGHTS = {1: 0.03, 2: 0.17, 3: 0.12, 4: 0.18, 5: 0.05, 6: 0.15,
                7: 0.18, 8: 0.05, 9: 0.07}
STEP_NAMES = {
    1: "Entrée Apollo",
    2: "Scraping Apollo",
    3: "LinkedIn et site web",
    4: "Extraction des contacts du site",
    5: "Pré-score et priorisation",
    6: "Cascade email",
    7: "Collecte de preuves (site + Perplexity)",
    8: "Extraction de faits et scoring ICP",
    9: "Rédaction des angles commerciaux",
}

# Patterns to detect which step a log message belongs to
STEP_PATTERNS = [
    (2, re.compile(r"Step 2|Scraping Apollo|apollo|page \d+", re.I)),
    (3, re.compile(r"Step 3|Google enrichment|LinkedIn|website|Clearbit|Serper", re.I)),
    (4, re.compile(r"Step 4|Contact extraction|harvest|contact page|robots", re.I)),
    (5, re.compile(r"Step 5|[Pp]rescore|priorisation|ranking", re.I)),
    (6, re.compile(r"Step 6|cascade|Prospeo|GetProspect|Hunter|catch-all|MX|pattern", re.I)),
    (7, re.compile(r"Step 7|Evidence|Perplexity|Scraping hit lead", re.I)),
    (8, re.compile(r"Step 8|Fact extraction|ICP scoring", re.I)),
    (9, re.compile(r"Step 9|Angle writing", re.I)),
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


# ── Executive summary prompt ──────────────────────────────────────────────────

# Providers whose degradation changes how the run's numbers should be read.
_PROVIDER_LABELS = {
    "hunter": "Hunter.io (recherche et vérification d'emails)",
    "prospeo": "Prospeo (recherche d'emails)",
    "getprospect": "GetProspect (recherche d'emails)",
    "getprospect_verify": "GetProspect (vérification d'emails)",
    "serper": "Serper (recherche LinkedIn)",
    "website": "Scraping des sites web",
    "perplexity": "Perplexity (signaux business)",
    "anthropic_facts": "Extraction de faits",
    "anthropic_angles": "Rédaction des angles",
}


def _build_summary_prompt(
    leads: list[dict],
    reachable_count: int,
    unreachable_count: int,
    pending_count: int,
    stats: JobStats,
    enrich_instructions: str = "",
    provider_status: Optional[dict] = None,
) -> str:
    """Build the executive-summary prompt from a finished run's numbers.

    Pure function, no I/O: the summary is the one artefact the operator reads
    before anything else, and a portfolio that silently loses thirty
    disqualified leads out of fifty is a reporting bug worth pinning in tests.

    Four things the model must never have to infer:
      - disqualified leads exist and are counted (they are neither hot, warm
        nor cold, so a three-tier breakdown makes them vanish);
      - unverified leads are unverified, not merely low-scoring;
      - a degraded provider makes the numbers themselves unreliable;
      - pending_quota leads were never asked the question at all, so the
        reachable/unreachable split does not include them — a run that ran
        out of credits on 40 leads must not read as a poor find rate.
    """
    total = len(leads)
    icp_scored = any(l.get("icp_tier") for l in leads)
    top_companies = [l.get("company", "?") for l in leads if l.get("icp_tier") == "hot"][:10]
    unverified = sum(1 for l in leads if l.get("evidence_verified") is False)

    data_lines = [
        f"- {total} prospects analysés",
        f"- {reachable_count} leads joignables",
        f"- {unreachable_count} non joignables",
    ]
    if pending_count:
        data_lines.append(
            f"- {pending_count} leads en attente de quota : aucun fournisseur "
            f"n'avait de crédit disponible. Ils ne sont pas écartés et repasseront "
            f"en priorité au prochain reset mensuel."
        )
    if stats.email_by_source:
        described = ", ".join(f"{src} : {n}" for src, n in sorted(
            stats.email_by_source.items(), key=lambda kv: -kv[1]))
        data_lines.append(f"- Emails trouvés par source — {described}")
    if icp_scored:
        data_lines.append(
            f"- ICP : {stats.icp_hot_count} haute pertinence, "
            f"{stats.icp_warm_count} pertinence moyenne, "
            f"{stats.icp_cold_count} faible pertinence, "
            f"{stats.icp_disqualified_count} disqualifiés"
        )
        data_lines.append(
            f"- {unverified} leads non vérifiés (preuves insuffisantes, "
            f"qualification manuelle nécessaire)"
        )
    else:
        data_lines.append(
            "- Scoring ICP : non calculé sur ce run (aucun lead qualifié à scorer)"
        )
    data_lines += [
        f"- Taux d'emails trouvés : {stats.email_pct}%",
        f"- Taux LinkedIn trouvés : {stats.linkedin_pct}%",
        f"- Pré-score moyen : {stats.avg_score}/60",
    ]
    if icp_scored:
        data_lines.append(
            f"- Top entreprises haute pertinence : "
            f"{', '.join(top_companies[:5]) if top_companies else 'aucune'}"
        )

    impaired = [
        (name, entry) for name, entry in (provider_status or {}).items()
        if isinstance(entry, dict) and entry.get("status") in ("failed", "degraded")
    ]
    if impaired:
        described = "; ".join(
            f"{_PROVIDER_LABELS.get(name, name)} — "
            f"{'en échec' if entry.get('status') == 'failed' else 'dégradé'}"
            f"{': ' + entry['reason'] if entry.get('reason') else ''}"
            for name, entry in impaired
        )
        data_lines.append(f"- Fournisseurs en difficulté sur ce run : {described}")

    data_lines.append(
        f"- Instructions utilisateur : {enrich_instructions or 'aucune instruction spécifique'}"
    )

    icp_writing_instruction = (
        "" if icp_scored else
        " Ne commente pas la pertinence ICP des leads : le scoring n'a pas été calculé sur ce run."
    )
    provider_writing_instruction = (
        " Signale explicitement que des fournisseurs ont été dégradés ou en échec "
        "et que les chiffres ci-dessus en sont affectés."
        if impaired else ""
    )
    pending_writing_instruction = (
        " Mentionne explicitement les leads en attente de quota : ils ne sont ni "
        "qualifiés ni disqualifiés, et les taux ci-dessus ne les comptent pas."
        if pending_count else ""
    )

    return (
        "Génère un résumé exécutif en 4-5 phrases pour ce run de lead generation.\n\n"
        "Données :\n" + "\n".join(data_lines) + "\n\n"
        "Rédige un résumé actionnable en français. Mentionne les chiffres clés, les tendances, "
        "et une recommandation concrète de prochaine action."
        + icp_writing_instruction
        + provider_writing_instruction
        + pending_writing_instruction
        + " Pas de markdown, juste du texte."
    )


# ── Run statistics ───────────────────────────────────────────────────────────

def compute_stats(leads: list[dict]) -> JobStats:
    """Aggregate one run's outcome, including where each email came from.

    The per-source breakdown is what tells the operator whether the free
    branches are carrying their weight: a month where everything came from
    finders means the site crawl or the pattern generator has regressed, and
    the credits will run out long before the leads do.
    """
    total = len(leads)
    if not total:
        return JobStats()

    def pct(field):
        return round(100 * sum(1 for l in leads if l.get(field)) / total, 1)

    def cnt(field):
        return sum(1 for l in leads if l.get(field))

    by_source: dict[str, int] = {}
    for lead in leads:
        source = lead.get("email_source")
        if source and lead.get("email"):
            by_source[source] = by_source.get(source, 0) + 1

    quotas = {
        name: {"remaining": quota_db.get_quota(name)["remaining"],
               "allocation": quota_db.get_quota(name)["allocation"]}
        for name in pipeline_config.PROVIDER_ALLOCATIONS
    }

    return JobStats(
        email_pct=pct("email"), linkedin_pct=pct("linkedin_url"),
        phone_pct=pct("phone"), website_pct=pct("website"),
        email_count=cnt("email"), linkedin_count=cnt("linkedin_url"),
        phone_count=cnt("phone"), website_count=cnt("website"),
        email_by_source=by_source,
        mobile_count=sum(1 for l in leads if l.get("phone_type") == "mobile"),
        whatsapp_count=sum(1 for l in leads if l.get("whatsapp")),
        pending_quota_count=sum(1 for l in leads if l.get("email_status") == "pending_quota"),
        reachable_count=sum(1 for l in leads if l.get("reachable") is True),
        avg_score=round(sum(l.get("prescore") or 0 for l in leads) / total, 1),
        icp_hot_count=sum(1 for l in leads if l.get("icp_tier") == "hot"),
        icp_warm_count=sum(1 for l in leads if l.get("icp_tier") == "warm"),
        icp_cold_count=sum(1 for l in leads if l.get("icp_tier") == "cold"),
        icp_disqualified_count=sum(1 for l in leads if l.get("icp_tier") == "disqualified"),
        provider_credits=quotas,
    )


# ── Pipeline execution ────────────────────────────────────────────────────────

def _export_csv(leads: list[dict], filename: str) -> str:
    """Write one CSV under OUTPUT_DIR using the shared column order."""
    os.makedirs(pipeline_config.OUTPUT_DIR, exist_ok=True)
    path = os.path.join(pipeline_config.OUTPUT_DIR, filename)
    df = pd.DataFrame(leads)
    for col in CSV_COLUMNS:
        if col not in df.columns:
            df[col] = None
    df[CSV_COLUMNS].to_csv(path, index=False, encoding="utf-8-sig")
    return path


def _apply_suppression_filter(leads: list[dict]) -> tuple[list[dict], list[dict]]:
    """Split off suppressed leads before any enrichment, free or paid.

    An existing BoxCom client or an opt-out must never reach a finder, or
    even the free cascade: contacting them is at best wasteful and at worst
    a breach of an explicit request (see api/suppression_db.py). Suppressed
    leads are returned separately, marked reachable=False, rather than
    silently dropped: a pool lead must not vanish without a trace.
    """
    from api.suppression_db import is_suppressed
    for lead in leads:
        motif = is_suppressed(lead)
        if motif:
            lead["email_status"] = "not_found"
            lead["suppression_reason"] = motif
            lead["reachable"] = False
            lead["contact_level"] = "aucun"
    kept = [l for l in leads if not l.get("suppression_reason")]
    suppressed = [l for l in leads if l.get("suppression_reason")]
    return kept, suppressed


def _harvest_lead_contacts(lead: dict) -> None:
    """Free Step 4, for one lead: crawl its own site for phone/social/emails.

    Everything the pool has a column for — phone, social handles, the
    domain's MX provider — is written onto the lead directly. The raw email
    candidate list is kept too (lead["_site_contacts"]) for the cascade to
    consume later in the same run, but it is not one of the pool's columns:
    a lead loaded back from a pool (the enrich-only path) rebuilds it fresh
    instead — see _refresh_site_contacts.
    """
    from enrichers.contact_extractor import harvest_contacts
    from enrichers.phone_extractor import best_phone
    from enrichers import domain_intel

    page = lead.pop("_page_fetch", None)
    contacts = harvest_contacts(lead, page)
    lead["_site_contacts"] = contacts

    phone = best_phone(contacts.get("phones") or [])
    if phone:
        lead["phone"] = phone.e164
        lead["phone_type"] = phone.kind
        lead["phone_source"] = phone.source_url

    social = contacts.get("social") or {}
    lead["whatsapp"] = bool(social.get("whatsapp"))
    lead["facebook_url"] = social.get("facebook_url")
    lead["instagram_url"] = social.get("instagram_url")
    lead["linkedin_company_url"] = social.get("linkedin_company_url")

    domain = urlparse(lead.get("website") or "").netloc.lower().removeprefix("www.")
    lead["domain_mx_provider"] = domain_intel.lookup_mx(domain).provider if domain else None


def _refresh_site_contacts(lead: dict) -> None:
    """Rebuild a pool lead's site contacts right before the cascade needs them.

    Pools persist scalar columns only (see api.leads_db._LEAD_POOL_ADDED_COLUMNS);
    the raw ExtractedEmail list that resolve_email's branches (a)/(b) read is
    not one of them. Re-harvesting it here costs nothing — it is the same
    free homepage fetch _harvest_lead_contacts already made — and avoids
    growing the pool schema to cache a blob only the cascade itself consumes.
    """
    if lead.get("_site_contacts") is not None:
        return  # already populated in this process (full-pipeline run)
    from enrichers.contact_extractor import harvest_contacts
    from enrichers.google_search import verify_website
    website = lead.get("website")
    if not website:
        lead["_site_contacts"] = {"emails": [], "phones": []}
        return
    try:
        _coherence, page = verify_website(website, lead.get("company") or "")
        lead["_site_contacts"] = harvest_contacts(lead, page)
    except Exception as exc:
        logging.getLogger("pipeline_runner").debug(
            f"Site contact refresh failed for {website}: {exc}"
        )
        lead["_site_contacts"] = {"emails": [], "phones": []}


def _dedupe_leads(leads: list[dict], job_id: str) -> None:
    """Flag is_duplicate/first_seen_at using the multi-key dedupe (most leads
    out of the free cascade have no email — see api.leads_db.dedupe_key) and
    register every lead for future runs. Best-effort: a DB hiccup must not
    fail the run over a bookkeeping step."""
    log = logging.getLogger("pipeline_runner")
    try:
        from api.leads_db import check_duplicates, dedupe_key, register_leads
        known = check_duplicates(leads)
        new_count = 0
        for lead in leads:
            key = dedupe_key(lead)
            if key != ("", "") and key in known:
                lead["is_duplicate"] = True
                lead["first_seen_at"] = known[key].get("first_seen_at")
            else:
                lead["is_duplicate"] = False
                lead["first_seen_at"] = None
                if key != ("", ""):
                    new_count += 1
        register_leads(job_id, leads)
        log.info(f"{new_count} nouveaux leads, {len(known)} déjà vus")
    except Exception as exc:
        log.warning(f"Dedup bookkeeping failed (best-effort): {exc}")
        for lead in leads:
            lead.setdefault("is_duplicate", False)
            lead.setdefault("first_seen_at", None)


def _run_pipeline_sync(job_id: str, url: str, max_leads: int, skip_gpt: bool,
                       loop: asyncio.AbstractEventLoop, queue: asyncio.Queue,
                       enrich_instructions: str = ""):
    """
    Runs the full pipeline synchronously in a thread: the free side (Apollo,
    LinkedIn/site, contact harvesting, pre-score) chained straight into the
    paid side (cascade, reachability, evidence, facts, ICP, angles) — the
    same split /api/scrape and /api/enrich expose separately (§10).
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

        registry = ProviderRegistry()

        # Reset enricher state from any previous run
        from enrichers.google_search import _reset_state as _reset_google
        from enrichers.perplexity_enricher import _reset_state as _reset_perplexity
        from enrichers.fact_extractor import _reset_state as _reset_facts
        from enrichers.angle_writer import _reset_state as _reset_angles
        from enrichers import domain_intel
        _reset_google()
        _reset_perplexity()
        _reset_facts()
        _reset_angles()
        domain_intel.reset_caches()

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

        # Apollo scraping was the only consumer of this loop. Every remaining
        # step below is sync, so new_loop is closed here rather than left
        # dangling as the thread's "current" loop.
        new_loop.close()

        # ── Step 3: LinkedIn and website + coherence ───────────────────────────
        handler.set_explicit_progress(3, 0.0, "Recherche LinkedIn et site web...")
        from enrichers.google_search import enrich_leads_google
        leads = enrich_leads_google(leads, registry=registry)
        handler.set_explicit_progress(
            3, 1.0,
            f"{sum(1 for l in leads if l.get('linkedin_url'))}/{len(leads)} LinkedIn, "
            f"{sum(1 for l in leads if l.get('website'))}/{len(leads)} sites web"
        )
        _check_cancelled(job_id)

        # ── Step 4: site contact extraction ───────────────────────────
        handler.set_explicit_progress(4, 0.0, "Extraction des contacts du site...")
        for lead in leads:
            _harvest_lead_contacts(lead)
        published = sum(1 for l in leads if (l.get("_site_contacts") or {}).get("emails"))
        handler.set_explicit_progress(4, 1.0, f"{published}/{len(leads)} sites avec email publié")
        _check_cancelled(job_id)

        # ── Step 5: pre-score and prioritization ─────────────────────────────────
        handler.set_explicit_progress(5, 0.0, "Calcul du pre-score...")
        from processors.prescore import apply_prescores, rank_for_spending
        apply_prescores(leads)
        handler.set_explicit_progress(5, 1.0, "Pré-score calculé")

        # ── Suppression and dedup, before any enrichment ────────
        leads, suppressed = _apply_suppression_filter(leads)
        if suppressed:
            logging.getLogger("pipeline_runner").info(
                f"{len(suppressed)} lead(s) écarté(s) — liste de suppression"
            )
        _dedupe_leads(leads, job_id)
        _check_cancelled(job_id)

        # ── Step 6: email cascade ──────────────────────────────────────────────
        handler.set_explicit_progress(6, 0.0, "Synchronisation des quotas fournisseurs...")
        from enrichers.providers.quota_sync import sync_all
        sync_all(registry)

        # Finder credits go to the head of the queue, not to whoever happens
        # to be scraped first (§7).
        ranked = rank_for_spending(leads)
        budget = sum(quota_db.get_quota(p)["remaining"] for p in ("prospeo", "getprospect", "hunter"))
        from enrichers.email_cascade import resolve_email
        for position, lead in enumerate(ranked):
            _check_cancelled(job_id)
            resolve_email(lead, is_priority=position < budget, registry=registry)
        leads = ranked
        handler.set_explicit_progress(6, 1.0, "Cascade email terminée")

        # ── Reachability: reachable / unreachable / pending_quota ────────────
        from processors.hit_calculator import score_all_leads
        reachable_leads, unreachable_leads, pending_leads = score_all_leads(leads)
        unreachable_leads = unreachable_leads + suppressed
        handler.set_explicit_progress(
            6, 1.0,
            f"{len(reachable_leads)} joignables / {len(unreachable_leads)} non joignables / "
            f"{len(pending_leads)} en attente de quota"
        )

        # ── Steps 7-9: evidence, facts, ICP scoring, angles (reachable only) ───────
        if not skip_gpt and reachable_leads:
            handler.set_explicit_progress(7, 0.0, "Collecte de preuves (sites web + Perplexity)...")
            from enrichers.evidence_collector import collect_evidence
            reachable_leads, active_providers = collect_evidence(
                reachable_leads, enrich_instructions, registry=registry
            )
            handler.set_explicit_progress(7, 1.0, "Collecte de preuves terminée")
            _check_cancelled(job_id)

            handler.set_explicit_progress(8, 0.0, "Extraction des faits et scoring ICP...")
            from enrichers.fact_extractor import extract_leads_facts
            reachable_leads = extract_leads_facts(reachable_leads, active_providers, registry=registry)
            confirmed = sum(1 for l in reachable_leads if (l.get("facts") or {}).get("identite_confirmee"))
            from processors.icp_scorer import apply_scores
            reachable_leads = apply_scores(reachable_leads)
            disq = sum(1 for l in reachable_leads if l.get("icp_tier") == "disqualified")
            handler.set_explicit_progress(
                8, 1.0,
                f"{confirmed}/{len(reachable_leads)} identités confirmées — "
                f"{disq} lead(s) disqualifié(s)"
            )
            _check_cancelled(job_id)

            handler.set_explicit_progress(9, 0.0, "Rédaction des angles commerciaux...")
            from enrichers.angle_writer import write_leads_angles
            reachable_leads = write_leads_angles(reachable_leads, enrich_instructions, registry=registry)
            handler.set_explicit_progress(9, 1.0, "Rédaction terminée")
        else:
            # An AI half that never ran must say so. Left unrecorded, the
            # three steps were simply absent from provider_status, which reads
            # the same as a run where they all worked.
            if skip_gpt:
                for step in ("perplexity", "anthropic_facts", "anthropic_angles"):
                    registry.record(StepOutcome(step, "skipped", "recherche IA désactivée", 0))
            for lead in reachable_leads:
                lead.setdefault("icp_score", None)
                lead.setdefault("icp_tier", None)
                lead.setdefault("icp_rationale", None)
                lead.setdefault("icp_scores_detail", None)
                lead.setdefault("disqualification_reason", None)
                lead.setdefault("evidence_level", None)
                lead.setdefault("evidence_verified", None)
                lead.setdefault("facts_json", None)
                lead.setdefault("activity_summary", None)
                lead.setdefault("conversion_angle", None)
                lead.setdefault("digital_maturity", None)
                lead.setdefault("estimated_budget", None)
                lead.setdefault("business_signals", None)

        leads = reachable_leads + unreachable_leads + pending_leads

        # ── Export CSV ────────────────────────────────────────────────────────
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        csv_filename = f"leads_final_{ts}_{job_id[:8]}.csv"
        csv_path = _export_csv(leads, csv_filename)

        # pending_quota leads never had their question answered — they are
        # not no-hit, and mixing them into the main export would read as a
        # poor find rate rather than an exhausted month (§11).
        if pending_leads:
            pending_path = _export_csv(pending_leads, f"leads_pending_quota_{ts}_{job_id[:8]}.csv")
            logging.getLogger("pipeline_runner").info(f"Pending-quota CSV saved: {pending_path}")

        # ── Compute stats ─────────────────────────────────────────────────────
        total = len(leads)
        stats = compute_stats(leads)

        # ── Executive summary (Claude) ───────────────────────────────────────
        executive_summary = None
        if not skip_gpt and not pipeline_config._is_placeholder(pipeline_config.ANTHROPIC_API_KEY):
            try:
                import anthropic as _anth
                _summary_client = _anth.Anthropic(api_key=pipeline_config.ANTHROPIC_API_KEY)

                summary_prompt = _build_summary_prompt(
                    leads=leads,
                    reachable_count=len(reachable_leads),
                    unreachable_count=len(unreachable_leads),
                    pending_count=len(pending_leads),
                    stats=stats,
                    enrich_instructions=enrich_instructions,
                    provider_status=registry.to_dict(),
                )

                msg = _summary_client.messages.create(
                    model="claude-haiku-4-5-20251001",
                    max_tokens=300,
                    messages=[{"role": "user", "content": summary_prompt}],
                )
                executive_summary = msg.content[0].text.strip()
                handler.set_explicit_progress(9, 1.0, "Résumé exécutif généré")
            except Exception as e:
                logging.getLogger("pipeline_runner").warning(f"Executive summary failed: {e}")

        # ── Update job state ──────────────────────────────────────────────────
        # The same status goes to the in-memory job and to the history row: a
        # run that lost its contacts must not sit in the history as a plain
        # green "done" forever.
        final_status = "completed_with_errors" if registry.has_critical_failure() else "done"
        _jobs[job_id] = JobResult(
            job_id=job_id,
            status=final_status,
            total_leads=total,
            hit_leads=len(reachable_leads),
            nohit_leads=len(unreachable_leads),
            pending_quota_leads=len(pending_leads),
            stats=stats,
            leads=leads,
            csv_path=csv_path,
            executive_summary=executive_summary,
            provider_status=registry.to_dict(),
        )

        # ── Persist to history DB ────────────────────────────────────────────
        from api.history import save_job as _save_hist
        meta = _job_meta.get(job_id, {})
        _save_hist(
            job_id=job_id, status=final_status,
            apollo_url=meta.get("apollo_url", ""),
            max_leads=meta.get("max_leads", 0),
            skip_gpt=meta.get("skip_gpt", False),
            started_at=meta.get("started_at", ""),
            finished_at=datetime.now().isoformat(),
            total_leads=total,
            hit_leads=len(reachable_leads),
            nohit_leads=len(unreachable_leads),
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

    except ProviderFailure as exc:
        message = f"Étape contacts interrompue — {exc.reason}"
        logging.getLogger("pipeline_runner").error(message)
        _jobs[job_id] = JobResult(job_id=job_id, status="error", error=message)
        from api.history import save_job as _save_hist
        meta = _job_meta.get(job_id, {})
        _save_hist(
            job_id=job_id, status="error",
            apollo_url=meta.get("apollo_url", ""),
            max_leads=meta.get("max_leads", 0),
            skip_gpt=meta.get("skip_gpt", False),
            started_at=meta.get("started_at", ""),
            finished_at=datetime.now().isoformat(),
            error=message,
        )
        error_payload = json.dumps({"type": "error", "data": {"message": message}})
        asyncio.run_coroutine_threadsafe(queue.put(error_payload), loop)
        return

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
    """Runs the free side only (§10): Apollo, LinkedIn/site + coherence,
    contact harvesting, MX lookup, pre-score, suppression and dedup. Stores
    the resulting pool. Never calls the cascade, Perplexity or Claude —
    those belong to /api/enrich, the paid side of the split."""
    import asyncio as _asyncio

    handler = _QueueLogHandler(loop, queue, job_id)
    handler.setFormatter(logging.Formatter("%(message)s"))
    root_logger = logging.getLogger()
    saved_level = root_logger.level
    root_logger.setLevel(logging.DEBUG)
    root_logger.addHandler(handler)

    try:
        _jobs[job_id].status = "running"

        registry = ProviderRegistry()

        from enrichers.google_search import _reset_state as _reset_google
        from enrichers import domain_intel
        _reset_google()
        domain_intel.reset_caches()

        new_loop = _asyncio.new_event_loop()
        _asyncio.set_event_loop(new_loop)

        # ── Step 2: Apollo scraping ────────────────────────────────────────
        handler.set_explicit_progress(2, 0.0, "Lancement scraping Apollo...")
        from scrapers.apollo_scraper import scrape_apollo
        leads = new_loop.run_until_complete(scrape_apollo(url, max_leads=max_leads))
        if not leads:
            raise RuntimeError("No leads scraped from Apollo. Check cookies and URL.")
        handler.set_explicit_progress(2, 1.0, f"Scraping terminé — {len(leads)} leads extraits")
        _check_cancelled(job_id)
        new_loop.close()

        # ── Step 3: LinkedIn and website + coherence ─────────────────────────
        handler.set_explicit_progress(3, 0.0, "Recherche LinkedIn et site web...")
        from enrichers.google_search import enrich_leads_google
        leads = enrich_leads_google(leads, registry=registry)
        handler.set_explicit_progress(
            3, 1.0,
            f"{sum(1 for l in leads if l.get('linkedin_url'))}/{len(leads)} LinkedIn, "
            f"{sum(1 for l in leads if l.get('website'))}/{len(leads)} sites web"
        )
        _check_cancelled(job_id)

        # ── Step 4: site contact extraction + MX ─────────────────────
        handler.set_explicit_progress(4, 0.0, "Extraction des contacts du site...")
        for lead in leads:
            _harvest_lead_contacts(lead)
        published = sum(1 for l in leads if (l.get("_site_contacts") or {}).get("emails"))
        handler.set_explicit_progress(4, 1.0, f"{published}/{len(leads)} sites avec email publié")
        _check_cancelled(job_id)

        # ── Step 5: pre-score ─────────────────────────────────────────────────
        handler.set_explicit_progress(5, 0.0, "Calcul du pre-score...")
        from processors.prescore import apply_prescores
        apply_prescores(leads)
        handler.set_explicit_progress(5, 1.0, "Pré-score calculé")

        # ── Suppression and dedup ───────────────────────────────────
        leads, suppressed = _apply_suppression_filter(leads)
        if suppressed:
            logging.getLogger("pipeline_runner").info(
                f"{len(suppressed)} lead(s) écarté(s) — liste de suppression"
            )
            leads = leads + suppressed  # kept in the pool, just pre-flagged
        _dedupe_leads(leads, job_id)

        # ── Store in pool ────────────────────────────────────────────────────
        from api.leads_db import create_pool
        pool_id = create_pool(pool_name, url, job_id, leads)

        total = len(leads)
        final_status = "completed_with_errors" if registry.has_critical_failure() else "done"
        _jobs[job_id] = JobResult(
            job_id=job_id,
            status=final_status,
            total_leads=total,
            leads=leads,
            provider_status=registry.to_dict(),
        )

        # Persist to history
        from api.history import save_job as _save_hist
        meta = _job_meta.get(job_id, {})
        _save_hist(
            job_id=job_id, status=final_status,
            apollo_url=url, max_leads=max_leads, skip_gpt=True,
            started_at=meta.get("started_at", ""),
            finished_at=datetime.now().isoformat(),
            total_leads=total,
        )

        done_payload = json.dumps({"type": "done", "data": {"job_id": job_id, "pool_id": pool_id}})
        asyncio.run_coroutine_threadsafe(queue.put(done_payload), loop)

    except PipelineCancelled:
        _jobs[job_id] = JobResult(job_id=job_id, status="error", error="Annulé")
        cancel_payload = json.dumps({"type": "cancelled", "data": {"job_id": job_id}})
        asyncio.run_coroutine_threadsafe(queue.put(cancel_payload), loop)
        _cancelled.pop(job_id, None)
        return

    except ProviderFailure as exc:
        message = f"Étape contacts interrompue — {exc.reason}"
        logging.getLogger("pipeline_runner").error(message)
        _jobs[job_id] = JobResult(job_id=job_id, status="error", error=message)
        error_payload = json.dumps({"type": "error", "data": {"message": message}})
        asyncio.run_coroutine_threadsafe(queue.put(error_payload), loop)
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
                          loop: asyncio.AbstractEventLoop, queue: asyncio.Queue,
                          enrich_instructions: str = ""):
    """Runs the paid side (§10): quota sync, a batch selected by descending
    pre-score, the email cascade, reachability, then evidence + facts + ICP
    scoring + angle writing (steps 6 to 9) on leads already scraped for free
    and sitting in an existing pool."""
    handler = _QueueLogHandler(loop, queue, job_id)
    handler.setFormatter(logging.Formatter("%(message)s"))
    root_logger = logging.getLogger()
    saved_level = root_logger.level
    root_logger.setLevel(logging.DEBUG)
    root_logger.addHandler(handler)

    try:
        _jobs[job_id].status = "running"

        registry = ProviderRegistry()

        from enrichers.perplexity_enricher import _reset_state as _reset_perplexity
        from enrichers.fact_extractor import _reset_state as _reset_facts
        from enrichers.angle_writer import _reset_state as _reset_angles
        from enrichers import domain_intel
        _reset_perplexity()
        _reset_facts()
        _reset_angles()
        domain_intel.reset_caches()

        # ── Quota sync — always free, always run before spending a credit ────
        handler.set_explicit_progress(6, 0.0, "Synchronisation des quotas fournisseurs...")
        from enrichers.providers.quota_sync import sync_all
        sync_all(registry)

        # Batch selected by descending pre-score; pending_quota leads from a
        # previous reset sort first (see api.leads_db.get_pool_leads).
        from api.leads_db import (
            CASCADE_POOL_COLUMNS, get_pool_leads, mark_leads_enriched, update_cascade_columns,
        )
        batch = get_pool_leads(pool_id, only_unenriched=True, limit=batch_size)
        if not batch:
            raise RuntimeError("Aucun lead non-enrichi dans ce pool.")

        # ── Suppression, before a single credit is spent ─────────────────────
        leads, suppressed = _apply_suppression_filter(batch)
        if suppressed:
            logging.getLogger("pipeline_runner").info(
                f"{len(suppressed)} lead(s) écarté(s) — liste de suppression"
            )

        # ── Step 6: email cascade ─────────────────────────────────────────────
        handler.set_explicit_progress(6, 0.0, f"Cascade email sur {len(leads)} lead(s)...")
        from enrichers.email_cascade import resolve_email
        for lead in leads:
            _check_cancelled(job_id)
            _refresh_site_contacts(lead)
            resolve_email(lead, is_priority=True, registry=registry)
        handler.set_explicit_progress(6, 1.0, "Cascade email terminée")

        # ── Reachability: reachable / unreachable / pending_quota ────────────
        from processors.hit_calculator import score_all_leads
        reachable_leads, unreachable_leads, pending_leads = score_all_leads(leads)
        unreachable_leads = unreachable_leads + suppressed
        handler.set_explicit_progress(
            6, 1.0,
            f"{len(reachable_leads)} joignables / {len(unreachable_leads)} non joignables / "
            f"{len(pending_leads)} en attente de quota"
        )

        # ── Steps 7-9: evidence, facts, ICP scoring, angles (reachable only) ───────
        if reachable_leads:
            handler.set_explicit_progress(7, 0.0, "Collecte de preuves...")
            from enrichers.evidence_collector import collect_evidence
            reachable_leads, active_providers = collect_evidence(
                reachable_leads, enrich_instructions, registry=registry
            )
            handler.set_explicit_progress(7, 1.0, "Collecte terminée")
            _check_cancelled(job_id)

            handler.set_explicit_progress(8, 0.0, "Extraction des faits et scoring ICP...")
            from enrichers.fact_extractor import extract_leads_facts
            reachable_leads = extract_leads_facts(reachable_leads, active_providers, registry=registry)
            from processors.icp_scorer import apply_scores
            reachable_leads = apply_scores(reachable_leads)
            handler.set_explicit_progress(8, 1.0, "Scoring terminé")
            _check_cancelled(job_id)

            handler.set_explicit_progress(9, 0.0, "Rédaction des angles...")
            from enrichers.angle_writer import write_leads_angles
            reachable_leads = write_leads_angles(reachable_leads, enrich_instructions, registry=registry)
            handler.set_explicit_progress(9, 1.0, "Rédaction terminée")

        # pending_quota leads keep enriched=0: they never got their question
        # asked and must resurface at the head of the next batch (§10).
        finalized = reachable_leads + unreachable_leads
        enrich_data: dict[int, dict] = {}
        for lead in finalized:
            payload = {k: lead.get(k) for k in ENRICH_FIELDS if lead.get(k) is not None}
            payload.update({k: lead.get(k) for k in CASCADE_POOL_COLUMNS if k in lead})
            enrich_data[lead["id"]] = payload
        if finalized:
            mark_leads_enriched(pool_id, [l["id"] for l in finalized], job_id, enrich_data)

        # pending_quota leads must reach their pool row too, or their status
        # never leaves this run's in-memory list: the next enrich batch would
        # read email_status = NULL for them and lose the requeue-first order
        # (see update_cascade_columns' docstring).
        if pending_leads:
            pending_data = {
                lead["id"]: {k: lead.get(k) for k in CASCADE_POOL_COLUMNS if k in lead}
                for lead in pending_leads
            }
            update_cascade_columns([l["id"] for l in pending_leads], pending_data)

        leads = reachable_leads + unreachable_leads + pending_leads

        # ── Export CSV ────────────────────────────────────────────────────────
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        csv_filename = f"leads_enriched_{ts}_{job_id[:8]}.csv"
        csv_path = _export_csv(leads, csv_filename)

        # pending_quota leads never had their question answered — they are
        # not no-hit, and get their own CSV rather than padding the no-hit
        # numbers (§11).
        if pending_leads:
            pending_path = _export_csv(pending_leads, f"leads_pending_quota_{ts}_{job_id[:8]}.csv")
            logging.getLogger("pipeline_runner").info(f"Pending-quota CSV saved: {pending_path}")

        stats = compute_stats(leads)

        # ── Executive summary (Claude) — this is precisely the run where a
        # month's credits are most likely to run out mid-batch ───────────────
        executive_summary = None
        if not pipeline_config._is_placeholder(pipeline_config.ANTHROPIC_API_KEY):
            try:
                import anthropic as _anth
                _summary_client = _anth.Anthropic(api_key=pipeline_config.ANTHROPIC_API_KEY)
                summary_prompt = _build_summary_prompt(
                    leads=leads,
                    reachable_count=len(reachable_leads),
                    unreachable_count=len(unreachable_leads),
                    pending_count=len(pending_leads),
                    stats=stats,
                    enrich_instructions=enrich_instructions,
                    provider_status=registry.to_dict(),
                )
                msg = _summary_client.messages.create(
                    model="claude-haiku-4-5-20251001",
                    max_tokens=300,
                    messages=[{"role": "user", "content": summary_prompt}],
                )
                executive_summary = msg.content[0].text.strip()
            except Exception as e:
                logging.getLogger("pipeline_runner").warning(f"Executive summary failed: {e}")

        final_status = "completed_with_errors" if registry.has_critical_failure() else "done"
        _jobs[job_id] = JobResult(
            job_id=job_id, status=final_status,
            total_leads=len(leads),
            hit_leads=len(reachable_leads), nohit_leads=len(unreachable_leads),
            pending_quota_leads=len(pending_leads),
            stats=stats,
            leads=leads, csv_path=csv_path,
            executive_summary=executive_summary,
            provider_status=registry.to_dict(),
        )

        from api.history import save_job as _save_hist
        meta = _job_meta.get(job_id, {})
        _save_hist(
            job_id=job_id, status=final_status,
            apollo_url=f"pool:{pool_id}", max_leads=batch_size, skip_gpt=False,
            started_at=meta.get("started_at", ""),
            finished_at=datetime.now().isoformat(),
            total_leads=len(leads), hit_leads=len(reachable_leads), nohit_leads=len(unreachable_leads),
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

    except ProviderFailure as exc:
        message = f"Étape contacts interrompue — {exc.reason}"
        logging.getLogger("pipeline_runner").error(message)
        _jobs[job_id] = JobResult(job_id=job_id, status="error", error=message)
        error_payload = json.dumps({"type": "error", "data": {"message": message}})
        asyncio.run_coroutine_threadsafe(queue.put(error_payload), loop)
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


def start_enrich_job(pool_id: str, batch_size: int, enrich_instructions: str = "") -> str:
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
    _job_meta[job_id] = {
        "apollo_url": f"pool:{pool_id}", "max_leads": batch_size, "skip_gpt": False,
        "started_at": started_at, "enrich_instructions": enrich_instructions or "",
    }

    _executor.submit(
        _run_enrich_only_sync, job_id, pool_id, batch_size, loop, queue,
        enrich_instructions or "",
    )
    return job_id
