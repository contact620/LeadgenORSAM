from pydantic import BaseModel
from typing import Optional


class RunRequest(BaseModel):
    url: str
    max_leads: int = 500
    skip_gpt: bool = False


class ProgressEvent(BaseModel):
    step: int             # 1-5
    step_name: str
    message: str
    progress: float       # 0.0-1.0 within current step
    total_progress: float # 0.0-1.0 overall


class LeadRecord(BaseModel):
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    company: Optional[str] = None
    job_title: Optional[str] = None
    location: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    linkedin_url: Optional[str] = None
    website: Optional[str] = None
    hit_score: Optional[int] = None
    is_hit: Optional[bool] = None
    activity_summary: Optional[str] = None
    conversion_angle: Optional[str] = None


class JobStats(BaseModel):
    email_pct: float = 0.0
    linkedin_pct: float = 0.0
    phone_pct: float = 0.0
    website_pct: float = 0.0
    avg_score: float = 0.0


class JobResult(BaseModel):
    job_id: str
    status: str           # "running" | "done" | "error"
    total_leads: int = 0
    hit_leads: int = 0
    nohit_leads: int = 0
    stats: JobStats = JobStats()
    leads: list[dict] = []
    error: Optional[str] = None
    csv_path: Optional[str] = None


class HistoryEntry(BaseModel):
    job_id: str
    status: str
    apollo_url: str
    max_leads: int
    skip_gpt: bool
    started_at: str
    finished_at: Optional[str] = None
    total_leads: int = 0
    hit_leads: int = 0
    nohit_leads: int = 0
    email_pct: float = 0.0
    linkedin_pct: float = 0.0
    phone_pct: float = 0.0
    website_pct: float = 0.0
    avg_score: float = 0.0
    csv_filename: Optional[str] = None
    error: Optional[str] = None
    csv_available: bool = False
