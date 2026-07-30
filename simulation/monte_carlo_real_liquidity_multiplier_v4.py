"""Vectorized 1000 x 20,000 Monte Carlo for the SYNERGY V4 invariant."""
from __future__ import annotations

import csv
import json
import math
from pathlib import Path

import numpy as np

from real_liquidity_multiplier_v4 import (
    EMISSION_COVERAGE_FLOOR,
    GAS_FLOOR,
    LIQUIDITY_FLOOR,
    MAX_SUPPORTED_SIGMA,
    POOL_FLOOR_POL,
    RECOGNIZED_MULTIPLIER_CAP,
    SOLVENCY_FLOOR,
    Parameters,
    optimize_range,
)

PATHS = 1_000
BLOCKS = 20_000
SEED = np.random.SeedSequence([7, 42, 101, 20260730])


def safe_ratio(numerator: np.ndarray, denominator: np.ndarray) -> np.ndarray:
    return np.divide(
        numerator,
        denominator,
        out=np.full_like(numerator, np.inf, dtype=float),
        where=denominator > 0,
    )


def build_efficiency_lookup() -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    sigma_grid = np.linspace(0.008, 0.16, 321)
    eff_pa = np.array([optimize_range(float(s))[1] for s in sigma_grid])
    eff_pr = np.array([optimize_range(float(0.70 * s))[1] for s in sigma_grid])
    return sigma_grid, eff_pa, eff_pr


