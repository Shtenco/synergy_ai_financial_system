from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import Enum
from math import isfinite
from typing import Iterable, Mapping

EPS = 1e-9


class TokenRole(str, Enum):
    CAPITAL = "SYNA"
    RESERVE = "SYNR"
    MONEY = "SYNT"


@dataclass(frozen=True)
class AssetPosition:
    """Externally attributable asset.

    `hard_haircut` is deliberately explicit. An internally issued SINERGY token
    should normally use a hard haircut of 0.0 because its own market cap is not
    external redeemable backing.
    """

    name: str
    value: float
    hard_haircut: float = 1.0
    liquid_haircut: float = 1.0
    economic_haircut: float = 1.0

    def __post_init__(self) -> None:
        if self.value < -EPS:
            raise ValueError("asset value cannot be negative")
        for field_name in ("hard_haircut", "liquid_haircut", "economic_haircut"):
            h = getattr(self, field_name)
            if not 0.0 <= h <= 1.0:
                raise ValueError(f"{field_name} must be in [0, 1]")


@dataclass(frozen=True)
class LiabilityPosition:
    name: str
    value: float
    seniority: int = 0

    def __post_init__(self) -> None:
        if self.value < -EPS:
            raise ValueError("liability value cannot be negative")


@dataclass
class BalanceSheet:
    assets: list[AssetPosition] = field(default_factory=list)
    liabilities: list[LiabilityPosition] = field(default_factory=list)
    net_new_capital: float = 0.0

    @staticmethod
    def _asset_value(assets: Iterable[AssetPosition], haircut_attr: str) -> float:
        return sum(a.value * getattr(a, haircut_attr) for a in assets)

    @property
    def liabilities_total(self) -> float:
        return sum(x.value for x in self.liabilities)

    @property
    def hard_assets(self) -> float:
        return self._asset_value(self.assets, "hard_haircut")

    @property
    def liquid_assets(self) -> float:
        return self._asset_value(self.assets, "liquid_haircut")

    @property
    def economic_assets(self) -> float:
        return self._asset_value(self.assets, "economic_haircut")

    @property
    def hard_nav(self) -> float:
        return self.hard_assets - self.liabilities_total

    @property
    def liquid_nav(self) -> float:
        return self.liquid_assets - self.liabilities_total

    @property
    def economic_nav(self) -> float:
        return self.economic_assets - self.liabilities_total

    def distributable_profit(self, previous_hard_nav: float) -> float:
        """Profit after excluding capital contributed by users/investors.

        This is the accounting guard against treating deposits, internal minting,
        self-token price changes or virtual liquidity as profit.
        """

        return max(0.0, self.hard_nav - previous_hard_nav - self.net_new_capital)


@dataclass(frozen=True)
class MonetaryState:
    inflation: float
    output_gap: float
    unemployment_gap: float
    velocity_gap: float
    hard_nav_ratio: float
    liquidity_coverage_ratio: float
    nonperforming_loan_ratio: float
    reserve_coverage_ratio: float
    upcoming_unlock_ratio_8w: float
    external_pnl_ratio: float


@dataclass(frozen=True)
class MonetaryAction:
    demurrage_rate: float = 0.0
    term_savings_reward_rate: float = 0.0
    credit_cap_ratio: float = 0.45
    productive_qe_ratio: float = 0.0
    qt_ratio: float = 0.0
    insurance_target_ratio: float = 0.15
    reserve_target_ratio: float = 0.20
    midas_cap_ratio: float = 0.15
    buyback_profit_share: float = 0.05


@dataclass(frozen=True)
class MonetaryResidual:
    """RL proposal expressed only as deltas around the deterministic policy."""

    demurrage_rate: float = 0.0
    term_savings_reward_rate: float = 0.0
    credit_cap_ratio: float = 0.0
    productive_qe_ratio: float = 0.0
    qt_ratio: float = 0.0
    insurance_target_ratio: float = 0.0
    reserve_target_ratio: float = 0.0
    midas_cap_ratio: float = 0.0
    buyback_profit_share: float = 0.0


