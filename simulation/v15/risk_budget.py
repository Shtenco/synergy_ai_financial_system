#!/usr/bin/env python3
"""V15 drawdown-aware risk-budget reference.

Solvency ratios answer whether a state is admissible; a fund also needs a bounded
loss budget for the next action. V15 never increases size merely to recover a
loss. As drawdown consumes the high-water-mark budget, available risk shrinks.

This is an off-chain policy/reference layer. On-chain execution remains protected
by post-state Economic HardNAV/K/STS/portfolio gates.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class RiskState:
    hard_nav: float
    high_water_nav: float
    solvency_loss_headroom: float
    daily_loss_used: float
    daily_loss_limit: float
    max_hwm_drawdown: float
    turnover_remaining: float

    def __post_init__(self):
        if self.hard_nav < 0 or self.high_water_nav < 0 or self.solvency_loss_headroom < 0:
            raise ValueError("negative risk state")
        if self.daily_loss_used < 0 or self.daily_loss_limit < 0 or self.turnover_remaining < 0:
            raise ValueError("negative budget")
        if not (0 < self.max_hwm_drawdown < 1):
            raise ValueError("bad max drawdown")

    @property
    def drawdown(self) -> float:
        if self.high_water_nav <= 0:
            return 0.0
        return max(0.0, (self.high_water_nav - self.hard_nav) / self.high_water_nav)

    @property
    def remaining_drawdown_loss(self) -> float:
        max_loss_from_hwm = self.max_hwm_drawdown * self.high_water_nav
        used = max(0.0, self.high_water_nav - self.hard_nav)
        return max(0.0, max_loss_from_hwm - used)

    @property
    def remaining_daily_loss(self) -> float:
        return max(0.0, self.daily_loss_limit - self.daily_loss_used)

    @property
    def action_loss_budget(self) -> float:
        return max(0.0, min(
            self.solvency_loss_headroom,
            self.remaining_daily_loss,
            self.remaining_drawdown_loss,
        ))


@dataclass(frozen=True)
class ActionRisk:
    worst_case_loss_rate: float
    hard_turnover_per_notional: float
    minimum_notional: float = 0.0

    def __post_init__(self):
        if self.worst_case_loss_rate <= 0 or self.hard_turnover_per_notional <= 0:
            raise ValueError("risk rates must be positive")
        if self.minimum_notional < 0:
            raise ValueError("negative minimum notional")


def max_notional(state: RiskState, risk: ActionRisk) -> float:
    """Maximum notional consistent with loss and turnover budgets."""
    by_loss = state.action_loss_budget / risk.worst_case_loss_rate
    by_turnover = state.turnover_remaining / risk.hard_turnover_per_notional
    n = max(0.0, min(by_loss, by_turnover))
    return n if n + 1e-12 >= risk.minimum_notional else 0.0


def drawdown_multiplier(drawdown: float, soft_drawdown: float, hard_drawdown: float) -> float:
    """Linear de-risking between soft and hard drawdown thresholds."""
    if not (0 <= soft_drawdown < hard_drawdown < 1):
        raise ValueError("bad drawdown thresholds")
    if drawdown <= soft_drawdown:
        return 1.0
    if drawdown >= hard_drawdown:
        return 0.0
    return (hard_drawdown - drawdown) / (hard_drawdown - soft_drawdown)


def scaled_max_notional(
    state: RiskState,
    risk: ActionRisk,
    soft_drawdown: float,
    hard_drawdown: float,
) -> float:
    return max_notional(state, risk) * drawdown_multiplier(state.drawdown, soft_drawdown, hard_drawdown)


def accept_expected_log_growth(
    current_hard_nav: float,
    notional: float,
    win_probability: float,
    gain_rate: float,
    loss_rate: float,
    minimum_expected_log_growth: float = 0.0,
) -> bool:
    """Optional secondary Kelly-style sanity check after all hard constraints.

    This function never determines safety. It rejects actions whose estimated
    expected log growth is non-positive at the already risk-capped notional.
    """
    from math import log
    if current_hard_nav <= 0 or notional < 0:
        raise ValueError("bad capital/notional")
    if not (0 <= win_probability <= 1) or gain_rate < 0 or loss_rate < 0:
        raise ValueError("bad distribution estimate")
    gain = notional * gain_rate
    loss = notional * loss_rate
    if loss >= current_hard_nav:
        return False
    g_win = log((current_hard_nav + gain) / current_hard_nav)
    g_loss = log((current_hard_nav - loss) / current_hard_nav)
    expected = win_probability * g_win + (1.0 - win_probability) * g_loss
    return expected >= minimum_expected_log_growth


def main() -> None:
    risk = ActionRisk(worst_case_loss_rate=.02, hard_turnover_per_notional=2.5)
    for nav in (100, 98, 95, 92, 90):
        state = RiskState(nav, 100, 20, 1, 5, .10, 50)
        print(
            f"NAV={nav:5.1f} DD={state.drawdown:.1%} "
            f"lossBudget={state.action_loss_budget:.2f} "
            f"maxNotional={scaled_max_notional(state,risk,.03,.10):.2f}"
        )


if __name__ == "__main__":
    main()
