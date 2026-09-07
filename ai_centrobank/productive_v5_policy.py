from __future__ import annotations

from dataclasses import asdict, dataclass
from math import isfinite


class AICBV5PolicyError(ValueError):
    pass


@dataclass(frozen=True)
class EconomicSnapshotV5:
    period_id: str
    monthly_inflation: float
    target_monthly_inflation: float
    inflation_tolerance: float
    reserve_cover: float
    min_reserve_cover: float
    target_reserve_cover: float
    goods_growth: float
    capacity_growth: float
    employment_rate: float
    money_to_goods: float
    target_money_to_goods: float
    available_matching_capital: float
    required_match_ratio: float
    max_period_emission: float
    physical_consistency_gap: float = 0.0
    supply_accounting_gap: float = 0.0

    def __post_init__(self) -> None:
        if not self.period_id:
            raise AICBV5PolicyError("period_id is required")
        numeric = asdict(self)
        numeric.pop("period_id")
        for name, value in numeric.items():
            if not isfinite(value):
                raise AICBV5PolicyError(f"{name} must be finite")
        if self.inflation_tolerance <= 0:
            raise AICBV5PolicyError("inflation_tolerance must be positive")
        if self.target_reserve_cover <= self.min_reserve_cover:
            raise AICBV5PolicyError("target reserve cover must exceed minimum")
        if self.required_match_ratio <= 0:
            raise AICBV5PolicyError("required_match_ratio must be positive")
        if self.max_period_emission < 0 or self.available_matching_capital < 0:
            raise AICBV5PolicyError("emission and matching-capital limits must be non-negative")
        if self.physical_consistency_gap < 0:
            raise AICBV5PolicyError("physical_consistency_gap must be non-negative")


@dataclass(frozen=True)
class TargetEmissionProposalV5:
    period_id: str
    requested_emission: float
    raw_policy_limit: float
    matching_capital_limit: float
    policy_score: float
    blocked: bool
    block_reason: str
    policy_version: str = "AICB_V5_DUAL_GATE_1"

    def as_payload(self) -> dict:
        return asdict(self)


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


class AICBPolicyV5:
    """Bounded proposal engine distilled from Productive Liquidity Protocol V4.

    It has no mint/release authority. It only proposes an upper bound. The
    proposal must still pass independent risk approval, productive evidence,
    Financial OS evidence and escrow release rules.
    """

    POLICY_VERSION = "AICB_V5_DUAL_GATE_1"

    @staticmethod
    def evaluate(snapshot: EconomicSnapshotV5) -> TargetEmissionProposalV5:
        # Fail closed on the two integrity gaps carried over from V4.
        if snapshot.physical_consistency_gap > 1e-12:
            return TargetEmissionProposalV5(
                period_id=snapshot.period_id,
                requested_emission=0.0,
                raw_policy_limit=0.0,
                matching_capital_limit=0.0,
                policy_score=0.0,
                blocked=True,
                block_reason="PHYSICAL_CONSISTENCY_GAP",
            )
        if abs(snapshot.supply_accounting_gap) > 1e-9:
            return TargetEmissionProposalV5(
                period_id=snapshot.period_id,
                requested_emission=0.0,
                raw_policy_limit=0.0,
                matching_capital_limit=0.0,
                policy_score=0.0,
                blocked=True,
                block_reason="SUPPLY_ACCOUNTING_GAP",
            )

        inflation_excess = max(
            0.0,
            snapshot.monthly_inflation - snapshot.target_monthly_inflation,
        )
        inflation_score = _clamp(
            1.0 - inflation_excess / snapshot.inflation_tolerance,
            0.0,
            1.0,
        )
        reserve_score = _clamp(
            (snapshot.reserve_cover - snapshot.min_reserve_cover)
            / (snapshot.target_reserve_cover - snapshot.min_reserve_cover),
            0.0,
            1.0,
        )
        goods_score = _clamp((snapshot.goods_growth + 0.006) / 0.020, 0.0, 1.0)
        capacity_score = _clamp((snapshot.capacity_growth + 0.004) / 0.018, 0.0, 1.0)
        employment_score = _clamp((snapshot.employment_rate - 0.88) / 0.10, 0.0, 1.0)
        money_gap_score = _clamp(
            (snapshot.target_money_to_goods - snapshot.money_to_goods + 0.20) / 0.40,
            0.0,
            1.0,
        )

        score = (
            0.25 * inflation_score
            + 0.20 * reserve_score
            + 0.22 * goods_score
            + 0.16 * capacity_score
            + 0.09 * employment_score
            + 0.08 * money_gap_score
        )

        # Preserve V4's asymmetric brakes: inflation, reserves and excess money
        # can reduce the proposal sharply, while no positive signal can exceed
        # the configured hard cap.
        if snapshot.monthly_inflation > (
            snapshot.target_monthly_inflation + snapshot.inflation_tolerance
        ):
            score *= 0.45
        if snapshot.reserve_cover < snapshot.min_reserve_cover:
            score *= 0.35
        if snapshot.money_to_goods > snapshot.target_money_to_goods + 0.35:
            score *= 0.55

        score = _clamp(score, 0.0, 1.0)
        raw_policy_limit = snapshot.max_period_emission * score
        matching_capital_limit = (
            snapshot.available_matching_capital / snapshot.required_match_ratio
        )
        requested = min(raw_policy_limit, matching_capital_limit)

        blocked = requested <= 0.0
        reason = "NO_CAPACITY" if blocked else ""
        return TargetEmissionProposalV5(
            period_id=snapshot.period_id,
            requested_emission=max(0.0, requested),
            raw_policy_limit=max(0.0, raw_policy_limit),
            matching_capital_limit=max(0.0, matching_capital_limit),
            policy_score=score,
            blocked=blocked,
            block_reason=reason,
        )