@dataclass(frozen=True)
class PolicyBounds:
    demurrage_rate: tuple[float, float] = (0.0, 0.06)
    term_savings_reward_rate: tuple[float, float] = (0.0, 0.15)
    credit_cap_ratio: tuple[float, float] = (0.0, 0.60)
    productive_qe_ratio: tuple[float, float] = (0.0, 0.10)
    qt_ratio: tuple[float, float] = (0.0, 0.20)
    insurance_target_ratio: tuple[float, float] = (0.10, 0.40)
    reserve_target_ratio: tuple[float, float] = (0.15, 0.60)
    midas_cap_ratio: tuple[float, float] = (0.0, 0.15)
    buyback_profit_share: tuple[float, float] = (0.0, 0.10)


@dataclass(frozen=True)
class PolicyDecision:
    baseline: MonetaryAction
    rl_residual: MonetaryResidual
    bounded: MonetaryAction
    mode: str
    invariant_failures: tuple[str, ...] = ()


def _clip(x: float, bounds: tuple[float, float]) -> float:
    lo, hi = bounds
    if not isfinite(x):
        raise ValueError("policy value must be finite")
    return min(hi, max(lo, x))


def _add_actions(a: MonetaryAction, b: MonetaryResidual) -> MonetaryAction:
    values = {
        field_name: getattr(a, field_name) + getattr(b, field_name)
        for field_name in MonetaryAction.__dataclass_fields__
    }
    return MonetaryAction(**values)


class Constitution:
    """Hard constraints around a deterministic monetary policy plus bounded RL.

    RL is allowed to recommend *residual* changes. It never gets authority to
    violate solvency, liquidity, maturity or risk invariants.
    """

    def __init__(
        self,
        bounds: PolicyBounds | None = None,
        min_hard_nav_ratio: float = 1.0,
        min_lcr: float = 1.5,
        max_npl_ratio: float = 0.12,
        max_midas_drawdown: float = 0.08,
    ) -> None:
        self.bounds = bounds or PolicyBounds()
        self.min_hard_nav_ratio = min_hard_nav_ratio
        self.min_lcr = min_lcr
        self.max_npl_ratio = max_npl_ratio
        self.max_midas_drawdown = max_midas_drawdown

    def baseline_policy(self, state: MonetaryState) -> MonetaryAction:
        # Taylor-like deterministic anchor plus countercyclical reserve logic.
        overheating = max(0.0, state.inflation - 0.02) + max(0.0, state.output_gap)
        weakness = max(0.0, -state.output_gap) + max(0.0, -state.inflation)
        stress = max(0.0, 1.5 - state.liquidity_coverage_ratio)
        credit_stress = max(0.0, state.nonperforming_loan_ratio - 0.04)

        return MonetaryAction(
            demurrage_rate=0.01 * overheating,
            term_savings_reward_rate=0.04 + 0.03 * overheating,
            credit_cap_ratio=0.45 - 0.50 * credit_stress - 0.15 * stress,
            productive_qe_ratio=0.02 * weakness,
            qt_ratio=0.05 * overheating,
            insurance_target_ratio=0.15 + 0.40 * credit_stress,
            reserve_target_ratio=0.20 + 0.30 * stress + 0.20 * credit_stress,
            midas_cap_ratio=0.10 if stress == 0 else 0.05,
            buyback_profit_share=0.05 if state.external_pnl_ratio > 0 else 0.0,
        )

    def _bound(self, action: MonetaryAction) -> MonetaryAction:
        values = {}
        for field_name in MonetaryAction.__dataclass_fields__:
            values[field_name] = _clip(
                getattr(action, field_name),
                getattr(self.bounds, field_name),
            )
        return MonetaryAction(**values)

    def invariant_failures(
        self,
        state: MonetaryState,
        *,
        midas_drawdown: float = 0.0,
        unbacked_mint: float = 0.0,
        flash_debt_at_commit: float = 0.0,
        loan_maturity_weeks: float | None = None,
        funding_maturity_weeks: float | None = None,
    ) -> tuple[str, ...]:
        failures: list[str] = []
        if state.hard_nav_ratio < self.min_hard_nav_ratio - EPS:
            failures.append("HARD_NAV_COVERAGE")
        if state.liquidity_coverage_ratio < self.min_lcr - EPS:
            failures.append("LIQUIDITY_COVERAGE")
        if state.nonperforming_loan_ratio > self.max_npl_ratio + EPS:
            failures.append("NPL_LIMIT")
        if midas_drawdown > self.max_midas_drawdown + EPS:
            failures.append("MIDAS_DRAWDOWN")
        if unbacked_mint > EPS:
            failures.append("UNBACKED_MINT")
        if flash_debt_at_commit > EPS:
            failures.append("FLASH_DEBT_AT_COMMIT")
        if loan_maturity_weeks is not None and funding_maturity_weeks is not None:
            if loan_maturity_weeks >= funding_maturity_weeks - EPS:
                failures.append("MATURITY_MISMATCH")
        return tuple(failures)

    def decide(
        self,
        state: MonetaryState,
        rl_residual: MonetaryResidual | None = None,
        **invariant_inputs: float,
    ) -> PolicyDecision:
        baseline = self._bound(self.baseline_policy(state))
        residual = rl_residual or MonetaryResidual()
        bounded = self._bound(_add_actions(baseline, residual))
        failures = self.invariant_failures(state, **invariant_inputs)

        if failures:
            # Fail-safe policy: do not create new risk while servicing redemptions.
            bounded = replace(
                bounded,
                demurrage_rate=0.0,
                credit_cap_ratio=0.0,
                productive_qe_ratio=0.0,
                qt_ratio=max(bounded.qt_ratio, 0.05),
                midas_cap_ratio=0.0,
                buyback_profit_share=0.0,
                reserve_target_ratio=max(bounded.reserve_target_ratio, 0.40),
                insurance_target_ratio=max(bounded.insurance_target_ratio, 0.20),
            )
            mode = "EMERGENCY"
        elif (
            state.liquidity_coverage_ratio < 2.0
            or state.nonperforming_loan_ratio > 0.08
        ):
            bounded = replace(
                bounded,
                midas_cap_ratio=min(bounded.midas_cap_ratio, 0.05),
                buyback_profit_share=0.0,
                credit_cap_ratio=min(bounded.credit_cap_ratio, 0.30),
            )
            mode = "DEFENSE"
        elif state.inflation < 0.01 and state.output_gap < 0:
            mode = "GROWTH"
        else:
            mode = "NORMAL"

        return PolicyDecision(baseline, residual, bounded, mode, failures)


