"""History endpoints — list, view, delete past pipeline runs."""
import os

import pandas as pd
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse

import config as pipeline_config
from api import history

router = APIRouter()


@router.get("/history")
async def list_history(limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0)):
    return history.list_jobs(limit=limit, offset=offset)


@router.get("/history/{job_id}")
async def get_history_entry(job_id: str):
    entry = history.get_job(job_id)
    if not entry:
        raise HTTPException(404, "Job not found in history")
    return entry


@router.get("/history/{job_id}/leads")
async def get_history_leads(job_id: str):
    """Re-read leads from the CSV file for a historical job."""
    entry = history.get_job(job_id)
    if not entry:
        raise HTTPException(404, "Job not found in history")
    fname = entry.get("csv_filename")
    if not fname:
        raise HTTPException(404, "No CSV file associated with this job")
    csv_path = os.path.join(pipeline_config.OUTPUT_DIR, fname)
    if not os.path.exists(csv_path):
        raise HTTPException(404, "CSV file no longer available on disk")
    df = pd.read_csv(csv_path)
    return df.where(df.notna(), None).to_dict(orient="records")


@router.delete("/history/{job_id}")
async def delete_history_entry(job_id: str):
    csv_filename = history.delete_job(job_id)
    if csv_filename is None:
        raise HTTPException(404, "Job not found in history")
    # Also delete CSV if it exists
    csv_path = os.path.join(pipeline_config.OUTPUT_DIR, csv_filename)
    if os.path.exists(csv_path):
        os.remove(csv_path)
    return {"ok": True}
