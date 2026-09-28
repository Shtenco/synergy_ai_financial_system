from __future__ import annotations
from dataclasses import asdict
from typing import Any

from aicb_scenario_evidence_v1 import AICBScenarioEvidence, forbid_authority_promotion

CONTRACT_ID = "synergy.economy.scenario-evidence/v1"
AUTHORITY = "financial_scenario_research"


def scenario_evidence_payload(evidence: AICBScenarioEvidence) -> dict[str, Any]:
    evidence.validate()
    payload = asdict(evidence)
    forbid_authority_promotion(payload)
    return {
        **payload,
        "evidence_digest": evidence.evidence_digest(),
        "accounting_authority": False,
        "settlement_authority": False,
        "capital_authorization": False,
    }
