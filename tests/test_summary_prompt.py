"""Tests for the executive-summary prompt.

The summary is the first — often only — thing the operator reads about a run.
Everything asserted here is a number that used to vanish from it.
"""
from api.models import JobStats
from api.pipeline_runner import _build_summary_prompt


def _stats(**kw) -> JobStats:
    base = dict(
        email_pct=80.0, linkedin_pct=60.0, phone_pct=20.0, website_pct=40.0,
        avg_score=62.0, email_count=40, linkedin_count=30, phone_count=10,
        website_count=20, icp_hot_count=5, icp_warm_count=5, icp_cold_count=10,
        icp_disqualified_count=30,
    )
    base.update(kw)
    return JobStats(**base)


def _leads(hot=5, warm=5, cold=10, disqualified=30, unverified=0):
    leads = []
    for tier, count in (("hot", hot), ("warm", warm), ("cold", cold),
                        ("disqualified", disqualified)):
        for i in range(count):
            leads.append({
                "company": f"{tier.title()} {i}",
                "icp_tier": tier,
                "evidence_verified": True,
            })
    for lead in leads[:unverified]:
        lead["evidence_verified"] = False
    return leads


def test_disqualified_leads_are_counted():
    """50 leads, 30 disqualified: the three-tier breakdown described 20 of
    them and let the other 30 disappear without a word."""
    prompt = _build_summary_prompt(
        leads=_leads(), hit_count=50, nohit_count=0, stats=_stats(),
    )
    assert "30 disqualifiés" in prompt


def test_unverified_leads_are_named_as_such():
    prompt = _build_summary_prompt(
        leads=_leads(unverified=12), hit_count=50, nohit_count=0, stats=_stats(),
    )
    assert "12 leads non vérifiés" in prompt
    assert "preuves insuffisantes" in prompt


def test_every_tier_total_is_reported():
    prompt = _build_summary_prompt(
        leads=_leads(), hit_count=50, nohit_count=7, stats=_stats(),
    )
    assert "5 haute pertinence" in prompt
    assert "5 pertinence moyenne" in prompt
    assert "10 faible pertinence" in prompt
    assert "50 prospects analysés" in prompt
    assert "7 non qualifiés" in prompt


def test_degraded_provider_is_named():
    prompt = _build_summary_prompt(
        leads=_leads(), hit_count=50, nohit_count=0, stats=_stats(),
        provider_status={
            "serper": {"status": "degraded", "reason": "clé rejetée", "leads_affected": 40},
            "dropcontact": {"status": "ok", "reason": None, "leads_affected": 50},
        },
    )
    assert "Serper" in prompt
    assert "dégradé" in prompt
    assert "clé rejetée" in prompt
    # And the model is told the figures themselves are affected.
    assert "les chiffres ci-dessus en sont affectés" in prompt


def test_failed_provider_is_named_as_failed():
    prompt = _build_summary_prompt(
        leads=_leads(), hit_count=50, nohit_count=0, stats=_stats(),
        provider_status={
            "hunter": {"status": "failed", "reason": "401", "leads_affected": 50},
        },
    )
    assert "Hunter.io" in prompt
    assert "en échec" in prompt


def test_healthy_providers_are_not_mentioned():
    prompt = _build_summary_prompt(
        leads=_leads(), hit_count=50, nohit_count=0, stats=_stats(),
        provider_status={
            "dropcontact": {"status": "ok", "reason": None, "leads_affected": 50},
            "perplexity": {"status": "skipped", "reason": "clé API absente", "leads_affected": 0},
        },
    )
    assert "Fournisseurs en difficulté" not in prompt


def test_unscored_run_is_not_reported_as_zero_relevant_leads():
    """--skip-gpt leaves icp_tier None everywhere; a naive count would read
    that as "0 lead pertinent trouvé"."""
    leads = [{"company": "Acme", "icp_tier": None} for _ in range(10)]
    prompt = _build_summary_prompt(
        leads=leads, hit_count=4, nohit_count=6,
        stats=_stats(icp_hot_count=0, icp_warm_count=0, icp_cold_count=0,
                     icp_disqualified_count=0),
    )
    assert "non calculé sur ce run" in prompt
    assert "haute pertinence" not in prompt
    assert "Ne commente pas la pertinence ICP" in prompt


def test_user_instructions_are_carried_through():
    prompt = _build_summary_prompt(
        leads=_leads(), hit_count=50, nohit_count=0, stats=_stats(),
        enrich_instructions="cibler les PME qui recrutent",
    )
    assert "cibler les PME qui recrutent" in prompt


def test_absent_instructions_are_stated_explicitly():
    prompt = _build_summary_prompt(
        leads=_leads(), hit_count=50, nohit_count=0, stats=_stats(),
    )
    assert "aucune instruction spécifique" in prompt