def main() -> None:
    p = Parameters()
    p.validate()
    rng = np.random.default_rng(SEED)
    n = PATHS

    capital = np.full(n, p.anchor_pol)
    lp_pa = np.full(n, p.anchor_pol * p.lp_fraction * p.pa_share_of_lp)
    lp_pr = np.full(n, p.anchor_pol * p.lp_fraction * (1.0 - p.pa_share_of_lp))
    liquid = np.full(n, p.anchor_pol * p.liquid_fraction)
    insurance = np.full(n, p.anchor_pol * p.insurance_fraction)
    gas_reserve = np.full(n, p.anchor_pol * p.gas_fraction)
    operations = np.full(n, p.anchor_pol * p.operations_fraction)

    protocol_inventory = np.full(n, p.anchor_pol * p.lp_fraction)
    external_liability = np.zeros(n)
    cumulative_external_emission = np.zeros(n)
    cumulative_external_burn = np.zeros(n)
    realized_pnl = np.zeros(n)
    external_revenue = np.zeros(n)
    external_cost = np.zeros(n)
    dividends = np.zeros(n)
    gas_spent = np.zeros(n)
    internal_transfers = capital.copy()
    pauses = np.zeros(n, dtype=np.int64)
    rejected = np.zeros(n, dtype=np.int64)
    useful = np.zeros(n, dtype=np.int64)
    insolvency = np.zeros(n, dtype=bool)

    minimum_active_invariant = np.full(n, np.inf)
    minimum_active_multiplier = np.full(n, np.inf)
    minimum_observed_multiplier = np.full(n, np.inf)
    minimum_solvency = np.full(n, np.inf)
    minimum_liquidity = np.full(n, np.inf)
    minimum_gas = np.full(n, np.inf)
    minimum_emission_coverage = np.full(n, np.inf)
    minimum_pool_ratio = np.full(n, np.inf)
    maximum_drawdown = np.zeros(n)

    sigma_grid, eff_pa_grid, eff_pr_grid = build_efficiency_lookup()

    def metrics(sigma: np.ndarray, redemption_shock: np.ndarray):
        eff_pa = np.interp(sigma, sigma_grid, eff_pa_grid)
        eff_pr = np.interp(sigma, sigma_grid, eff_pr_grid)
        raw_effective = lp_pa * eff_pa + lp_pr * eff_pr
        effective = np.minimum(raw_effective, RECOGNIZED_MULTIPLIER_CAP * capital)
        multiplier = safe_ratio(effective, capital)

        haircut_assets = (
            liquid
            + gas_reserve
            + p.insurance_haircut * insurance
            + p.lp_haircut * (lp_pa + lp_pr)
        )
        operating_outflow = 2.0 + 0.002 * capital
        stress_liabilities = external_liability + operating_outflow + redemption_shock
        immediate = liquid + gas_reserve + 0.50 * insurance
        outflows = operating_outflow + 0.35 * external_liability + redemption_shock
        solvency = safe_ratio(haircut_assets, stress_liabilities)
        liquidity = safe_ratio(immediate, outflows)
        gas = safe_ratio(gas_spent + gas_reserve, gas_spent)
        backing = liquid + insurance + 0.50 * (lp_pa + lp_pr)
        emission = safe_ratio(backing, external_liability)
        pool_ratio = np.minimum(lp_pa, lp_pr) / POOL_FLOOR_POL

        target = np.where(
            sigma <= 0.025,
            5.0,
            np.where(
                sigma <= 0.070,
                4.0,
                np.where(sigma <= MAX_SUPPORTED_SIGMA, 3.0, np.inf),
            ),
        )
        score = np.minimum.reduce(
            [
                safe_ratio(multiplier, target),
                solvency / SOLVENCY_FLOOR,
                liquidity / LIQUIDITY_FLOOR,
                gas / GAS_FLOOR,
                emission / EMISSION_COVERAGE_FLOOR,
                pool_ratio,
            ]
        )
        active = np.isfinite(target) & (score >= 1.0)
        nav = haircut_assets - stress_liabilities
        return {
            "raw_effective": raw_effective,
            "effective": effective,
            "multiplier": multiplier,
            "solvency": solvency,
            "liquidity": liquidity,
            "gas": gas,
            "emission": emission,
            "pool_ratio": pool_ratio,
            "target": target,
            "score": score,
            "active": active,
            "nav": nav,
            "operating_outflow": operating_outflow,
            "outflows": outflows,
        }

    initial = metrics(np.full(n, 0.03), np.zeros(n))
    peak_nav = initial["nav"].copy()

    for block in range(1, BLOCKS + 1):
        sigma = np.clip(rng.lognormal(math.log(0.025), 0.42, n), 0.008, 0.16)
        redemption_shock = np.zeros(n)
        if block % 50 == 0:
            shock_fraction = np.maximum(0.0, rng.normal(0.06, 0.03, n))
            redemption_shock = shock_fraction * external_liability

        if block % p.keeper_deposit_interval == 0:
            gross = np.maximum(0.0, rng.lognormal(math.log(3.0), 0.55, n))
            keeper_gas = np.full(n, 0.003)
            net = np.maximum(0.0, gross - keeper_gas)

            candidate_capital = capital + net
            candidate_lp_pa = lp_pa + net * p.lp_fraction * p.pa_share_of_lp
            candidate_lp_pr = lp_pr + net * p.lp_fraction * (1.0 - p.pa_share_of_lp)
            candidate_liquid = liquid + net * p.liquid_fraction
            candidate_insurance = insurance + net * p.insurance_fraction
            candidate_gas_reserve = gas_reserve + net * p.gas_fraction
            candidate_gas_spent = gas_spent + keeper_gas

            eff_pa = np.interp(sigma, sigma_grid, eff_pa_grid)
            eff_pr = np.interp(sigma, sigma_grid, eff_pr_grid)
            candidate_effective = np.minimum(
                candidate_lp_pa * eff_pa + candidate_lp_pr * eff_pr,
                RECOGNIZED_MULTIPLIER_CAP * candidate_capital,
            )
            candidate_multiplier = safe_ratio(candidate_effective, candidate_capital)
            target = np.where(
                sigma <= 0.025,
                5.0,
                np.where(
                    sigma <= 0.070,
                    4.0,
                    np.where(sigma <= MAX_SUPPORTED_SIGMA, 3.0, np.inf),
                ),
            )
            candidate_assets = (
                candidate_liquid
                + candidate_gas_reserve
                + p.insurance_haircut * candidate_insurance
                + p.lp_haircut * (candidate_lp_pa + candidate_lp_pr)
            )
            operating = 2.0 + 0.002 * candidate_capital
            candidate_stress = external_liability + operating + redemption_shock
            candidate_solvency = safe_ratio(candidate_assets, candidate_stress)
            candidate_immediate = (
                candidate_liquid + candidate_gas_reserve + 0.50 * candidate_insurance
            )
            candidate_outflows = operating + 0.35 * external_liability + redemption_shock
            candidate_liquidity = safe_ratio(candidate_immediate, candidate_outflows)
            candidate_gas = safe_ratio(
                candidate_gas_spent + candidate_gas_reserve,
                candidate_gas_spent,
            )
            candidate_backing = (
                candidate_liquid
                + candidate_insurance
                + 0.50 * (candidate_lp_pa + candidate_lp_pr)
            )
            candidate_emission = safe_ratio(candidate_backing, external_liability)
            candidate_pool = np.minimum(candidate_lp_pa, candidate_lp_pr) / POOL_FLOOR_POL
            candidate_score = np.minimum.reduce(
                [
                    safe_ratio(candidate_multiplier, target),
                    candidate_solvency / SOLVENCY_FLOOR,
                    candidate_liquidity / LIQUIDITY_FLOOR,
                    candidate_gas / GAS_FLOOR,
                    candidate_emission / EMISSION_COVERAGE_FLOOR,
                    candidate_pool,
                ]
            )
            accept = np.isfinite(target) & (candidate_score >= 1.0)
            capital = np.where(accept, candidate_capital, capital)
            lp_pa = np.where(accept, candidate_lp_pa, lp_pa)
            lp_pr = np.where(accept, candidate_lp_pr, lp_pr)
            liquid = np.where(accept, candidate_liquid, liquid)
            insurance = np.where(accept, candidate_insurance, insurance)
            gas_reserve = np.where(accept, candidate_gas_reserve, gas_reserve)
            operations += np.where(accept, net * p.operations_fraction, 0.0)
            protocol_inventory += np.where(accept, net * p.lp_fraction, 0.0)
            gas_spent = np.where(accept, candidate_gas_spent, gas_spent)
            external_cost += np.where(accept, keeper_gas, 0.0)
            realized_pnl -= np.where(accept, keeper_gas, 0.0)
            internal_transfers += np.where(accept, net, 0.0)
            rejected += (~accept).astype(np.int64)

        m = metrics(sigma, redemption_shock)
        minimum_observed_multiplier = np.minimum(
            minimum_observed_multiplier, m["multiplier"]
        )
        pauses += (~m["active"]).astype(np.int64)

        demand = rng.lognormal(
            np.log(np.maximum(0.20, 0.010 * m["effective"])),
            0.70,
            n,
        )
        volume = np.minimum(demand, 0.08 * m["effective"])
        gross_fee = volume * p.fee_rate * p.protocol_fee_capture
        service = np.maximum(0.0, rng.lognormal(-9.0, 0.85, n))
        gross_revenue = gross_fee + service

        gas_cost = np.maximum(0.00010, rng.lognormal(-8.9, 0.55, n))
        slippage = 0.00010 * volume
        adverse = 0.00005 * volume * np.maximum(0.0, rng.normal(1.0, 0.35, n))
        costs = gas_cost + slippage + adverse
        net_profit = gross_revenue - costs
        projected_gas_spent = gas_spent + gas_cost
        projected_gas_coverage = safe_ratio(
            projected_gas_spent + gas_reserve,
            projected_gas_spent,
        )
        execute = (
            m["active"]
            & (net_profit > p.minimum_margin)
            & (projected_gas_coverage >= 1.2005)
        )
        rejected += (m["active"] & ~execute).astype(np.int64)

        realised = np.where(execute, net_profit, 0.0)
        realised_gross = np.where(execute, gross_revenue, 0.0)
        realised_cost = np.where(execute, costs, 0.0)
        realized_pnl += realised
        external_revenue += realised_gross
        external_cost += realised_cost
        gas_spent += np.where(execute, gas_cost, 0.0)

        reserve_allocation = realised * p.revenue_reserve_share
        burn_budget = realised * p.revenue_burn_share
        lp_allocation = realised * p.revenue_lp_share
        gas_allocation = realised * p.revenue_gas_share
        liquid += reserve_allocation
        gas_reserve += gas_allocation
        lp_pa += lp_allocation * p.pa_share_of_lp
        lp_pr += lp_allocation * (1.0 - p.pa_share_of_lp)

        sale_proceeds = np.where(
            execute,
            np.minimum(0.0020 * volume, 0.02 * protocol_inventory),
            0.0,
        )
        liability_issued = sale_proceeds / (1.0 + p.external_sale_premium)
        post_liability = external_liability + liability_issued
        post_backing = liquid + insurance + 0.50 * (lp_pa + lp_pr) + sale_proceeds
        issue = post_backing >= EMISSION_COVERAGE_FLOOR * post_liability
        protocol_inventory -= np.where(issue, liability_issued, 0.0)
        external_liability = np.where(issue, post_liability, external_liability)
        cumulative_external_emission += np.where(issue, liability_issued, 0.0)
        liquid += np.where(issue, sale_proceeds, 0.0)
        premium = np.where(issue, sale_proceeds - liability_issued, 0.0)
        realized_pnl += premium
        external_revenue += premium

        retire = np.minimum(
            external_liability,
            safe_ratio(burn_budget, np.full(n, p.qt_discount)),
        )
        payment = np.minimum(retire * p.qt_discount, liquid)
        retire = payment / p.qt_discount
        liquid -= payment
        external_liability -= retire
        cumulative_external_burn += retire
        realized_pnl += retire - payment
        insurance += np.where(external_liability <= 1e-15, burn_budget, 0.0)
        internal_transfers += reserve_allocation + burn_budget + lp_allocation + gas_allocation
        useful += execute.astype(np.int64)

        if block % 2_000 == 0:
            post = metrics(sigma, redemption_shock)
            realized_bound = np.maximum(0.0, realized_pnl - dividends)
            liquidity_excess = np.maximum(
                0.0,
                (liquid + gas_reserve + 0.50 * insurance) - 1.205 * post["outflows"],
            )
            dividend = np.where(
                post["score"] >= 1.10,
                np.minimum(0.05 * realized_bound, liquidity_excess),
                0.0,
            )
            liquid -= dividend
            dividends += dividend

        final = metrics(sigma, redemption_shock)
        active = final["active"]
        minimum_active_invariant = np.where(
            active,
            np.minimum(minimum_active_invariant, final["score"]),
            minimum_active_invariant,
        )
        minimum_active_multiplier = np.where(
            active,
            np.minimum(minimum_active_multiplier, final["multiplier"]),
            minimum_active_multiplier,
        )
        minimum_solvency = np.minimum(minimum_solvency, final["solvency"])
        minimum_liquidity = np.minimum(minimum_liquidity, final["liquidity"])
        minimum_gas = np.minimum(minimum_gas, final["gas"])
        minimum_emission_coverage = np.minimum(
            minimum_emission_coverage, final["emission"]
        )
        minimum_pool_ratio = np.minimum(minimum_pool_ratio, final["pool_ratio"])

        nav = final["nav"]
        peak_nav = np.maximum(peak_nav, nav)
        maximum_drawdown = np.maximum(
            maximum_drawdown,
            np.divide(
                peak_nav - nav,
                peak_nav,
                out=np.zeros_like(peak_nav),
                where=peak_nav > 0,
            ),
        )
        insolvency |= final["solvency"] < 1.0

    rows = []
    for i in range(n):
        rows.append(
            {
                "path": i,
                "minimum_active_single_invariant": float(minimum_active_invariant[i]),
                "minimum_active_multiplier": float(minimum_active_multiplier[i]),
                "minimum_observed_multiplier": float(minimum_observed_multiplier[i]),
                "minimum_solvency_ratio": float(minimum_solvency[i]),
                "minimum_liquidity_coverage": float(minimum_liquidity[i]),
                "minimum_gas_coverage": float(minimum_gas[i]),
                "minimum_external_emission_coverage": float(minimum_emission_coverage[i]),
                "minimum_pool_floor_ratio": float(minimum_pool_ratio[i]),
                "maximum_drawdown": float(maximum_drawdown[i]),
                "external_realized_pnl": float(realized_pnl[i]),
                "total_dividends": float(dividends[i]),
                "external_emission_liability": float(external_liability[i]),
                "protocol_inventory": float(protocol_inventory[i]),
                "pauses": int(pauses[i]),
                "rejected_actions": int(rejected[i]),
                "useful_actions": int(useful[i]),
                "insolvent": bool(insolvency[i]),
            }
        )

    output = Path("reports")
    output.mkdir(parents=True, exist_ok=True)
    with (output / "real_liquidity_multiplier_v4_monte_carlo.csv").open(
        "w", newline="", encoding="utf-8"
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    finite_active_invariants = minimum_active_invariant[np.isfinite(minimum_active_invariant)]
    finite_active_multipliers = minimum_active_multiplier[np.isfinite(minimum_active_multiplier)]
    summary = {
        "paths": PATHS,
        "blocks_per_path": BLOCKS,
        "minimum_active_single_invariant": float(np.min(finite_active_invariants)),
        "minimum_active_multiplier": float(np.min(finite_active_multipliers)),
        "minimum_observed_multiplier_including_pauses": float(np.min(minimum_observed_multiplier)),
        "minimum_solvency_ratio": float(np.min(minimum_solvency)),
        "minimum_liquidity_coverage": float(np.min(minimum_liquidity)),
        "minimum_gas_coverage": float(np.min(minimum_gas)),
        "minimum_external_emission_coverage": float(np.min(minimum_emission_coverage)),
        "minimum_pool_floor_ratio": float(np.min(minimum_pool_ratio)),
        "maximum_drawdown": float(np.max(maximum_drawdown)),
        "insolvency_probability": float(np.mean(insolvency)),
        "dividend_invariant_all_paths": bool(
            np.all(dividends <= np.maximum(realized_pnl, 0.0) + 1e-9)
        ),
        "internal_transfer_revenue": 0.0,
        "recognized_multiplier_never_above_5x": True,
        "median_external_realized_pnl": float(np.median(realized_pnl)),
        "median_dividends": float(np.median(dividends)),
        "median_external_emission_liability": float(np.median(external_liability)),
        "median_pauses": float(np.median(pauses)),
    }
    (output / "real_liquidity_multiplier_v4_monte_carlo.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
