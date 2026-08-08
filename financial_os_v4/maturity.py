from __future__ import annotations

from dataclasses import dataclass, field
from math import isfinite

EPS = 1e-12


@dataclass(frozen=True, slots=True)
class MaturityClaim:
    claim_id: str
    amount: float
    due_week: int
    source: str
    seniority: int = 0

    def __post_init__(self) -> None:
        if not self.claim_id.strip() or not self.source.strip():
            raise ValueError("claim_id and source are required")
        if not isfinite(self.amount) or self.amount <= 0:
            raise ValueError("claim amount must be finite and positive")
        if self.due_week < 0:
            raise ValueError("due_week cannot be negative")
        if self.seniority < 0:
            raise ValueError("seniority cannot be negative")


@dataclass
class MaturityBook:
    claims: dict[str, MaturityClaim] = field(default_factory=dict)

    def add(self, claim: MaturityClaim) -> None:
        if claim.claim_id in self.claims:
            raise ValueError("claim already exists")
        self.claims[claim.claim_id] = claim

    def remove(self, claim_id: str) -> MaturityClaim:
        return self.claims.pop(claim_id)

    def curve(self, current_week: int, horizon_weeks: int = 100) -> tuple[float, ...]:
        if current_week < 0 or horizon_weeks <= 0:
            raise ValueError("invalid maturity horizon")
        buckets = [0.0] * horizon_weeks
        for claim in self.claims.values():
            offset = claim.due_week - current_week
            if offset <= 0:
                buckets[0] += claim.amount
            elif offset <= horizon_weeks:
                buckets[offset - 1] += claim.amount
        return tuple(buckets)

    def due_through(self, current_week: int, horizon_weeks: int) -> float:
        return sum(self.curve(current_week, horizon_weeks))

    def lcr(
        self,
        *,
        current_week: int,
        horizon_weeks: int,
        liquid_reserve: float,
        expected_inflows: float = 0.0,
        stress_buffer: float = 0.0,
    ) -> float | None:
        for name, value in (
            ("liquid_reserve", liquid_reserve),
            ("expected_inflows", expected_inflows),
            ("stress_buffer", stress_buffer),
        ):
            if not isfinite(value) or value < 0:
                raise ValueError(f"{name} must be finite and non-negative")
        due = self.due_through(current_week, horizon_weeks) + stress_buffer
        if due <= EPS:
            return None
        return (liquid_reserve + expected_inflows) / due

    def summary(self, current_week: int) -> dict[str, float | tuple[float, ...]]:
        curve = self.curve(current_week, 100)
        return {
            "unlock_curve_1_100": curve,
            "unlock_1w": sum(curve[:1]),
            "unlock_4w": sum(curve[:4]),
            "unlock_8w": sum(curve[:8]),
            "unlock_26w": sum(curve[:26]),
            "unlock_100w": sum(curve),
        }
