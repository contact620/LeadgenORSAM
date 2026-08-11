from enrichers.angle_writer import should_write


def test_disqualified_lead_gets_no_angle():
    assert should_write({"icp_tier": "disqualified"}) is False


def test_unverified_lead_gets_no_angle():
    assert should_write({"icp_tier": "cold", "evidence_verified": False}) is False


def test_verified_cold_lead_still_gets_an_angle():
    assert should_write({"icp_tier": "cold", "evidence_verified": True}) is True


def test_hot_lead_gets_an_angle():
    assert should_write({"icp_tier": "hot", "evidence_verified": True}) is True


def test_well_evidenced_disqualified_lead_still_gets_no_angle():
    # The row that actually exercises the disqualification short-circuit:
    # without it, evidence_verified=True would let this lead through.
    assert should_write({"icp_tier": "disqualified", "evidence_verified": True}) is False
