from __future__ import annotations

from dataclasses import dataclass
from math import isfinite

from .core import (
    Constitution,
    MonetaryAction,
    MonetaryResidual,
    MonetaryState,
    PolicyDecision,
)


@dataclass(frozen=True)
class RewardWeights:
    inflation: float = 4.0
    output_gap: float = 2.0
    unemployment_gap: float = 1.0
    liquidity_shortfall: float = 8.0
    npl: float = 6.0
    reserve_shortfall: float = 8.0
    policy_change: float = 0.5
    external_pnl: float = 1.0
    solvency_margin: float = 2.0

    def __post_init__(self) -> None:
        for value in self.__dict__.values():
            if not isfinite(value) or value < 0:
                raise ValueError("reward weights must be finite and non-negative")


@dataclass(frozen=True)
class PolicyTransition:
    state: MonetaryState
    proposed_residual: MonetaryResidual
    decision: PolicyDecision
    observed_next_state: MonetaryState
    reward: float


def _action_distance(a: MonetaryAction, b: MonetaryAction) -> float:
    return sum(
        (getattr(a, field_name) - getattr(b, field_name)) ** 2
        for field_name in MonetaryAction.__dataclass_fields__
    )


class ConstrainedMonetaryEnv:
    """Offline/model-based RL boundary around the hard monetary constitution.

    The environment never executes monetary actions. It evaluates observations
    and bounded decisions for research/training. Production execution belongs to
    a separate authorised policy/ledger service after audit and human governance.
    """

    def __init__(
        self,
        constitution: Constitution | None = None,
        weights: RewardWeights | None = None,
        target_inflation: float = 0.02,
        target_lcr: float = 2.0,
        target_reserve_coverage: float = 1.5,
    ) -> None:
        self.constitution = constitution or Constitution()
        self.weights = weights or RewardWeights()
        self.target_inflation = target_inflation
        self.target_lcr = target_lcr
        self.target_reserve_coverage = target_reserve_coverage

    def reward(
        self,
        next_state: MonetaryState,
        bounded_action: MonetaryAction,
        previous_action: MonetaryAction | None = None,
    ) -> float:
        w = self.weights
        score = 0.0
        score -= w.inflation * (next_state.inflation - self.target_inflation) ** 2
        score -= w.output_gap * next_state.output_gap**2
        score -= w.unemployment_gap * next_state.unemployment_gap**2
        score -= w.liquidity_shortfall * max(
            0.0,
            self.target_lcr - next_state.liquidity_coverage_ratio,
        ) ** 2
        score -= w.npl * next_state.nonperforming_loan_ratio**2
        score -= w.reserve_shortfall * max(
            0.0,
            self.target_reserve_coverage - next_state.reserve_coverage_ratio,
        ) ** 2
        score += w.external_pnl * next_state.external_pnl_ratio
        score += w.solvency_margin * max(0.0, next_state.hard_nav_ratio - 1.0)
        if previous_action is not None:
            score -= w.policy_change * _action_distance(bounded_action, previous_action)
        return score

    def evaluate_transition(
        self,
        state: MonetaryState,
        proposed_residual: MonetaryResidual,
        observed_next_state: MonetaryState,
        *,
        previous_action: MonetaryAction | None = None,
        midas_drawdown: float = 0.0,
        unbacked_mint: float = 0.0,
        flash_debt_at_commit: float = 0.0,
        loan_maturity_weeks: float | None = None,
        funding_maturity_weeks: float | None = None,
    ) -> PolicyTransition:
        decision = self.constitution.decide(
            state,
            proposed_residual,
            midas_drawdown=midas_drawdown,
            unbacked_mint=unbacked_mint,
            flash_debt_at_commit=flash_debt_at_commit,
            loan_maturity_weeks=loan_maturity_weeks,
            funding_maturity_weeks=funding_maturity_weeks,
        )
        reward = self.reward(
            observed_next_state,
            decision.bounded,
            previous_action,
        )
        if decision.invariant_failures:
            # Large explicit research penalty, while the hard shield already
            # prevents the prohibited action from reaching the bounded decision.
            reward -= 100.0 * len(decision.invariant_failures)
        return PolicyTransition(
            state=state,
            proposed_residual=proposed_residual,
            decision=decision,
            observed_next_state=observed_next_state,
            reward=reward,
        )
