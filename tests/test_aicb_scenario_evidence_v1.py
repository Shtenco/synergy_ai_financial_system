from simulation.aicb_scenario_evidence_v1 import AICBScenarioEvidence, forbid_authority_promotion


def test_aicb_evidence_is_content_addressed_and_scenario_only():
    evidence = AICBScenarioEvidence(
        scenario_id="stress-001",
        status="STRESS",
        model_sha256="a" * 64,
        config_sha256="b" * 64,
        seed=20260702,
        horizon_months=120,
        calibration_status="UNCALIBRATED_RND",
        assumptions={"foreign_demand_shock": 0.5},
        outputs={"debt_to_gdp": 0.8},
    )
    digest = evidence.evidence_digest()
    assert len(digest) == 64


def test_model_payload_cannot_promote_itself_to_accounting_or_settlement_authority():
    for forbidden in (
        "accounting_entry",
        "hardnav_authorization",
        "payment_settlement",
        "treasury_transfer",
        "observed_production_fact",
    ):
        try:
            forbid_authority_promotion({forbidden: {"value": 1}})
        except ValueError:
            continue
        assert False, f"{forbidden} must fail closed"
