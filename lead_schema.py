"""
Single source of truth for the exported lead schema.

Before this module the column list was duplicated in main.py and three times
in api/pipeline_runner.py, which guarantees divergence over time.
"""

CSV_COLUMNS: list[str] = [
    # Identity
    "first_name", "last_name", "company", "job_title", "location",
    # True when the contact row holds a legal entity instead of a person
    # ("Delta Btp", "Stpv Voire", "Les Marrakech" in the 2026-09-25 demo).
    # A flag, never a removal: the operator decides whether to keep the row,
    # but no longer discovers the problem by reading an email nobody owns.
    "name_looks_like_company",
    # Contact
    "email", "email_status", "email_confidence", "phone",
    "linkedin_url", "website", "website_coherent", "website_rejected",
    # Why a candidate site was kept or dropped — auditable in the export,
    # not only in the UI modal.
    "website_check_reason",
    # True when the site fetch itself failed (network/DNS/timeout/error
    # status) rather than the page answering thin or empty. This is what
    # lets a lead like Astrak reach evidence_level="sufficient" on Perplexity
    # alone — without this column in the export, that outcome is invisible
    # to an operator comparing two otherwise-similar leads. Set as early as
    # step 3a (find_linkedin_and_website) for any lead with a candidate
    # website, hit or not, and possibly overwritten in step 5/6a for hit
    # leads once the evidence scrape runs. None means no candidate website
    # was ever fetched for this lead (no company name, or none found).
    "website_unreachable",
    # Reachability — a boolean and its best route, never a score (2026-09-25).
    "reachable", "contact_level",
    # Email acquisition — which branch of the cascade produced this address,
    # and, when it went through the verification step, which provider gave the
    # verdict. email_source alone names a branch ("pattern_verified"), never a
    # vendor: reading it, the client concluded GetProspect was never called.
    "email_source", "email_type", "email_verification_provider",
    "contact_source_url",
    # Domain-level facts, shared by every lead on the same domain.
    "domain_catch_all", "domain_mx_provider", "domain_mismatch",
    # Phones and social, all extracted from the company's own site.
    "phone_type", "phone_source", "whatsapp",
    "facebook_url", "instagram_url", "linkedin_company_url",
    # Pass-1 spending prioritisation. NEVER a verdict — see processors/prescore.py.
    # The two raw Apollo cells the prescore reads travel with it: without them
    # in the export, an operator reading prescore=0 on every row cannot tell a
    # genuinely low-fit lead from a column Apollo never displayed. Both were
    # empty for the 20 leads of the 2026-09-25 demo, and nothing said so.
    "prescore", "apollo_industry", "employee_count",
    # ICP verdict. The 0-100 score, its tier, its rationale ("Secteur 70/100,
    # taille 40/100...") and its per-axis detail are computed but deliberately
    # NOT exported: the client asked for the score to be removed, and a CSV
    # that still carries it only moves the score out of sight of one screen.
    # disqualification_reason stays: it is a factual reason, not a grade.
    "disqualification_reason", "evidence_level", "evidence_verified",
    # AI enrichment
    "activity_summary", "conversion_angle", "facts_json",
    # Priority signal, lifted out of facts_json into its own cell: a contact
    # who just took the job is the one moment they are open to changing
    # provider. Sourced and dated to the month, or absent — see
    # enrichers/fact_extractor._as_appointment.
    "prise_de_poste",
    # Company intelligence
    "digital_maturity", "estimated_budget", "business_signals",
    # Person intelligence — the contact, not their employer: current role and
    # since when, scope, publicly attributed achievements, public appearances.
    # Researched once per lead and never cached, see
    # enrichers/perplexity_enricher.PERSON_PROMPT.
    "person_research",
    # Deduplication
    "is_duplicate", "first_seen_at",
]

# Fields produced by the enrichment phase, persisted per lead in the pool DB.
ENRICH_FIELDS: list[str] = [
    "disqualification_reason", "evidence_level", "evidence_verified",
    "activity_summary", "conversion_angle", "facts_json", "prise_de_poste",
    "digital_maturity", "estimated_budget", "business_signals",
    "person_research",
]
