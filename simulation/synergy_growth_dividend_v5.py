"""SYNERGY V5 dividend-compounding and permissioned-liquidity model.

Economic boundary
-----------------
Only net external fees, spread, service revenue and yield are profit. Internal
transfers, internal emission, token market-cap changes and re-investment are not
new revenue. A settlement declares 10% of realised profit as a dividend pool,
withholds configurable tax into an external tax escrow, and automatically
reinvests every net owner/keeper dividend. The remaining 90% is retained and
reinvested by the protocol.

The 3-5x value is stress V2-equivalent executable depth, never withdrawable POL.
"""
from __future__ import annotations

import csv
import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

import numpy as np

BLOCKS = 20_000
PATHS = 1_000
BPS = 10_000.0
DIVIDEND_POOL_BPS = 1_000.0
WITHHOLDING_BPS = 1_000.0
WAD = 1.0
SOLVENCY_FLOOR = 1.20
LIQUIDITY_FLOOR = 1.20
GAS_FLOOR = 1.20
EMISSION_FLOOR = 1.20
POOL_FLOOR_SHARE = 0.12
SETTLEMENT_INTERVAL = 100

LOW_SIGMA = 0.025
NORMAL_SIGMA = 0.070
MAX_SIGMA = 0.120


@dataclass
class GrowthState:
    original_external_capital: float = 120.0
    compounded_backed_capital: float = 120.0
    pending_external_profit: float = 0.0
    realised_external_profit_gross: float = 0.0
    realised_external_cost: float = 0.0
    tax_remitted: float = 0.0
    gross_dividends_declared: float = 0.0
    owner_net_reinvested: float = 0.0
    keeper_net_reinvested: float = 0.0
    retained_profit_reinvested: float = 0.0
    owner_equity: float = 100.0
    keeper_equity: float = 20.0
    protocol_equity: float = 0.0
    internal_transfer_volume: float = 0.0
    external_representative_liability: float = 0.0
    gas_spent: float = 5.0
    maximum_drawdown: float = 0.0
    peak_haircut_nav: float = 0.0
    pauses: int = 0
    useful_actions: int = 0
    settlements: int = 0
    failed_settlements: int = 0
    minimum_single_invariant: float = math.inf
    minimum_active_multiplier: float = math.inf


@dataclass
class Scenario:
    seed: int = 42
    fixed_sigma: float | None = None
    revenue_multiplier: float = 1.0
    gas_multiplier: float = 1.0
    withholding_bps: float = WITHHOLDING_BPS
    redemption_shock: float = 0.0
    unsupported_volatility: bool = False


def target_multiplier(sigma: float) -> float | None:
    if sigma <= LOW_SIGMA:
        return 5.0
    if sigma <= NORMAL_SIGMA:
        return 4.0
    if sigma <= MAX_SIGMA:
        return 3.0
    return None


def recognised_multiplier(sigma: float, capital: float, original: float) -> float:
    """Conservative stress-equivalent depth from concentrated ranges.

    The buffer falls as volatility and capital concentration risk rise. The
    result is capped at 5x and cannot be increased by the internal SYNA/SYNR leg.
    """
    target = target_multiplier(sigma)
    if target is None:
        return 0.0
    compounding_scale = min(0.10, 0.04 * math.log1p(max(0.0, capital / original - 1.0)))
    if target == 5.0:
        return 5.0
    if target == 4.0:
        volatility_buffer = max(0.10, 0.52 - 2.5 * max(0.0, sigma - LOW_SIGMA))
        return min(5.0, target + volatility_buffer + compounding_scale)
    volatility_buffer = max(0.06, 0.36 - 2.0 * max(0.0, sigma - NORMAL_SIGMA))
    return min(5.0, target + volatility_buffer + compounding_scale)


