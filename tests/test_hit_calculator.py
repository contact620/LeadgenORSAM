"""
processors/hit_calculator.py is now a thin compatibility shim over
processors/reachability.py (see that module's docstring for why the hit
score itself is gone). These tests exercise only the three-way split the
shim exposes, so the runners keep one import path until Task 22 migrates them.
"""
from processors.hit_calculator import score_all_leads


def _lead(**over):
    base = {"email": None, "email_status": "not_found", "phone": None,
            "phone_type": None, "whatsapp": False, "linkedin_url": None}
    base.update(over)
    return base


def test_score_all_leads_splits_into_three_groups():
    leads = [
        _lead(email="a@acme.ma", email_status="valid_nominatif"),
        _lead(),
        _lead(email_status="pending_quota"),
    ]
    reachable, unreachable, pending = score_all_leads(leads)
    assert len(reachable) == 1
    assert len(unreachable) == 1
    assert len(pending) == 1


def test_a_pending_quota_lead_never_lands_in_the_unreachable_group():
    leads = [_lead(email_status="pending_quota")]
    reachable, unreachable, pending = score_all_leads(leads)
    assert reachable == []
    assert unreachable == []
    assert len(pending) == 1


def test_score_all_leads_annotates_each_lead_in_place():
    leads = [_lead(phone="+212661234567", phone_type="mobile")]
    reachable, unreachable, pending = score_all_leads(leads)
    assert leads[0]["reachable"] is True
    assert leads[0]["contact_level"] == "direct"
    assert leads[0] in reachable
