from simulation.aicb_scenario_evidence_v1 import AICBScenarioEvidence
from simulation.synergy_contracts import CONTRACT_ID, scenario_evidence_payload

def test_scenario_evidence_cannot_promote_authority():
    e=AICBScenarioEvidence(
        scenario_id="s1",status="STRESS",model_sha256="1"*64,config_sha256="2"*64,
        seed=1,horizon_months=12,calibration_status="TEST",
        assumptions={"shock":.2},outputs={"hardnav_path":[1,0.9]}
    )
    p=scenario_evidence_payload(e)
    assert CONTRACT_ID=="synergy.economy.scenario-evidence/v1"
    assert p["accounting_authority"] is False
    assert p["settlement_authority"] is False
    assert p["capital_authorization"] is False
