from pydantic import BaseModel
from typing import Optional


class ApolloFilters(BaseModel):
    person_titles: list[str] = []
    locations: list[str] = []
    industries: list[str] = []
    employee_ranges: list[str] = []
    seniority: list[str] = []
    email_status: list[str] = ["verified"]
    keywords: list[str] = []


class RunRequest(BaseModel):
    url: Optional[str] = None
    filters: Optional[ApolloFilters] = None
    max_leads: int = 500
    skip_gpt: bool = False
    enrich_instructions: Optional[str] = None


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
    email_status: Optional[str] = None
    email_confidence: Optional[int] = None
    email_verification_provider: Optional[str] = None
    phone: Optional[str] = None
    linkedin_url: Optional[str] = None
    website: Optional[str] = None
    # Reachability — a boolean and its best route, never a score (2026-09-25).
    reachable: Optional[bool] = None
    contact_level: Optional[str] = None
    # Email acquisition — which branch of the cascade produced this address.
    email_source: Optional[str] = None
    email_type: Optional[str] = None
    contact_source_url: Optional[str] = None
    # Domain-level facts, shared by every lead on the same domain.
    domain_catch_all: Optional[bool] = None
    domain_mx_provider: Optional[str] = None
    domain_mismatch: Optional[bool] = None
    # Phones and social, all extracted from the company's own site.
    phone_type: Optional[str] = None
    phone_source: Optional[str] = None
    whatsapp: Optional[bool] = None
    facebook_url: Optional[str] = None
    instagram_url: Optional[str] = None
    linkedin_company_url: Optional[str] = None
    # Pass-1 spending prioritisation. NEVER a verdict — see processors/prescore.py.
    prescore: Optional[int] = None
    activity_summary: Optional[str] = None
    conversion_angle: Optional[str] = None
    digital_maturity: Optional[str] = None
    estimated_budget: Optional[str] = None
    business_signals: Optional[str] = None
    icp_score: Optional[int] = None
    icp_tier: Optional[str] = None
    icp_rationale: Optional[str] = None
    icp_scores_detail: Optional[str] = None
    website_coherent: Optional[bool] = None
    website_rejected: Optional[str] = None
    disqualification_reason: Optional[str] = None
    evidence_level: Optional[str] = None
    evidence_verified: Optional[bool] = None
    facts_json: Optional[str] = None


class JobStats(BaseModel):
    email_pct: float = 0.0
    linkedin_pct: float = 0.0
    phone_pct: float = 0.0
    website_pct: float = 0.0
    avg_score: float = 0.0
    email_count: int = 0
    linkedin_count: int = 0
    phone_count: int = 0
    website_count: int = 0
    # Which branch of the free cascade produced each address — the number
    # that tells the operator whether the free steps are carrying their
    # weight (see api.pipeline_runner.compute_stats).
    email_by_source: dict[str, int] = {}
    mobile_count: int = 0
    whatsapp_count: int = 0
    pending_quota_count: int = 0
    reachable_count: int = 0
    provider_credits: dict[str, dict] = {}
    icp_hot_count: int = 0
    icp_warm_count: int = 0
    icp_cold_count: int = 0
    icp_disqualified_count: int = 0


class JobResult(BaseModel):
    job_id: str
    status: str           # "running" | "done" | "error"
    total_leads: int = 0
    # Named hit_leads/nohit_leads for frontend compatibility, but they now
    # carry the reachable/unreachable split (see processors/reachability.py)
    # rather than a hit-score threshold.
    hit_leads: int = 0
    nohit_leads: int = 0
    pending_quota_leads: int = 0
    stats: JobStats = JobStats()
    leads: list[dict] = []
    error: Optional[str] = None
    csv_path: Optional[str] = None
    executive_summary: Optional[str] = None
    provider_status: dict[str, dict] = {}


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