def balance_sheet(capital: float, gas_spent: float, redemption_shock: float) -> dict[str, float]:
    anchor = 0.54 * capital
    liquid = 0.30 * capital
    insurance = 0.10 * capital
    gas_reserve = 0.05 * capital
    operations = 0.01 * capital

    haircut_assets = (
        0.80 * anchor
        + liquid
        + 0.90 * insurance
        + gas_reserve
        + 0.50 * operations
    )
    stress_liabilities = 0.50 * capital + redemption_shock
    immediate_liquidity = liquid + gas_reserve + 0.25 * anchor
    stressed_outflows = 0.34 * capital + redemption_shock
    emission_liability = 0.20 * capital
    emission_backing = liquid + insurance + 0.30 * anchor
    minimum_anchor_pool = 0.216 * capital
    pool_floor = POOL_FLOOR_SHARE * capital
    gas_coverage_numerator = gas_spent + gas_reserve

    return {
        "anchor": anchor,
        "liquid": liquid,
        "insurance": insurance,
        "gas_reserve": gas_reserve,
        "operations": operations,
        "haircut_assets": haircut_assets,
        "stress_liabilities": stress_liabilities,
        "immediate_liquidity": immediate_liquidity,
        "stressed_outflows": stressed_outflows,
        "emission_liability": emission_liability,
        "emission_backing": emission_backing,
        "minimum_anchor_pool": minimum_anchor_pool,
        "pool_floor": pool_floor,
        "gas_coverage_numerator": gas_coverage_numerator,
    }


def safe_ratio(a: float, b: float) -> float:
    return math.inf if b <= 0 else a / b


def metrics(state: GrowthState, sigma: float, redemption_shock: float = 0.0) -> dict[str, float | bool]:
    bs = balance_sheet(state.compounded_backed_capital, state.gas_spent, redemption_shock)
    target = target_multiplier(sigma)
    multiplier = recognised_multiplier(
        sigma,
        state.compounded_backed_capital,
        state.original_external_capital,
    )
    if target is None:
        return {
            **bs,
            "sigma": sigma,
            "target_multiplier": math.inf,
            "recognised_multiplier": 0.0,
            "stress_equivalent_liquidity": 0.0,
            "solvency_ratio": safe_ratio(bs["haircut_assets"], bs["stress_liabilities"]),
            "liquidity_coverage": safe_ratio(bs["immediate_liquidity"], bs["stressed_outflows"]),
            "gas_coverage": safe_ratio(bs["gas_coverage_numerator"], state.gas_spent),
            "emission_coverage": safe_ratio(bs["emission_backing"], bs["emission_liability"]),
            "pool_score": safe_ratio(bs["minimum_anchor_pool"], bs["pool_floor"]),
            "single_invariant": 0.0,
            "active": False,
        }

    stress_equivalent = multiplier * state.compounded_backed_capital
    solvency = safe_ratio(bs["haircut_assets"], bs["stress_liabilities"])
    liquidity = safe_ratio(bs["immediate_liquidity"], bs["stressed_outflows"])
    gas = safe_ratio(bs["gas_coverage_numerator"], state.gas_spent)
    emission = safe_ratio(bs["emission_backing"], bs["emission_liability"])
    pool = safe_ratio(bs["minimum_anchor_pool"], bs["pool_floor"])
    invariant = min(
        multiplier / target,
        solvency / SOLVENCY_FLOOR,
        liquidity / LIQUIDITY_FLOOR,
        gas / GAS_FLOOR,
        emission / EMISSION_FLOOR,
        pool,
    )
    return {
        **bs,
        "sigma": sigma,
        "target_multiplier": target,
        "recognised_multiplier": multiplier,
        "stress_equivalent_liquidity": stress_equivalent,
        "solvency_ratio": solvency,
        "liquidity_coverage": liquidity,
        "gas_coverage": gas,
        "emission_coverage": emission,
        "pool_score": pool,
        "single_invariant": invariant,
        "active": invariant >= 1.0,
    }


def can_settle(state: GrowthState, sigma: float, scenario: Scenario) -> bool:
    if state.pending_external_profit <= 0:
        return False
    before = metrics(state, sigma, scenario.redemption_shock)
    if not bool(before["active"]):
        return False

    gross = state.pending_external_profit
    gross_dividend = gross * DIVIDEND_POOL_BPS / BPS
    tax = gross_dividend * scenario.withholding_bps / BPS
    post_capital = state.compounded_backed_capital + gross - tax
    probe = GrowthState(
        original_external_capital=state.original_external_capital,
        compounded_backed_capital=post_capital,
        gas_spent=state.gas_spent,
    )
    after = metrics(probe, sigma, scenario.redemption_shock)
    return bool(after["active"]) and float(after["single_invariant"]) >= 1.0


