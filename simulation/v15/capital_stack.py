#!/usr/bin/env python3
"""V15 capital-stack reference economics.

Own-token issuance is never hard revenue. A junior recapitalization token can
improve solvency only when external investors actually contribute hard assets.
Those proceeds are capital contributions and are removed from operating PnL.

This module uses generic SYNA/SYNR/USDx names for the proposed V15 roles; it is
not a legal characterization of the tokens and does not promise distributions.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class BalanceSheet:
    hard_assets: float
    risk_assets: float
    external_liabilities: float

    @property
    def hard_nav(self) -> float:
        return self.hard_assets - self.external_liabilities

    @property
    def coverage(self) -> float:
        if self.external_liabilities == 0:
            return float("inf")
        return self.risk_assets / self.external_liabilities


def required_canonical_recapitalization(
    risk_assets: float,
    liabilities: float,
    target_coverage: float,
    contribution_risk_factor: float = 1.0,
) -> float:
    """Hard contribution required to restore a target risk-coverage ratio."""
    if min(risk_assets, liabilities) < 0 or target_coverage <= 1:
        raise ValueError("bad recapitalization input")
    if not (0 < contribution_risk_factor <= 1):
        raise ValueError("bad contribution risk factor")
    deficit = max(0.0, target_coverage * liabilities - risk_assets)
    return deficit / contribution_risk_factor


def issue_internal_token_without_hard_inflow(sheet: BalanceSheet, token_units: float) -> BalanceSheet:
    """Minting SYNA/SYNR internally changes no hard balance-sheet item."""
    if token_units < 0:
        raise ValueError("negative issuance")
    return sheet


def junior_capital_raise(
    sheet: BalanceSheet,
    hard_proceeds: float,
    proceeds_risk_factor: float,
    new_hard_redemption_liability: float = 0.0,
) -> tuple[BalanceSheet, float]:
    """Sell a non-hard-accounted junior token for external hard capital.

    Returns `(post_sheet, operating_pnl_after_capital_flow_adjustment)`.
    If the new token itself promises hard redemption, that promise is added to
    liabilities and reduces the recapitalization benefit.
    """
    if hard_proceeds < 0 or new_hard_redemption_liability < 0:
        raise ValueError("negative capital raise")
    if not (0 < proceeds_risk_factor <= 1):
        raise ValueError("bad risk factor")

    post = BalanceSheet(
        hard_assets=sheet.hard_assets + hard_proceeds,
        risk_assets=sheet.risk_assets + hard_proceeds * proceeds_risk_factor,
        external_liabilities=sheet.external_liabilities + new_hard_redemption_liability,
    )
    # Capital-flow adjusted operating PnL excludes the actual hard contribution.
    operating_pnl = post.hard_nav - sheet.hard_nav - hard_proceeds
    return post, operating_pnl


def hard_surplus_distribution(
    sheet: BalanceSheet,
    hard_amount: float,
    distributed_asset_risk_factor: float = 1.0,
) -> BalanceSheet:
    """Holder/project/founder payout OR external own-token buyback/burn."""
    if hard_amount < 0 or hard_amount > sheet.hard_assets:
        raise ValueError("bad distribution")
    if not (0 <= distributed_asset_risk_factor <= 1):
        raise ValueError("bad risk factor")
    return BalanceSheet(
        hard_assets=sheet.hard_assets - hard_amount,
        risk_assets=max(0.0, sheet.risk_assets - hard_amount * distributed_asset_risk_factor),
        external_liabilities=sheet.external_liabilities,
    )


def issue_redeemable_usdx_against_hard_deposit(
    sheet: BalanceSheet,
    hard_deposit: float,
    deposit_risk_factor: float,
    usdx_liability_created: float,
) -> BalanceSheet:
    """Permanent externally held USDx is a liability, unlike atomic QE/QT."""
    if min(hard_deposit, usdx_liability_created) < 0:
        raise ValueError("negative deposit/liability")
    if not (0 < deposit_risk_factor <= 1):
        raise ValueError("bad risk factor")
    return BalanceSheet(
        hard_assets=sheet.hard_assets + hard_deposit,
        risk_assets=sheet.risk_assets + hard_deposit * deposit_risk_factor,
        external_liabilities=sheet.external_liabilities + usdx_liability_created,
    )


def main() -> None:
    s = BalanceSheet(hard_assets=120, risk_assets=110, external_liabilities=100)
    need = required_canonical_recapitalization(s.risk_assets, s.external_liabilities, 1.30, 0.95)
    post, pnl = junior_capital_raise(s, need, 0.95)
    print("required hard recapitalization", round(need, 6))
    print("post coverage", round(post.coverage, 6))
    print("capital-flow-adjusted operating PnL", round(pnl, 6))


if __name__ == "__main__":
    main()
