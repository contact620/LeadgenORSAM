from enrichers.angle_writer import should_write


def test_disqualified_lead_gets_no_angle():
    assert should_write({"icp_tier": "disqualified"}) is False


def test_unverified_lead_gets_no_angle():
    assert should_write({"icp_tier": "cold", "evidence_verified": False}) is False


def test_verified_cold_lead_still_gets_an_angle():
    assert should_write({"icp_tier": "cold", "evidence_verified": True}) is True


def test_hot_lead_gets_an_angle():
    assert should_write({"icp_tier": "hot", "evidence_verified": True}) is True
