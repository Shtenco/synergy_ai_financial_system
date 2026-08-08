from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from statistics import median


@dataclass(frozen=True)
class VerifierAttestation:
    verifier_id: str
    measured_output_value: float
    bond_value: float

    def __post_init__(self) -> None:
        if not self.verifier_id.strip():
            raise ValueError("verifier_id is required")
        if not isfinite(self.measured_output_value) or self.measured_output_value < 0:
            raise ValueError("measured_output_value must be finite and non-negative")
        if not isfinite(self.bond_value) or self.bond_value < 0:
            raise ValueError("bond_value must be finite and non-negative")


@dataclass(frozen=True)
class ProductiveCreditRequest:
    project_id: str
    requested_credit: float
    attestations: tuple[VerifierAttestation, ...]

    def __post_init__(self) -> None:
        if not self.project_id.strip():
            raise ValueError("project_id is required")
        if not isfinite(self.requested_credit) or self.requested_credit <= 0:
            raise ValueError("requested_credit must be finite and positive")


@dataclass(frozen=True)
class ProductiveCapacity:
    verified_output_value: float
    productive_capacity: float
    reserve_capacity: float
    liquidity_capacity: float
    risk_capacity: float
    requested_credit: float
    approved_credit: float


@dataclass(frozen=True)
class VerificationPolicy:
    """Conservative post-factum verification for productive credit research.

    The verifier identity/bond fields are accounting inputs only. Real Sybil
    resistance, staking custody, dispute resolution and fraud evidence require
    external identity/security systems and cannot be proven by this class.
    """

    required_verifiers: int = 7
    minimum_bond: float = 10_000.0
    productive_haircut: float = 0.50
    max_relative_deviation: float = 0.35

    def __post_init__(self) -> None:
        if self.required_verifiers < 3:
            raise ValueError("required_verifiers must be at least 3")
        if not isfinite(self.minimum_bond) or self.minimum_bond < 0:
            raise ValueError("minimum_bond must be finite and non-negative")
        if not 0 < self.productive_haircut <= 1:
            raise ValueError("productive_haircut must be in (0,1]")
        if not 0 <= self.max_relative_deviation <= 1:
            raise ValueError("max_relative_deviation must be in [0,1]")

    def verified_output_value(self, request: ProductiveCreditRequest) -> float:
        by_id: dict[str, VerifierAttestation] = {}
        for attestation in request.attestations:
            if attestation.verifier_id in by_id:
                raise ValueError("duplicate verifier identity in one evidence set")
            if attestation.bond_value < self.minimum_bond:
                continue
            by_id[attestation.verifier_id] = attestation

        if len(by_id) < self.required_verifiers:
            raise RuntimeError("insufficient independently bonded verifier quorum")

        values = [item.measured_output_value for item in by_id.values()]
        center = median(values)
        if center == 0:
            accepted = [value for value in values if value == 0]
        else:
            accepted = [
                value
                for value in values
                if abs(value - center) / center <= self.max_relative_deviation
            ]

        if len(accepted) < self.required_verifiers:
            raise RuntimeError("verifier values fail robust-consensus deviation test")
        return float(median(accepted))

    def capacity(
        self,
        request: ProductiveCreditRequest,
        *,
        reserve_capacity: float,
        liquidity_capacity: float,
        risk_capacity: float,
    ) -> ProductiveCapacity:
        for name, value in (
            ("reserve_capacity", reserve_capacity),
            ("liquidity_capacity", liquidity_capacity),
            ("risk_capacity", risk_capacity),
        ):
            if not isfinite(value) or value < 0:
                raise ValueError(f"{name} must be finite and non-negative")

        verified = self.verified_output_value(request)
        productive_capacity = verified * self.productive_haircut
        approved = min(
            request.requested_credit,
            productive_capacity,
            reserve_capacity,
            liquidity_capacity,
            risk_capacity,
        )
        return ProductiveCapacity(
            verified_output_value=verified,
            productive_capacity=productive_capacity,
            reserve_capacity=reserve_capacity,
            liquidity_capacity=liquidity_capacity,
            risk_capacity=risk_capacity,
            requested_credit=request.requested_credit,
            approved_credit=max(0.0, approved),
        )
