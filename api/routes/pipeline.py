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
from api.pipeline_runner import start_job, get_job, get_queue

router = APIRouter()


@router.post("/run")
async def run_pipeline(req: RunRequest):
    """Start a pipeline job. Returns job_id immediately."""
    if not req.url.strip():
        raise HTTPException(status_code=400, detail="Apollo URL is required")

    try:
        job_id = start_job(
            url=req.url.strip(),
            max_leads=req.max_leads,
            skip_gpt=req.skip_gpt,
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


@router.get("/results/{job_id}", response_model=JobResult)
async def get_results(job_id: str):
    """Return the full job result (status, leads, stats)."""
    job = get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@router.get("/download/{job_id}")
async def download_csv(job_id: str):
    """Download the final CSV file for a completed job."""
    job = get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status != "done":
        raise HTTPException(status_code=409, detail="Job is not complete yet")
    if not job.csv_path or not os.path.exists(job.csv_path):
        raise HTTPException(status_code=404, detail="CSV file not found")

    filename = os.path.basename(job.csv_path)
    return FileResponse(
        path=job.csv_path,
        media_type="text/csv",
        filename=filename,
    )