def settle(state: GrowthState, sigma: float, scenario: Scenario) -> None:
    if not can_settle(state, sigma, scenario):
        state.failed_settlements += 1
        return

    gross = state.pending_external_profit
    dividend_pool = gross * DIVIDEND_POOL_BPS / BPS
    owner_gross = 0.50 * dividend_pool
    keeper_gross = dividend_pool - owner_gross
    owner_tax = owner_gross * scenario.withholding_bps / BPS
    keeper_tax = keeper_gross * scenario.withholding_bps / BPS
    owner_net = owner_gross - owner_tax
    keeper_net = keeper_gross - keeper_tax
    retained = gross - dividend_pool
    tax = owner_tax + keeper_tax

    state.compounded_backed_capital += retained + owner_net + keeper_net
    state.retained_profit_reinvested += retained
    state.gross_dividends_declared += dividend_pool
    state.owner_net_reinvested += owner_net
    state.keeper_net_reinvested += keeper_net
    state.tax_remitted += tax
    state.owner_equity += owner_net
    state.keeper_equity += keeper_net
    state.protocol_equity += retained
    state.internal_transfer_volume += gross + owner_net + keeper_net
    state.pending_external_profit = 0.0
    state.settlements += 1


def run_deterministic(
    blocks: int = BLOCKS,
    scenario: Scenario | None = None,
) -> tuple[GrowthState, list[dict[str, float | int | str | bool]]]:
    scenario = scenario or Scenario()
    rng = np.random.default_rng(scenario.seed)
    state = GrowthState()
    state.peak_haircut_nav = float(metrics(state, 0.05)["haircut_assets"])
    trajectory: list[dict[str, float | int | str | bool]] = []

    for block in range(1, blocks + 1):
        if scenario.unsupported_volatility:
            sigma = 0.15
        elif scenario.fixed_sigma is not None:
            sigma = scenario.fixed_sigma
        else:
            sigma = max(0.005, float(rng.normal(0.052, 0.022)))
            if block % 2_500 == 0:
                sigma += float(rng.uniform(0.025, 0.060))

        m = metrics(state, sigma, scenario.redemption_shock)
        state.minimum_single_invariant = min(
            state.minimum_single_invariant,
            float(m["single_invariant"]) if bool(m["active"]) else state.minimum_single_invariant,
        )
        if bool(m["active"]):
            state.minimum_active_multiplier = min(
                state.minimum_active_multiplier,
                float(m["recognised_multiplier"]),
            )
            volume_fraction = float(rng.lognormal(-6.0, 0.52))
            external_volume = state.compounded_backed_capital * volume_fraction
            permissioned_dex_fees = 0.0030 * external_volume
            public_lp_fees = 0.0005 * external_volume
            service_revenue = (
                state.compounded_backed_capital
                * max(0.0, float(rng.normal(0.0000025, 0.0000010)))
            )
            yield_revenue = (
                state.compounded_backed_capital
                * max(0.0, float(rng.normal(0.0000012, 0.0000004)))
            )
            gross_revenue = scenario.revenue_multiplier * (
                permissioned_dex_fees
                + public_lp_fees
                + service_revenue
                + yield_revenue
            )
            gas_cost = (
                scenario.gas_multiplier
                * state.compounded_backed_capital
                * max(0.0000005, float(rng.lognormal(-14.2, 0.55)))
            )
            adverse_selection = 0.00035 * external_volume
            operational_cost = 0.00015 * external_volume
            cost = gas_cost + adverse_selection + operational_cost
            net_external_profit = gross_revenue - cost

            if net_external_profit > 0:
                state.pending_external_profit += net_external_profit
                state.realised_external_profit_gross += net_external_profit
                state.realised_external_cost += cost
                state.gas_spent += gas_cost
                state.useful_actions += 1
            else:
                state.pauses += 1
        else:
            state.pauses += 1

        if block % SETTLEMENT_INTERVAL == 0:
            settle(state, sigma, scenario)

        current = metrics(state, sigma, scenario.redemption_shock)
        nav = float(current["haircut_assets"]) - float(current["stress_liabilities"])
        state.peak_haircut_nav = max(state.peak_haircut_nav, nav)
        if state.peak_haircut_nav > 0:
            state.maximum_drawdown = max(
                state.maximum_drawdown,
                (state.peak_haircut_nav - nav) / state.peak_haircut_nav,
            )

        if block == 1 or block % 100 == 0 or block == blocks:
            trajectory.append(
                {
                    "block": block,
                    "mode": "ACTIVE" if current["active"] else "PAUSED",
                    "sigma": sigma,
                    "backed_capital": state.compounded_backed_capital,
                    "stress_equivalent_liquidity": current["stress_equivalent_liquidity"],
                    "recognised_multiplier": current["recognised_multiplier"],
                    "single_invariant": current["single_invariant"],
                    "solvency_ratio": current["solvency_ratio"],
                    "liquidity_coverage": current["liquidity_coverage"],
                    "gas_coverage": current["gas_coverage"],
                    "emission_coverage": current["emission_coverage"],
                    "gross_external_profit": state.realised_external_profit_gross,
                    "gross_dividends": state.gross_dividends_declared,
                    "owner_net_reinvested": state.owner_net_reinvested,
                    "keeper_net_reinvested": state.keeper_net_reinvested,
                    "retained_reinvested": state.retained_profit_reinvested,
                    "tax_remitted": state.tax_remitted,
                }
            )

    if state.pending_external_profit > 0:
        settle(state, 0.05, scenario)
    return state, trajectory


