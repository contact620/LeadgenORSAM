import asyncio
import json
import logging
import os
import traceback
from typing import AsyncIterator

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, StreamingResponse

_log = logging.getLogger(__name__)

from api.models import RunRequest, JobResult
from api.pipeline_runner import start_job, get_job, get_queue, cancel_job, start_scrape_job, start_enrich_job

router = APIRouter()


@router.post("/run")
async def run_pipeline(req: RunRequest):
    """Start a pipeline job. Returns job_id immediately."""
    # Resolve URL: either direct or built from filters
    url = (req.url or "").strip()
    if not url and req.filters:
        from api.url_builder import build_apollo_url
        url = build_apollo_url(req.filters)
    if not url:
        raise HTTPException(status_code=400, detail="Apollo URL or filters required")

    try:
        job_id = start_job(
            url=url,
            max_leads=req.max_leads,
            skip_gpt=req.skip_gpt,
            enrich_instructions=req.enrich_instructions,
        )
    except Exception as exc:
        detail = f"{type(exc).__name__}: {exc}"
        _log.error(f"[/api/run] start_job failed:\n{traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=detail)
    return {"job_id": job_id}


@router.get("/stream/{job_id}")
async def stream_progress(job_id: str):
    """SSE endpoint — streams progress events until pipeline is done or errors."""
    queue = get_queue(job_id)
    if queue is None:
        raise HTTPException(status_code=404, detail="Job not found")

    async def event_generator() -> AsyncIterator[str]:
        while True:
            try:
                payload = await asyncio.wait_for(queue.get(), timeout=30)
            except asyncio.TimeoutError:
                # Send keepalive ping
                yield "event: ping\ndata: {}\n\n"
                continue

            if payload is None:
                # Sentinel — pipeline thread is done
                break

            data = json.loads(payload)
            event_type = data.get("type", "message")
            yield f"event: {event_type}\ndata: {payload}\n\n"

            if event_type in ("done", "error"):
                break

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/cancel/{job_id}")
async def cancel_pipeline(job_id: str):
    """Cancel a running pipeline."""
    if cancel_job(job_id):
        return {"ok": True}
    raise HTTPException(status_code=404, detail="Job not found")


@router.get("/results/{job_id}", response_model=JobResult)
async def get_results(job_id: str):
    """Return the full job result (status, leads, stats)."""
    job = get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@router.get("/download/{job_id}")
async def download_csv(job_id: str, format: str = "csv"):
    """Download the final file for a completed job. Supports csv and xlsx."""
    csv_path = None

    job = get_job(job_id)
    if job and job.status == "done" and job.csv_path and os.path.exists(job.csv_path):
        csv_path = job.csv_path
    else:
        from api import history
        import config as pipeline_config
        entry = history.get_job(job_id)
        if entry and entry.get("csv_filename"):
            path = os.path.join(pipeline_config.OUTPUT_DIR, entry["csv_filename"])
            if os.path.exists(path):
                csv_path = path

    if not csv_path:
        raise HTTPException(status_code=404, detail="CSV file not found")

    if format == "xlsx":
        try:
            import pandas as pd
            df = pd.read_csv(csv_path)
            xlsx_path = csv_path.replace(".csv", ".xlsx")
            df.to_excel(xlsx_path, index=False, engine="openpyxl")
            return FileResponse(
                path=xlsx_path,
                media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                filename=os.path.basename(xlsx_path),
            )
        except ImportError:
            raise HTTPException(status_code=400, detail="openpyxl non installé. Installez-le avec: pip install openpyxl")

    if format == "json":
        import pandas as pd
        df = pd.read_csv(csv_path)
        json_path = csv_path.replace(".csv", ".json")
        df.to_json(json_path, orient="records", indent=2, force_ascii=False)
        return FileResponse(
            path=json_path,
            media_type="application/json",
            filename=os.path.basename(json_path),
        )

    return FileResponse(
        path=csv_path,
        media_type="text/csv",
        filename=os.path.basename(csv_path),
    )


# ── Scrape-only & Enrich-only routes ─────────────────────────────────────────

from pydantic import BaseModel


class ScrapeRequest(BaseModel):
    url: str
    max_leads: int = 500
    pool_name: str = "Pool sans nom"


class EnrichRequest(BaseModel):
    pool_id: str
    batch_size: int = 10


@router.post("/scrape")
async def scrape_only(req: ScrapeRequest):
    """Start a scrape-only pipeline (steps 2-4). Stores leads in a pool."""
    if not req.url.strip():
        raise HTTPException(status_code=400, detail="Apollo URL required")
    job_id = start_scrape_job(
        url=req.url.strip(),
        max_leads=req.max_leads,
        pool_name=req.pool_name,
    )
    return {"job_id": job_id}


@router.post("/enrich")
async def enrich_pool(req: EnrichRequest):
    """Start an enrich-only pipeline (steps 5-7) on existing pool leads."""
    from api.leads_db import get_pool, get_pool_leads
    pool = get_pool(req.pool_id)
    if not pool:
        raise HTTPException(status_code=404, detail="Pool not found")
    # Check there are unenriched hit leads before starting
    available = get_pool_leads(req.pool_id, only_hit=True, only_unenriched=True, limit=1)
    if not available:
        raise HTTPException(status_code=400, detail="Tous les leads hit de ce pool sont déjà enrichis.")
    job_id = start_enrich_job(pool_id=req.pool_id, batch_size=req.batch_size)
    return {"job_id": job_id}


@router.get("/pools")
async def list_pools():
    """List all lead pools."""
    from api.leads_db import list_pools
    return list_pools()


@router.get("/pools/{pool_id}")
async def get_pool_detail(pool_id: str):
    """Get pool metadata."""
    from api.leads_db import get_pool
    pool = get_pool(pool_id)
    if not pool:
        raise HTTPException(status_code=404, detail="Pool not found")
    return pool


@router.get("/pools/{pool_id}/leads")
async def get_pool_leads_route(pool_id: str, only_hit: bool = False, only_unenriched: bool = False, limit: int = 0):
    """Get leads from a pool."""
    from api.leads_db import get_pool_leads
    return get_pool_leads(pool_id, only_hit=only_hit, only_unenriched=only_unenriched, limit=limit)


@router.delete("/pools/{pool_id}")
async def delete_pool_route(pool_id: str):
    """Delete a lead pool."""
    from api.leads_db import delete_pool
    if not delete_pool(pool_id):
        raise HTTPException(status_code=404, detail="Pool not found")
    return {"ok": True}
