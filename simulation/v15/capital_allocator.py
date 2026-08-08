#!/usr/bin/env python3
"""V15 capital-allocation reference.

Retained allocation and external distribution are deliberately separated:
- reserve/insurance/reinvestment inside protocol accounts keeps consolidated HardNAV;
- holder/project/founder payouts and own-token buybacks send hard assets outside and reduce HardNAV.

The external distribution cap is the minimum of base-coverage, stress and absolute
risk-capital headroom, then capped again by realized profit after loss carryforward.
"""
from dataclasses import dataclass
from typing import Sequence


@dataclass(frozen=True)
class StressCapitalState:
    name: str
    stressed_assets: float
    stressed_liabilities: float
    target_sts: float

    @property
    def headroom(self) -> float:
        return self.stressed_assets - self.target_sts * self.stressed_liabilities


@dataclass(frozen=True)
class CapitalState:
    risk_assets: float
    risk_liabilities: float
    target_coverage: float
    min_risk_assets: float
    scenarios: Sequence[StressCapitalState]

    @property
    def base_coverage_headroom(self) -> float:
        return self.risk_assets - self.target_coverage * self.risk_liabilities

    @property
    def absolute_capital_headroom(self) -> float:
        return self.risk_assets - self.min_risk_assets

    @property
    def stress_headroom(self) -> float:
        if not self.scenarios:
            return float("-inf")
        return min(s.headroom for s in self.scenarios)

    @property
    def distribution_headroom(self) -> float:
        # Conservatively assume one canonical USD distributed can reduce risk
        # assets by as much as one risk USD. Post-transfer concentration is a
        # separate hard gate in the on-chain controller.
        return max(0.0, min(
            self.base_coverage_headroom,
            self.absolute_capital_headroom,
            self.stress_headroom,
        ))


@dataclass(frozen=True)
class Allocation:
    operating_pnl: float
    prior_loss_carryforward: float
    loss_carryforward_after: float
    profit_after_loss: float
    solvency_headroom: float
    max_external_distribution: float
    retained_profit: float


def allocate(operating_pnl: float, loss_carryforward: float, capital: CapitalState) -> Allocation:
    if loss_carryforward < 0:
        raise ValueError("negative loss carryforward")

    if operating_pnl <= 0:
        loss_after = loss_carryforward + (-operating_pnl)
        profit_after_loss = 0.0
    elif operating_pnl <= loss_carryforward:
        loss_after = loss_carryforward - operating_pnl
        profit_after_loss = 0.0
    else:
        loss_after = 0.0
        profit_after_loss = operating_pnl - loss_carryforward

    headroom = capital.distribution_headroom
    external = min(profit_after_loss, headroom)
    retained = profit_after_loss - external

    return Allocation(
        operating_pnl=operating_pnl,
        prior_loss_carryforward=loss_carryforward,
        loss_carryforward_after=loss_after,
        profit_after_loss=profit_after_loss,
        solvency_headroom=headroom,
        max_external_distribution=external,
        retained_profit=retained,
    )


def main() -> None:
    state = CapitalState(
        risk_assets=160,
        risk_liabilities=100,
        target_coverage=1.30,
        min_risk_assets=120,
        scenarios=(
            StressCapitalState("depeg", 145, 105, 1.20),
            StressCapitalState("liquidity", 138, 100, 1.20),
        ),
    )
    print(allocate(25, 5, state))


if __name__ == "__main__":
    main()
