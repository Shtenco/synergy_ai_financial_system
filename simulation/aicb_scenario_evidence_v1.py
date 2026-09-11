from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import json
from typing import Any, Mapping


ALLOWED_STATUS = {"SCENARIO", "STRESS", "COUNTERFACTUAL"}


@dataclass(frozen=True)
class AICBScenarioEvidence:
    scenario_id: str
    status: str
    model_sha256: str
    config_sha256: str
    seed: int
    horizon_months: int
    calibration_status: str
    assumptions: Mapping[str, Any]
    outputs: Mapping[str, Any]

    def validate(self) -> None:
        if self.status not in ALLOWED_STATUS:
            raise ValueError("AICB output must remain scenario/stress/counterfactual evidence")
        for digest in (self.model_sha256, self.config_sha256):
            if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest.lower()):
                raise ValueError("invalid sha256")
        if self.horizon_months <= 0:
            raise ValueError("horizon_months must be positive")
        if not self.scenario_id:
            raise ValueError("scenario_id required")

    def canonical_json(self) -> str:
        self.validate()
        return json.dumps(asdict(self), ensure_ascii=False, sort_keys=True, separators=(",", ":"))

    def evidence_digest(self) -> str:
        return sha256(self.canonical_json().encode("utf-8")).hexdigest()


def forbid_authority_promotion(payload: Mapping[str, Any]) -> None:
    """Fail closed if a model payload tries to masquerade as canonical economic truth."""
    forbidden = {
        "accounting_entry",
        "hardnav_authorization",
        "payment_settlement",
        "treasury_transfer",
        "observed_production_fact",
    }
    present = forbidden.intersection({str(k).lower() for k in payload.keys()})
    if present:
        raise ValueError(f"AICB scenario payload contains forbidden authority fields: {sorted(present)}")
