"""Vectorized 1000-path x 20,000-block consolidated solvency Monte Carlo."""
from __future__ import annotations

import csv
import json
from pathlib import Path

import numpy as np

PATHS = 1000
BLOCKS = 20_000
NORMAL_SOLVENCY = 1.20
DEFENSIVE_SOLVENCY = 1.05
NORMAL_LIQUIDITY = 1.20
LIQUIDITY_ACTION_BUFFER = 1.205
MIN_GAS_COVERAGE = 1.20
GAS_ACTION_BUFFER = 1.2005
MIN_POLICY_RATIO = 0.70
MIN_POOL_DEPTH = 25.0
BASE_STRESSED_OUTFLOWS = 45.0


def safe_ratio(numerator: np.ndarray, denominator: np.ndarray) -> np.ndarray:
    return np.divide(
        numerator,
        denominator,
        out=np.full_like(numerator, np.inf, dtype=float),
        where=denominator > 0,
    )


def main() -> None:
    rng = np.random.default_rng(np.random.SeedSequence([7, 42, 101, 20260730]))
    n = PATHS

    liquid = np.full(n, 100.0)
    stable_lp = np.full(n, 40.0)
    volatile_lp = np.full(n, 20.0)
    bridge = np.full(n, 20.0)
    insurance = np.full(n, 10.0)
    productive_yield = np.full(n, 10.0)
    gas_reserve = np.full(n, 6.0)
    inventory_value = np.zeros(n)

    external_syn_liability = np.full(n, 70.0)
    external_synr_claims = np.full(n, 20.0)
    vested_mev_claims = np.full(n, 5.0)
    fixed_other_liabilities = np.full(n, 5.0)
    redemption_shock = np.zeros(n)

    immediate_liquid = np.full(n, 75.0)
    stressed_outflows = np.full(n, BASE_STRESSED_OUTFLOWS)
    reimbursed_gas = np.full(n, 30.0)
    reserve_policy_capital = np.full(n, 105.0)
    conservative_obligations = np.full(n, 140.0)

    realized_pnl = np.zeros(n)
    external_revenue = np.zeros(n)
    external_cost = np.zeros(n)
    internal_transfers = np.zeros(n)
    dividends = np.zeros(n)
    external_supply = np.full(n, 70.0)
    protocol_inventory = np.full(n, 30.0)
    pool_depth = np.full(n, 60.0)
    pauses = np.zeros(n, dtype=np.int64)
    gas_skips = np.zeros(n, dtype=np.int64)
    useful_actions = np.zeros(n, dtype=np.int64)
    insolvency = np.zeros(n, dtype=bool)

    def assets() -> np.ndarray:
        return (
            liquid
            + gas_reserve
            + 0.85 * stable_lp
            + 0.65 * volatile_lp
            + 0.70 * bridge
            + 0.90 * insurance
            + 0.80 * productive_yield
            + 0.25 * inventory_value
        )

    def liabilities() -> np.ndarray:
        return (
            external_syn_liability
            + external_synr_claims
            + vested_mev_claims
            + fixed_other_liabilities
            + redemption_shock
        )

    initial_nav = assets() - liabilities()
    peak_nav = initial_nav.copy()
    maximum_drawdown = np.zeros(n)
    minimum_solvency = np.full(n, np.inf)
    minimum_liquidity = np.full(n, np.inf)
    minimum_gas = np.full(n, np.inf)
    minimum_pool_depth = pool_depth.copy()

    for block in range(1, BLOCKS + 1):
        user_volume = rng.lognormal(-2.7, 0.70, n)
        mev_fee = rng.lognormal(-5.0, 0.85, n)
        service_revenue = rng.lognormal(-5.2, 0.60, n)
        yield_revenue = np.maximum(0.0, productive_yield * rng.normal(0.000018, 0.000007, n))
        gross = 0.0025 * user_volume + mev_fee + service_revenue + yield_revenue

        gas_multiplier = rng.choice(
            np.array([50 / 274, 1.0, 500 / 274, 1000 / 274, 5000 / 274]),
            size=n,
            p=np.array([0.10, 0.55, 0.20, 0.10, 0.05]),
        )
        gas_cost = gas_multiplier * np.maximum(0.00008, rng.lognormal(-8.7, 0.48, n))
        slippage = 0.0008 * user_volume * (1.0 + np.maximum(0.0, rng.normal(0.0, 0.45, n)))
        adverse = 0.00035 * user_volume * np.maximum(0.0, rng.normal(1.0, 0.40, n))
        costs = gas_cost + slippage + adverse
        net_candidate = gross - costs

        a = assets()
        l = liabilities()
        sr = safe_ratio(a, l)
        lc = safe_ratio(immediate_liquid, stressed_outflows)
        gc = safe_ratio(reimbursed_gas + gas_reserve, reimbursed_gas)
        pr = safe_ratio(reserve_policy_capital, conservative_obligations)
        opportunity = net_candidate > 0.0001

        projected_reimbursed = reimbursed_gas + gas_cost
        projected_gas_reserve = gas_reserve + 0.20 * net_candidate
        projected_gc = safe_ratio(
            projected_reimbursed + projected_gas_reserve,
            projected_reimbursed,
        )
        projected_lc = safe_ratio(
            immediate_liquid + 0.70 * net_candidate,
            stressed_outflows,
        )
        projected_safe = (
            (projected_gc >= GAS_ACTION_BUFFER)
            & (projected_lc >= NORMAL_LIQUIDITY)
        )

        normal = (
            opportunity
            & projected_safe
            & (sr >= NORMAL_SOLVENCY)
            & (lc >= NORMAL_LIQUIDITY)
            & (gc >= MIN_GAS_COVERAGE)
            & (pr >= MIN_POLICY_RATIO)
            & (pool_depth >= MIN_POOL_DEPTH)
        )
        defensive = (
            opportunity
            & projected_safe
            & ~normal
            & (sr >= DEFENSIVE_SOLVENCY)
            & (lc >= DEFENSIVE_SOLVENCY)
            & (gc >= MIN_GAS_COVERAGE)
        )
        execute = normal | defensive
        pauses += (~execute).astype(np.int64)
        gas_skips += (opportunity & ~execute).astype(np.int64)

        net = np.where(execute, net_candidate, 0.0)
        external_revenue += np.where(execute, gross, 0.0)
        external_cost += np.where(execute, costs, 0.0)
        realized_pnl += net
        liquid += net
        immediate_liquid += 0.70 * net
        gas_reserve += 0.20 * net
        insurance += 0.10 * net
        reimbursed_gas += np.where(execute, gas_cost, 0.0)
        useful_actions += execute.astype(np.int64)

        issue = np.where(execute, np.minimum(0.018 * user_volume, protocol_inventory), 0.0)
        redeem_fraction = rng.uniform(0.70, 1.05, n)
        redeem = np.minimum(external_supply + issue, issue * redeem_fraction)
        protocol_inventory -= issue
        external_supply += issue - redeem
        external_syn_liability += issue - redeem
        internal_transfers += np.where(execute, 3.0 * gross, 0.0)
        pool_depth += 0.25 * net

        if block % 50 == 0:
            shock_fraction = np.maximum(0.0, rng.normal(0.08, 0.04, n))
            redemption_shock = shock_fraction * (external_syn_liability + external_synr_claims)
        if block % 200 == 0:
            redemption_shock *= 0.50
        if block % 50 == 0:
            stressed_outflows = np.maximum(BASE_STRESSED_OUTFLOWS, BASE_STRESSED_OUTFLOWS + redemption_shock)

        if block % 500 == 0:
            required = NORMAL_SOLVENCY * liabilities() + 11.0
            excess = np.maximum(0.0, liquid - required)
            liquidity_slack = np.maximum(
                0.0,
                immediate_liquid - LIQUIDITY_ACTION_BUFFER * stressed_outflows,
            )
            qe = np.where(normal, np.minimum(np.minimum(0.10 * excess, 5.0), liquidity_slack), 0.0)
            liquid -= qe
            stable_lp += 0.50 * qe
            bridge += 0.25 * qe
            insurance += 0.25 * qe
            immediate_liquid -= qe
            internal_transfers += qe

        if block % 1000 == 0:
            nav = assets() - liabilities()
            realized_bound = np.maximum(0.0, realized_pnl - dividends)
            nav_bound = np.maximum(0.0, nav - 13.0)
            capacity = np.minimum(realized_bound, nav_bound)
            required = NORMAL_SOLVENCY * liabilities() + 11.0
            cash_bound = np.maximum(0.0, liquid - required)
            liquidity_slack = np.maximum(
                0.0,
                immediate_liquid - LIQUIDITY_ACTION_BUFFER * stressed_outflows,
            )
            dividend = np.where(
                normal,
                np.minimum(np.minimum(0.10 * capacity, cash_bound), liquidity_slack),
                0.0,
            )
            liquid -= dividend
            immediate_liquid -= dividend
            dividends += dividend

        current_assets = assets()
        current_liabilities = liabilities()
        current_nav = current_assets - current_liabilities
        current_sr = safe_ratio(current_assets, current_liabilities)
        current_lc = safe_ratio(immediate_liquid, stressed_outflows)
        current_gc = safe_ratio(reimbursed_gas + gas_reserve, reimbursed_gas)
        minimum_solvency = np.minimum(minimum_solvency, current_sr)
        minimum_liquidity = np.minimum(minimum_liquidity, current_lc)
        minimum_gas = np.minimum(minimum_gas, current_gc)
        minimum_pool_depth = np.minimum(minimum_pool_depth, pool_depth)
        peak_nav = np.maximum(peak_nav, current_nav)
        maximum_drawdown = np.maximum(
            maximum_drawdown,
            np.divide(peak_nav - current_nav, peak_nav, out=np.zeros_like(peak_nav), where=peak_nav > 0),
        )
        insolvency |= current_sr < 1.0

    rows = [
        {
            "path": i,
            "minimum_solvency_ratio": float(minimum_solvency[i]),
            "minimum_liquidity_coverage": float(minimum_liquidity[i]),
            "minimum_gas_coverage": float(minimum_gas[i]),
            "maximum_drawdown": float(maximum_drawdown[i]),
            "external_realized_pnl": float(realized_pnl[i]),
            "internal_transfer_volume": float(internal_transfers[i]),
            "total_dividends": float(dividends[i]),
            "external_liabilities": float(external_syn_liability[i]),
            "protocol_inventory": float(protocol_inventory[i]),
            "minimum_pool_depth": float(minimum_pool_depth[i]),
            "useful_actions": int(useful_actions[i]),
            "gas_skips": int(gas_skips[i]),
            "pauses": int(pauses[i]),
            "insolvent": bool(insolvency[i]),
        }
        for i in range(n)
    ]

    out = Path("reports")
    out.mkdir(parents=True, exist_ok=True)
    with (out / "monte_carlo_summary.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    invariants = {
        "paths": PATHS,
        "blocks_per_path": BLOCKS,
        "minimum_solvency_ratio": float(np.min(minimum_solvency)),
        "minimum_liquidity_coverage": float(np.min(minimum_liquidity)),
        "minimum_gas_coverage": float(np.min(minimum_gas)),
        "maximum_drawdown": float(np.max(maximum_drawdown)),
        "median_external_realized_pnl": float(np.median(realized_pnl)),
        "median_internal_transfer_volume": float(np.median(internal_transfers)),
        "median_dividends": float(np.median(dividends)),
        "minimum_pool_depth": float(np.min(minimum_pool_depth)),
        "insolvency_probability": float(np.mean(insolvency)),
        "dividend_invariant_all_paths": bool(np.all(dividends <= np.maximum(realized_pnl, 0.0) + 1e-9)),
        "no_negative_reserve_all_paths": bool(
            np.all(liquid >= -1e-9)
            and np.all(stable_lp >= -1e-9)
            and np.all(volatile_lp >= -1e-9)
            and np.all(bridge >= -1e-9)
            and np.all(insurance >= -1e-9)
            and np.all(gas_reserve >= -1e-9)
        ),
        "internal_transfer_revenue": 0.0,
    }
    (out / "formal_invariants.json").write_text(
        json.dumps(invariants, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(invariants, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