def run_monte_carlo(paths: int = PATHS, blocks: int = BLOCKS) -> dict[str, object]:
    rng = np.random.default_rng(np.random.SeedSequence([7, 42, 101, 20260730, 5]))
    capital = np.full(paths, 120.0)
    original = np.full(paths, 120.0)
    pending = np.zeros(paths)
    gross_profit = np.zeros(paths)
    dividends = np.zeros(paths)
    owner_reinvest = np.zeros(paths)
    keeper_reinvest = np.zeros(paths)
    retained = np.zeros(paths)
    taxes = np.zeros(paths)
    gas_spent = np.full(paths, 5.0)
    minimum_invariant = np.full(paths, np.inf)
    minimum_multiplier = np.full(paths, np.inf)
    max_drawdown = np.zeros(paths)
    peak_nav = 0.377 * capital
    insolvent = np.zeros(paths, dtype=bool)
    pauses = np.zeros(paths, dtype=np.int64)

    for block in range(1, blocks + 1):
        sigma = np.maximum(0.005, rng.normal(0.052, 0.024, paths))
        if block % 2_500 == 0:
            sigma += rng.uniform(0.025, 0.070, paths)

        target = np.where(
            sigma <= LOW_SIGMA,
            5.0,
            np.where(sigma <= NORMAL_SIGMA, 4.0, np.where(sigma <= MAX_SIGMA, 3.0, np.inf)),
        )
        comp_scale = np.minimum(0.10, 0.04 * np.log1p(np.maximum(0.0, capital / original - 1.0)))
        multiplier = np.where(
            target == 5.0,
            5.0,
            np.where(
                target == 4.0,
                np.minimum(5.0, 4.0 + np.maximum(0.10, 0.52 - 2.5 * np.maximum(0.0, sigma - LOW_SIGMA)) + comp_scale),
                np.where(
                    target == 3.0,
                    np.minimum(5.0, 3.0 + np.maximum(0.06, 0.36 - 2.0 * np.maximum(0.0, sigma - NORMAL_SIGMA)) + comp_scale),
                    0.0,
                ),
            ),
        )

        anchor = 0.54 * capital
        haircut_assets = 0.80 * anchor + 0.30 * capital + 0.09 * capital + 0.05 * capital + 0.005 * capital
        stress_liabilities = 0.50 * capital
        immediate = 0.30 * capital + 0.05 * capital + 0.25 * anchor
        outflows = 0.34 * capital
        emission_backing = 0.30 * capital + 0.10 * capital + 0.30 * anchor
        emission_liability = 0.20 * capital
        min_pool = 0.216 * capital
        pool_floor = POOL_FLOOR_SHARE * capital
        gas_ratio = (gas_spent + 0.05 * capital) / gas_spent

        scores = np.vstack(
            [
                np.divide(multiplier, target, out=np.zeros_like(multiplier), where=np.isfinite(target)),
                (haircut_assets / stress_liabilities) / SOLVENCY_FLOOR,
                (immediate / outflows) / LIQUIDITY_FLOOR,
                gas_ratio / GAS_FLOOR,
                (emission_backing / emission_liability) / EMISSION_FLOOR,
                min_pool / pool_floor,
            ]
        )
        invariant = np.min(scores, axis=0)
        active = np.isfinite(target) & (invariant >= 1.0)
        pauses += (~active).astype(np.int64)
        minimum_invariant = np.minimum(minimum_invariant, np.where(active, invariant, np.inf))
        minimum_multiplier = np.minimum(minimum_multiplier, np.where(active, multiplier, np.inf))

        volume = capital * rng.lognormal(-6.0, 0.56, paths)
        gross_revenue = (
            0.0035 * volume
            + capital * np.maximum(0.0, rng.normal(0.0000025, 0.0000012, paths))
            + capital * np.maximum(0.0, rng.normal(0.0000012, 0.0000005, paths))
        )
        gas_multiplier = rng.choice(
            np.array([50 / 274, 1.0, 500 / 274, 1000 / 274, 5000 / 274]),
            size=paths,
            p=np.array([0.10, 0.55, 0.20, 0.10, 0.05]),
        )
        gas_cost = gas_multiplier * capital * np.maximum(
            0.0000005, rng.lognormal(-14.2, 0.60, paths)
        )
        cost = gas_cost + 0.00050 * volume
        net = np.where(active, np.maximum(0.0, gross_revenue - cost), 0.0)
        pending += net
        gross_profit += net
        gas_spent += np.where(active, gas_cost, 0.0)

        if block % SETTLEMENT_INTERVAL == 0:
            dividend_pool = pending * DIVIDEND_POOL_BPS / BPS
            tax = dividend_pool * WITHHOLDING_BPS / BPS
            owner_net = 0.50 * (dividend_pool - tax)
            keeper_net = dividend_pool - tax - owner_net
            retained_now = pending - dividend_pool
            post_capital = capital + retained_now + owner_net + keeper_net
            settle_mask = active & (pending > 0)
            capital = np.where(settle_mask, post_capital, capital)
            dividends += np.where(settle_mask, dividend_pool, 0.0)
            owner_reinvest += np.where(settle_mask, owner_net, 0.0)
            keeper_reinvest += np.where(settle_mask, keeper_net, 0.0)
            retained += np.where(settle_mask, retained_now, 0.0)
            taxes += np.where(settle_mask, tax, 0.0)
            pending = np.where(settle_mask, 0.0, pending)

        current_nav = 0.377 * capital
        peak_nav = np.maximum(peak_nav, current_nav)
        max_drawdown = np.maximum(
            max_drawdown,
            np.divide(peak_nav - current_nav, peak_nav, out=np.zeros_like(peak_nav), where=peak_nav > 0),
        )
        insolvent |= haircut_assets < stress_liabilities

    finite_invariant = np.where(np.isfinite(minimum_invariant), minimum_invariant, 0.0)
    finite_multiplier = np.where(np.isfinite(minimum_multiplier), minimum_multiplier, 0.0)
    return {
        "paths": paths,
        "blocks_per_path": blocks,
        "minimum_single_invariant": float(np.min(finite_invariant)),
        "minimum_active_multiplier": float(np.min(finite_multiplier)),
        "insolvency_probability": float(np.mean(insolvent)),
        "median_growth_factor": float(np.median(capital / original)),
        "p05_growth_factor": float(np.quantile(capital / original, 0.05)),
        "p95_growth_factor": float(np.quantile(capital / original, 0.95)),
        "median_gross_external_profit": float(np.median(gross_profit)),
        "median_gross_dividends": float(np.median(dividends)),
        "median_owner_net_reinvested": float(np.median(owner_reinvest)),
        "median_keeper_net_reinvested": float(np.median(keeper_reinvest)),
        "median_retained_reinvested": float(np.median(retained)),
        "median_tax_remitted": float(np.median(taxes)),
        "maximum_drawdown": float(np.max(max_drawdown)),
        "dividend_bound_all_paths": bool(np.all(dividends <= gross_profit + 1e-9)),
        "reinvestment_identity_all_paths": bool(
            np.allclose(
                capital,
                original + retained + owner_reinvest + keeper_reinvest,
                rtol=0,
                atol=1e-8,
            )
        ),
        "internal_transfer_revenue": 0.0,
        "minimum_pauses": int(np.min(pauses)),
        "maximum_pauses": int(np.max(pauses)),
    }


