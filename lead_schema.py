"""
Single source of truth for the exported lead schema.

Before this module the column list was duplicated in main.py and three times
in api/pipeline_runner.py, which guarantees divergence over time.
"""

CSV_COLUMNS: list[str] = [
    # Identity
    "first_name", "last_name", "company", "job_title", "location",
    # Contact
    "email", "email_status", "email_confidence", "phone",
    "linkedin_url", "website", "website_coherent", "website_rejected",
    # Hit scoring
    "hit_score", "is_hit",
    # ICP scoring
    "icp_score", "icp_tier", "icp_rationale", "icp_scores_detail",
    "disqualification_reason", "evidence_level", "evidence_verified",
    # AI enrichment
    "activity_summary", "conversion_angle", "facts_json",
    # Legacy fields, still produced by enrichers/gpt_enricher.py.
    # Removed in task 13, together with the module that produces them —
    # dropping them earlier would lose data already written to lead_pool.enrich_data.
    "inconsistency_detected", "inconsistency_reason", "llm_confidence",
    # Company intelligence
    "digital_maturity", "estimated_budget", "business_signals",
    # Deduplication
    "is_duplicate", "first_seen_at",
]

# Fields produced by the enrichment phase, persisted per lead in the pool DB.
ENRICH_FIELDS: list[str] = [
    "icp_score", "icp_tier", "icp_rationale", "icp_scores_detail",
    "disqualification_reason", "evidence_level", "evidence_verified",
    "activity_summary", "conversion_angle", "facts_json",
    # Legacy fields, still produced by enrichers/gpt_enricher.py.
    # Removed in task 13, together with the module that produces them —
    # dropping them earlier would lose data already written to lead_pool.enrich_data.
    "inconsistency_detected", "inconsistency_reason", "llm_confidence",
    "digital_maturity", "estimated_budget", "business_signals",
]
