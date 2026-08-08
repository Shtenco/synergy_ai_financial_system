#!/usr/bin/env python3
"""V15 junior recapitalization auction reference.

The purpose of a SYNR-like recap auction is to raise ACTUAL external hard capital
when the system needs it. Own-token issuance itself has zero hard value and the
hard proceeds are capital contributions, not operating revenue.

This model focuses on solvency restoration, dilution limits and funding failure.
It is not a securities/legal characterization and contains no return promise.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Optional, Sequence


@dataclass(frozen=True)
class RecapState:
    risk_assets: float
    liabilities: float
    target_coverage: float
    contribution_risk_factor: float
    existing_synr_supply: float
    max_post_raise_dilution: float

    def __post_init__(self):
        if min(self.risk_assets, self.liabilities, self.existing_synr_supply) < 0:
            raise ValueError("negative recap state")
        if self.target_coverage <= 1:
            raise ValueError("target coverage must exceed 1")
        if not (0 < self.contribution_risk_factor <= 1):
            raise ValueError("bad contribution risk factor")
        if not (0 < self.max_post_raise_dilution < 1):
            raise ValueError("bad dilution limit")

    @property
    def hard_capital_required(self) -> float:
        deficit = max(0.0, self.target_coverage * self.liabilities - self.risk_assets)
        return deficit / self.contribution_risk_factor

    @property
    def max_new_synr(self) -> float:
        """Solve new/(old+new) <= max_post_raise_dilution."""
        d = self.max_post_raise_dilution
        if self.existing_synr_supply == 0:
            return float("inf")
        return self.existing_synr_supply * d / (1.0 - d)


@dataclass(frozen=True)
class AuctionBid:
    hard_capital: float
    synr_price_hard: float

    def __post_init__(self):
        if self.hard_capital <= 0 or self.synr_price_hard <= 0:
            raise ValueError("invalid recap bid")

    @property
    def synr_requested(self) -> float:
        return self.hard_capital / self.synr_price_hard


@dataclass(frozen=True)
class AuctionOutcome:
    successful: bool
    hard_capital_raised: float
    synr_issued: float
    clearing_price: float
    post_risk_assets: float
    post_coverage: float
    post_raise_dilution: float
    operating_pnl: float
    reason: str


def minimum_clearing_price_for_dilution(state: RecapState) -> float:
    need = state.hard_capital_required
    if need == 0:
        return 0.0
    qmax = state.max_new_synr
    if qmax == float("inf"):
        return 0.0
    return need / qmax


def clear_uniform_price_auction(
    state: RecapState,
    bids: Sequence[AuctionBid],
    minimum_price: float = 0.0,
) -> AuctionOutcome:
    """Fill highest-price hard-capital bids until required recap is raised.

    The model is deliberately conservative:
    - no oversubscription is needed once target hard capital is reached;
    - one uniform clearing price equal to the lowest accepted price;
    - if dilution constraint cannot be met at the clearing price, auction fails;
    - partial capital raise below the solvency target is not labeled success.
    """
    if minimum_price < 0:
        raise ValueError("negative minimum price")

    need = state.hard_capital_required
    if need == 0:
        return AuctionOutcome(True, 0.0, 0.0, 0.0, state.risk_assets,
                              float("inf") if state.liabilities == 0 else state.risk_assets / state.liabilities,
                              0.0, 0.0, "already-capitalized")

    dilution_floor = minimum_clearing_price_for_dilution(state)
    reserve_price = max(minimum_price, dilution_floor)
    eligible = sorted((b for b in bids if b.synr_price_hard >= reserve_price),
                      key=lambda b: b.synr_price_hard, reverse=True)

    raised = 0.0
    accepted: list[tuple[AuctionBid, float]] = []
    clearing = 0.0
    for bid in eligible:
        remaining = need - raised
        if remaining <= 0:
            break
        hard = min(bid.hard_capital, remaining)
        if hard <= 0:
            continue
        accepted.append((bid, hard))
        raised += hard
        clearing = bid.synr_price_hard

    if raised + 1e-12 < need:
        return AuctionOutcome(False, raised, 0.0, clearing, state.risk_assets,
                              state.risk_assets / state.liabilities if state.liabilities else float("inf"),
                              0.0, 0.0, "insufficient-hard-demand")

    # Uniform-price issuance: all accepted hard capital purchases SYNR at clearing price.
    issued = raised / clearing if clearing > 0 else float("inf")
    if issued > state.max_new_synr + 1e-12:
        return AuctionOutcome(False, raised, issued, clearing, state.risk_assets,
                              state.risk_assets / state.liabilities if state.liabilities else float("inf"),
                              0.0, 0.0, "dilution-limit")

    post_risk = state.risk_assets + raised * state.contribution_risk_factor
    coverage = float("inf") if state.liabilities == 0 else post_risk / state.liabilities
    post_supply = state.existing_synr_supply + issued
    dilution = 0.0 if post_supply == 0 else issued / post_supply

    # Actual hard capital is a capital contribution. It raises HardNAV but is removed
    # from capital-flow-adjusted operating PnL by definition.
    return AuctionOutcome(
        successful=coverage + 1e-12 >= state.target_coverage,
        hard_capital_raised=raised,
        synr_issued=issued,
        clearing_price=clearing,
        post_risk_assets=post_risk,
        post_coverage=coverage,
        post_raise_dilution=dilution,
        operating_pnl=0.0,
        reason="target-restored" if coverage + 1e-12 >= state.target_coverage else "target-not-restored",
    )


def main() -> None:
    state = RecapState(
        risk_assets=110,
        liabilities=100,
        target_coverage=1.30,
        contribution_risk_factor=0.95,
        existing_synr_supply=1_000,
        max_post_raise_dilution=0.10,
    )
    bids = [
        AuctionBid(8, 0.50),
        AuctionBid(8, 0.35),
        AuctionBid(8, 0.25),
        AuctionBid(8, 0.20),
    ]
    print("required capital", state.hard_capital_required)
    print("dilution reserve price", minimum_clearing_price_for_dilution(state))
    print(clear_uniform_price_auction(state, bids))


if __name__ == "__main__":
    main()