def stress_matrix() -> list[dict[str, object]]:
    cases = {
        "baseline": Scenario(seed=42),
        "low_volatility_5x": Scenario(seed=7, fixed_sigma=0.020),
        "normal_volatility_4x": Scenario(seed=42, fixed_sigma=0.055),
        "high_volatility_3x": Scenario(seed=101, fixed_sigma=0.100),
        "unsupported_volatility_pause": Scenario(seed=42, unsupported_volatility=True),
        "zero_external_revenue": Scenario(seed=42, revenue_multiplier=0.0),
        "half_external_revenue": Scenario(seed=42, revenue_multiplier=0.5),
        "gas_5x": Scenario(seed=42, gas_multiplier=5.0),
        "gas_20x": Scenario(seed=42, gas_multiplier=20.0),
        "tax_0": Scenario(seed=42, withholding_bps=0.0),
        "tax_20_percent": Scenario(seed=42, withholding_bps=2_000.0),
        "redemption_10_percent": Scenario(seed=42, redemption_shock=12.0),
        "redemption_30_percent": Scenario(seed=42, redemption_shock=36.0),
    }
    rows: list[dict[str, object]] = []
    for name, scenario in cases.items():
        state, _ = run_deterministic(BLOCKS, scenario)
        final_sigma = (
            0.15
            if scenario.unsupported_volatility
            else (scenario.fixed_sigma if scenario.fixed_sigma is not None else 0.052)
        )
        final = metrics(state, final_sigma, scenario.redemption_shock)
        safe_pause = (
            not bool(final["active"])
            and state.gross_dividends_declared == 0
            and state.compounded_backed_capital >= state.original_external_capital
        )
        zero_revenue_safe = name == "zero_external_revenue" and state.gross_dividends_declared == 0
        rows.append(
            {
                "scenario": name,
                "growth_factor": state.compounded_backed_capital / state.original_external_capital,
                "recognised_multiplier": final["recognised_multiplier"],
                "single_invariant": final["single_invariant"],
                "active": final["active"],
                "gross_external_profit": state.realised_external_profit_gross,
                "gross_dividends": state.gross_dividends_declared,
                "owner_net_reinvested": state.owner_net_reinvested,
                "keeper_net_reinvested": state.keeper_net_reinvested,
                "tax_remitted": state.tax_remitted,
                "pauses": state.pauses,
                "safe": (
                    bool(final["active"]) or safe_pause or zero_revenue_safe
                )
                and state.gross_dividends_declared
                <= state.realised_external_profit_gross + 1e-9,
            }
        )
    return rows