@dataclass
class TripleMoneyLedger:
    """Minimal monetary-accounting model for SYNA/SYNR/SYNT roles."""

    syna_equity_units: float = 0.0
    synr_reserve_units: float = 0.0
    synt_money_units: float = 0.0
    hard_reserve_value: float = 0.0
    reserve_basket_value: float = 0.0
    external_liabilities: float = 0.0

    def synt_coverage(self) -> float:
        if self.synt_money_units <= EPS:
            return float("inf")
        return self.hard_reserve_value / self.synt_money_units

    def synr_nav(self) -> float:
        if self.synr_reserve_units <= EPS:
            return 0.0
        return self.reserve_basket_value / self.synr_reserve_units

    def syna_nav(self) -> float:
        if self.syna_equity_units <= EPS:
            return 0.0
        equity = max(0.0, self.reserve_basket_value - self.external_liabilities)
        return equity / self.syna_equity_units

    def mint_synt_backed(self, amount: float, hard_backing_received: float) -> None:
        if amount <= 0 or hard_backing_received + EPS < amount:
            raise ValueError(
                "SYNT mint must be fully hard-backed at par in this reference core"
            )
        self.synt_money_units += amount
        self.hard_reserve_value += hard_backing_received
        self.reserve_basket_value += hard_backing_received

    def redeem_synt(self, amount: float) -> float:
        if amount <= 0 or amount > self.synt_money_units + EPS:
            raise ValueError("invalid redemption amount")
        if self.hard_reserve_value + EPS < amount:
            raise RuntimeError("insufficient hard reserve")
        self.synt_money_units -= amount
        self.hard_reserve_value -= amount
        self.reserve_basket_value -= amount
        return amount

    def allocate_realized_profit(
        self,
        profit: float,
        waterfall: Mapping[str, float],
    ) -> dict[str, float]:
        if profit < -EPS:
            raise ValueError("profit cannot be negative")
        if abs(sum(waterfall.values()) - 1.0) > 1e-8:
            raise ValueError("waterfall shares must sum to 1")
        return {name: profit * share for name, share in waterfall.items()}
