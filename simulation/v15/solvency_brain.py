#!/usr/bin/env python3
"""SINERGY V15 solvency-brain reference model.

This module deliberately sits ABOVE the frozen V13.1 edge engine.
It does not generate a wedge.  It decides whether a V13.1 transition is
economically admissible.

Economic accounting and risk accounting are intentionally separated.
Own synthetics never enter Economic HardNAV as assets.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from math import inf
from typing import Dict, Iterable, Mapping, Optional, Sequence


class Mode(str, Enum):
    GREEN = "GREEN"
    YELLOW = "YELLOW"
    ORANGE = "ORANGE"
    RED = "RED"


class ActionClass(str, Enum):
    EXPAND = "EXPAND"       # new gradient / temporary QE / other risk expansion
    NEUTRAL = "NEUTRAL"     # economically neutral maintenance / rotation
    REDUCE = "REDUCE"       # hedge, repay, liability reduction
    RESTORE = "RESTORE"     # invariant restoration / gradient close


@dataclass(frozen=True)
class HardAsset:
    balance: float
    canonical_price: float
    twap_price: float
    exit_price: float
    haircut: float = 1.0

    def __post_init__(self):
        if self.balance < 0:
            raise ValueError("negative hard-asset balance")
        if min(self.canonical_price, self.twap_price, self.exit_price) < 0:
            raise ValueError("negative price")
        if not (0.0 <= self.haircut <= 1.0):
            raise ValueError("haircut must be in [0,1]")

    @property
    def hard_value(self) -> float:
        return self.balance * self.canonical_price

    @property
    def risk_mark(self) -> float:
        return min(self.canonical_price, self.twap_price, self.exit_price)

    @property
    def risk_value(self) -> float:
        return self.balance * self.risk_mark * self.haircut


@dataclass(frozen=True)
class Liability:
    amount: float
    canonical_value: float
    base_stress_multiplier: float = 1.0

    def __post_init__(self):
        if self.amount < 0 or self.canonical_value < 0:
            raise ValueError("negative liability")
        if self.base_stress_multiplier < 1.0:
            raise ValueError("liability stress multiplier must be >= 1")

    @property
    def hard_value(self) -> float:
        return self.amount * self.canonical_value

    @property
    def risk_value(self) -> float:
        return self.hard_value * self.base_stress_multiplier


@dataclass
class SyntheticLedger:
    total_supply: float
    partitions: Dict[str, float]

    def __post_init__(self):
        self.assert_conserved()

    def assert_conserved(self, tol: float = 1e-9) -> None:
        if self.total_supply < -tol or any(v < -tol for v in self.partitions.values()):
            raise ValueError("negative synthetic partition")
        if abs(sum(self.partitions.values()) - self.total_supply) > tol:
            raise ValueError("synthetic supply partition mismatch")

    def supply_neutral_transfer(self, source: str, destination: str, amount: float) -> None:
        if amount <= 0 or source == destination:
            raise ValueError("bad synthetic transfer")
        if self.partitions.get(source, 0.0) < amount:
            raise ValueError("insufficient source synthetic")
        before = self.total_supply
        self.partitions[source] -= amount
        self.partitions[destination] = self.partitions.get(destination, 0.0) + amount
        self.assert_conserved()
        if self.total_supply != before:
            raise AssertionError("supply changed during neutral transfer")


@dataclass(frozen=True)
class StressScenario:
    name: str
    asset_price_multiplier: Mapping[str, float] = field(default_factory=dict)
    liquidity_multiplier: Mapping[str, float] = field(default_factory=dict)
    liability_multiplier: Mapping[str, float] = field(default_factory=dict)
    fixed_system_cost: float = 0.0

    def __post_init__(self):
        if self.fixed_system_cost < 0:
            raise ValueError("negative stress cost")
        for table in (self.asset_price_multiplier, self.liquidity_multiplier):
            if any(v < 0 or v > 1 for v in table.values()):
                raise ValueError("asset/liquidity multiplier must be in [0,1]")
        if any(v < 1 for v in self.liability_multiplier.values()):
            raise ValueError("liability multiplier must be >= 1")


@dataclass
class BalanceSheet:
    hard_assets: Dict[str, HardAsset]
    liabilities: Dict[str, Liability]
    synthetics: Dict[str, SyntheticLedger] = field(default_factory=dict)

    def hard_assets_value(self) -> float:
        return sum(a.hard_value for a in self.hard_assets.values())

    def hard_liabilities_value(self) -> float:
        return sum(l.hard_value for l in self.liabilities.values())

    def hard_nav(self) -> float:
        return self.hard_assets_value() - self.hard_liabilities_value()

    def risk_assets_value(self) -> float:
        return sum(a.risk_value for a in self.hard_assets.values())

    def risk_liabilities_value(self) -> float:
        return sum(l.risk_value for l in self.liabilities.values())

    def risk_nav(self) -> float:
        return self.risk_assets_value() - self.risk_liabilities_value()

    def coverage(self) -> float:
        liab = self.risk_liabilities_value()
        return inf if liab == 0 else self.risk_assets_value() / liab

    def sts_scenario(self, s: StressScenario) -> float:
        liquid = -s.fixed_system_cost
        for name, a in self.hard_assets.items():
            pm = s.asset_price_multiplier.get(name, 1.0)
            lm = s.liquidity_multiplier.get(name, 1.0)
            liquid += a.balance * a.risk_mark * a.haircut * pm * lm

        liabilities = 0.0
        for name, l in self.liabilities.items():
            lm = s.liability_multiplier.get(name, 1.0)
            liabilities += l.risk_value * lm

        return inf if liabilities == 0 else liquid / liabilities

    def sts(self, scenarios: Sequence[StressScenario]) -> float:
        if not scenarios:
            raise ValueError("stress set must not be empty")
        return min(self.sts_scenario(s) for s in scenarios)

    def assert_supply_ledgers(self) -> None:
        for ledger in self.synthetics.values():
            ledger.assert_conserved()


@dataclass(frozen=True)
class RiskPolicy:
    min_hard_nav: float = 0.0
    min_coverage_green: float = 1.30
    min_coverage_yellow: float = 1.15
    min_coverage_orange: float = 1.05
    min_sts_green: float = 1.30
    min_sts_yellow: float = 1.15
    min_sts_orange: float = 1.05
    green_reentry_buffer: float = 0.05
    yellow_reentry_buffer: float = 0.03
    max_defensive_nav_cost: float = 0.02

    def __post_init__(self):
        if not (self.min_sts_green > self.min_sts_yellow > self.min_sts_orange > 1.0):
            raise ValueError("bad STS thresholds")
        if not (self.min_coverage_green > self.min_coverage_yellow > self.min_coverage_orange > 1.0):
            raise ValueError("bad coverage thresholds")


@dataclass(frozen=True)
class Candidate:
    name: str
    delta_hard_nav: float
    oracle_uncertainty: float
    system_cost: float
    post_hard_nav: float
    pre_coverage: float
    post_coverage: float
    pre_sts: float
    post_sts: float
    action_class: ActionClass = ActionClass.EXPAND
    supply_ok: bool = True
    accounting_ok: bool = True
    atomic_qe_ok: bool = True

    @property
    def robust_gain(self) -> float:
        return self.delta_hard_nav - self.oracle_uncertainty - self.system_cost

    @property
    def solvency_nonworsening(self) -> bool:
        return self.post_coverage + 1e-12 >= self.pre_coverage and self.post_sts + 1e-12 >= self.pre_sts

    @property
    def solvency_improving(self) -> bool:
        return self.solvency_nonworsening and (
            self.post_coverage > self.pre_coverage + 1e-12 or self.post_sts > self.pre_sts + 1e-12
        )


class SolvencyBrain:
    def __init__(self, policy: RiskPolicy, min_robust_gain: float = 0.0):
        if min_robust_gain < 0:
            raise ValueError("negative min gain")
        self.policy = policy
        self.min_robust_gain = min_robust_gain

    def classify(self, sheet: BalanceSheet, scenarios: Sequence[StressScenario], previous: Mode) -> Mode:
        k = sheet.coverage()
        s = sheet.sts(scenarios)

        if sheet.hard_nav() < self.policy.min_hard_nav:
            return Mode.RED
        if k < self.policy.min_coverage_orange or s < self.policy.min_sts_orange:
            return Mode.RED

        if previous == Mode.RED:
            if (k >= self.policy.min_coverage_yellow + self.policy.yellow_reentry_buffer and
                    s >= self.policy.min_sts_yellow + self.policy.yellow_reentry_buffer):
                return Mode.YELLOW
            return Mode.ORANGE

        if previous == Mode.ORANGE:
            if (k >= self.policy.min_coverage_yellow + self.policy.yellow_reentry_buffer and
                    s >= self.policy.min_sts_yellow + self.policy.yellow_reentry_buffer):
                return Mode.YELLOW
            return Mode.ORANGE

        if previous == Mode.YELLOW:
            if (k >= self.policy.min_coverage_green + self.policy.green_reentry_buffer and
                    s >= self.policy.min_sts_green + self.policy.green_reentry_buffer):
                return Mode.GREEN
            if k < self.policy.min_coverage_yellow or s < self.policy.min_sts_yellow:
                return Mode.ORANGE
            return Mode.YELLOW

        if k < self.policy.min_coverage_green or s < self.policy.min_sts_green:
            return Mode.YELLOW
        return Mode.GREEN

    def admissible(self, c: Candidate, mode: Mode) -> bool:
        if not (c.supply_ok and c.accounting_ok and c.atomic_qe_ok):
            return False
        if c.post_hard_nav < self.policy.min_hard_nav:
            return False

        if mode == Mode.RED and c.action_class not in (ActionClass.REDUCE, ActionClass.RESTORE):
            return False
        if mode == Mode.ORANGE and c.action_class == ActionClass.EXPAND:
            return False

        if c.action_class == ActionClass.EXPAND:
            if mode == Mode.GREEN:
                kmin, smin = self.policy.min_coverage_green, self.policy.min_sts_green
            elif mode == Mode.YELLOW:
                kmin, smin = self.policy.min_coverage_yellow, self.policy.min_sts_yellow
            else:
                return False
            if c.post_coverage < kmin or c.post_sts < smin:
                return False
            return c.robust_gain >= self.min_robust_gain

        if c.action_class == ActionClass.NEUTRAL:
            return c.robust_gain >= 0 and c.solvency_nonworsening

        if c.robust_gain < -self.policy.max_defensive_nav_cost:
            return False
        if c.action_class == ActionClass.REDUCE:
            return c.solvency_improving

        return c.solvency_nonworsening

    def choose(self, candidates: Iterable[Candidate], mode: Mode) -> Optional[Candidate]:
        safe = [c for c in candidates if self.admissible(c, mode)]
        if not safe:
            return None
        return max(safe, key=lambda c: c.robust_gain)


def operating_hard_pnl(nav_before: float, nav_after: float, contributions: float = 0.0,
                       withdrawals: float = 0.0) -> float:
    if contributions < 0 or withdrawals < 0:
        raise ValueError("negative capital flow")
    return nav_after - nav_before - contributions + withdrawals


def revenue_waterfall(distributable_pnl: float, required_reserve_topup: float,
                      requested_allocations: Mapping[str, float]) -> Dict[str, float]:
    if distributable_pnl < 0 or required_reserve_topup < 0:
        raise ValueError("negative waterfall input")
    if any(v < 0 for v in requested_allocations.values()):
        raise ValueError("negative allocation")
    budget = max(0.0, distributable_pnl - required_reserve_topup)
    requested = sum(requested_allocations.values())
    if requested <= budget:
        return dict(requested_allocations)
    if requested == 0:
        return {k: 0.0 for k in requested_allocations}
    scale = budget / requested
    return {k: v * scale for k, v in requested_allocations.items()}


def cp_out(reserve_in: float, reserve_out: float, amount_in: float, fee: float = 0.003) -> float:
    effective = amount_in * (1.0 - fee)
    return reserve_out * effective / (reserve_in + effective)


@dataclass(frozen=True)
class V13FixtureResult:
    gross_profit: float
    protocol_tax: float
    solver_reward: float
    protocol_hardnav_delta: float
    external_hardnav_delta: float
    conservation_residual: float


def v13_two_pool_fixture(external_b_reserve: float, principal_b: float = 39.8,
                         gradient: float = 40.0, tax_share: float = 0.99,
                         reward_floor: float = 0.001) -> V13FixtureResult:
    """Exact floating reference for the V13.1 two-pool route at A=B=$1 marks."""
    source_syn = 100.0 - gradient
    destination_syn = 100.0 + gradient

    z = cp_out(100.0, destination_syn, principal_b)
    a_out = cp_out(source_syn, 100.0, z)
    b_returned = cp_out(10_000.0, external_b_reserve, a_out)
    gross = b_returned - principal_b

    if gross <= reward_floor:
        tax = 0.0
        solver = gross
    else:
        tax = min(tax_share * gross, gross - reward_floor)
        solver = gross - tax

    protocol = principal_b + tax - a_out
    external = a_out - b_returned
    residual = protocol + external + solver

    return V13FixtureResult(
        gross_profit=gross,
        protocol_tax=tax,
        solver_reward=solver,
        protocol_hardnav_delta=protocol,
        external_hardnav_delta=external,
        conservation_residual=residual,
    )


def best_executable_v13_protocol_delta(external_b_reserve: float,
                                         principal_max: float = 70.0,
                                         steps: int = 5000,
                                         reward_floor: float = 0.001) -> Optional[V13FixtureResult]:
    best: Optional[V13FixtureResult] = None
    for i in range(1, steps + 1):
        p = principal_max * i / steps
        r = v13_two_pool_fixture(external_b_reserve, principal_b=p, reward_floor=reward_floor)
        if r.gross_profit <= reward_floor:
            continue
        if best is None or r.protocol_hardnav_delta > best.protocol_hardnav_delta:
            best = r
    return best