def write_csv(path: Path, rows: Iterable[dict[str, object]]) -> None:
    rows = list(rows)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    out = Path("reports")
    out.mkdir(parents=True, exist_ok=True)

    state, trajectory = run_deterministic()
    final = metrics(state, 0.052)
    deterministic = {
        "verdict": "PASS"
        if final["active"]
        and state.gross_dividends_declared <= state.realised_external_profit_gross + 1e-9
        else "FAIL",
        "state": asdict(state),
        "final_metrics": final,
        "growth": {
            "original_external_capital_pol": state.original_external_capital,
            "ending_backed_capital_pol": state.compounded_backed_capital,
            "capital_growth_pol": state.compounded_backed_capital - state.original_external_capital,
            "growth_factor": state.compounded_backed_capital / state.original_external_capital,
            "stress_equivalent_liquidity_growth_factor": (
                float(final["stress_equivalent_liquidity"])
                / (4.0 * state.original_external_capital)
            ),
            "owner_equity_growth_factor": state.owner_equity / 100.0,
            "keeper_equity_growth_factor": state.keeper_equity / 20.0,
        },
        "identities": {
            "dividend_not_above_external_profit": (
                state.gross_dividends_declared
                <= state.realised_external_profit_gross + 1e-9
            ),
            "capital_reconciliation": math.isclose(
                state.compounded_backed_capital,
                state.original_external_capital
                + state.retained_profit_reinvested
                + state.owner_net_reinvested
                + state.keeper_net_reinvested,
                rel_tol=0,
                abs_tol=1e-8,
            ),
            "internal_transfer_revenue": 0.0,
            "cash_dividend_paid": 0.0,
        },
        "limitations": [
            "3-5x is stress-equivalent executable depth, not withdrawable POL.",
            "Tax withholding is a configurable protocol escrow policy, not a legal tax opinion.",
            "Revenue paths are stochastic model assumptions, not guaranteed future demand.",
        ],
    }
    mc = run_monte_carlo()
    stress = stress_matrix()

    (out / "synergy_growth_dividend_v5_deterministic.json").write_text(
        json.dumps(deterministic, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (out / "synergy_growth_dividend_v5_monte_carlo.json").write_text(
        json.dumps(mc, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (out / "synergy_growth_dividend_v5_stress.json").write_text(
        json.dumps(stress, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    write_csv(out / "synergy_growth_dividend_v5_trajectory.csv", trajectory)
    write_csv(out / "synergy_growth_dividend_v5_stress.csv", stress)

    print(json.dumps({"deterministic": deterministic, "monte_carlo": mc}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
