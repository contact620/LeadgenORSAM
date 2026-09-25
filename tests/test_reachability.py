import pytest

from processors.reachability import apply_reachability, contact_level, is_reachable


def _lead(**over):
    base = {"email": None, "email_status": "not_found", "phone": None,
            "phone_type": None, "whatsapp": False, "linkedin_url": None}
    base.update(over)
    return base


@pytest.mark.parametrize("status", ["valid_nominatif", "valid_generique", "catch_all"])
def test_a_usable_email_makes_a_lead_reachable(status):
    assert is_reachable(_lead(email="k@acme.ma", email_status=status)) is True


@pytest.mark.parametrize("status", ["not_found", "unverified", "provider_failure"])
def test_an_unusable_email_does_not(status):
    assert is_reachable(_lead(email="k@acme.ma", email_status=status)) is False


def test_a_phone_alone_is_enough():
    assert is_reachable(_lead(phone="+212661234567", phone_type="mobile")) is True


def test_a_company_published_whatsapp_link_is_enough():
    assert is_reachable(_lead(whatsapp=True)) is True


def test_linkedin_alone_is_not_a_contact_route():
    """A LinkedIn profile is not a direct route: reaching the person still
    requires a connection request they may never accept."""
    assert is_reachable(_lead(linkedin_url="https://linkedin.com/in/karim")) is False


def test_a_pending_quota_lead_is_neither_reachable_nor_unreachable():
    lead = _lead(email_status="pending_quota")
    assert is_reachable(lead) is False
    assert contact_level(lead) == "indetermine"


@pytest.mark.parametrize("lead,level", [
    (_lead(email="k@acme.ma", email_status="valid_nominatif"), "direct"),
    (_lead(phone="+212661234567", phone_type="mobile"), "direct"),
    (_lead(whatsapp=True), "direct"),
    (_lead(email="contact@acme.ma", email_status="valid_generique"), "indirect"),
    (_lead(phone="+212522123456", phone_type="fixe"), "indirect"),
    (_lead(email="k@acme.ma", email_status="catch_all"), "indirect"),
    (_lead(), "aucun"),
])
def test_contact_level_grades_the_best_available_route(lead, level):
    assert contact_level(lead) == level


def test_the_best_route_wins_over_a_weaker_one():
    lead = _lead(email="contact@acme.ma", email_status="valid_generique",
                 phone="+212661234567", phone_type="mobile")
    assert contact_level(lead) == "direct"


def test_splitting_returns_three_disjoint_groups():
    leads = [
        _lead(email="a@acme.ma", email_status="valid_nominatif"),
        _lead(),
        _lead(email_status="pending_quota"),
    ]
    reachable, unreachable, pending = apply_reachability(leads)
    assert len(reachable) == 1 and len(unreachable) == 1 and len(pending) == 1
    assert leads[0]["reachable"] is True
    assert leads[1]["reachable"] is False
    assert leads[2]["reachable"] is None


def test_a_pending_lead_is_never_placed_in_the_unreachable_group():
    """§6: a pending_quota lead is never classed no-hit — it is requeued."""
    _, unreachable, pending = apply_reachability([_lead(email_status="pending_quota")])
    assert unreachable == []
    assert len(pending) == 1
