"""Deterministic savings-credit scenario for the Financial OS V4 core.

The simulation is deliberately accounting-first. It does not assume that token
price appreciation creates profit.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class SavingsCreditScenario:
    participants: int = 200
    average_monthly_income: float = 300_000.0
    savings_rate: float = 0.035
    horizon_weeks: int = 100
    average_vesting_weeks: float = 50.5
    p2p_share: float = 0.45
    borrower_apr: float = 0.24
    expected_loss_rate: float = 0.04
    servicing_rate: float = 0.025
    liquidity_cost_rate: float = 0.005
    insurance_premium_rate: float = 0.015
    saver_profit_share: float = 0.55

    @property
    def weekly_savings(self) -> float:
        return self.participants * self.average_monthly_income * 12 / 52 * self.savings_rate

    @property
    def contributions(self) -> float:
        return self.weekly_savings * self.horizon_weeks

    @property
    def steady_locked(self) -> float:
        return self.weekly_savings * self.average_vesting_weeks

    @property
    def p2p_exposure(self) -> float:
        return self.steady_locked * self.p2p_share

    @property
    def p2p_net_apr(self) -> float:
        return (
            self.borrower_apr
            - self.expected_loss_rate
            - self.servicing_rate
            - self.liquidity_cost_rate
            - self.insurance_premium_rate
        )

    @property
    def annual_p2p_profit(self) -> float:
        return max(0.0, self.p2p_exposure * self.p2p_net_apr)

    @property
    def annual_saver_reward(self) -> float:
        return self.annual_p2p_profit * self.saver_profit_share

    @property
    def saver_yield_on_locked(self) -> float:
        if self.steady_locked == 0:
            return 0.0
        return self.annual_saver_reward / self.steady_locked


def base_200_participant_scenario() -> SavingsCreditScenario:
    return SavingsCreditScenario()
