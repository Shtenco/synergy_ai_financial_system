"""SYNERGY Real Liquidity Multiplier V4.

This model unifies the previous deflationary, triangular-emission,
non-inflationary-emission and consolidated-solvency models.

The numerator is NOT TVL and NOT token market capitalization. It is the
stress-adjusted V2-equivalent executable liquidity of the POL anchor cut.
The SYNA/SYNR cross-pool improves routing/redundancy but is excluded from the
numerator so the same internal emission cannot be counted twice.

One composite invariant is used:

I_t = min(
    L_eff_stress / (K(sigma) * C_external_net),
    HaircutAssets / (1.20 * StressLiabilities),
    ImmediateLiquidity / (1.20 * StressedOutflows30d),
    (GasSpent + GasReserve) / (1.20 * GasSpent),
    ExternalEmissionBacking / (1.20 * ExternalEmissionLiability),
    MinAnchorPoolPOL / PoolFloorPOL
) >= 1.

K(sigma) is 5x in low volatility, 4x in normal volatility and 3x in
high volatility. Above the supported volatility band the system must PAUSE.
"""
from __future__ import annotations

import csv
import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Tuple

import matplotlib.pyplot as plt
import numpy as np

BPS = 10_000.0
SOLVENCY_FLOOR = 1.20
LIQUIDITY_FLOOR = 1.20
GAS_FLOOR = 1.20
EMISSION_COVERAGE_FLOOR = 1.20
POOL_FLOOR_POL = 10.0
MAX_SUPPORTED_SIGMA = 0.12
RECOGNIZED_MULTIPLIER_CAP = 5.0
EPSILON_PRICE_IMPACT = 0.01
TAIL_Z = 2.576


@dataclass
class Parameters:
    anchor_pol: float = 100.0
    lp_fraction: float = 0.54
    pa_share_of_lp: float = 0.60
    liquid_fraction: float = 0.30
    insurance_fraction: float = 0.10
    gas_fraction: float = 0.05
    operations_fraction: float = 0.01
    fee_rate: float = 0.003
    protocol_fee_capture: float = 0.30
    keeper_deposit_interval: int = 1_000
    external_sale_premium: float = 0.02
    qt_discount: float = 0.95
    revenue_reserve_share: float = 0.50
    revenue_burn_share: float = 0.30
    revenue_lp_share: float = 0.15
    revenue_gas_share: float = 0.05
    lp_haircut: float = 0.75
    insurance_haircut: float = 0.90
    minimum_margin: float = 0.00010

    def validate(self) -> None:
        allocation = (
            self.lp_fraction
            + self.liquid_fraction
            + self.insurance_fraction
            + self.gas_fraction
            + self.operations_fraction
        )
        revenue_split = (
            self.revenue_reserve_share
            + self.revenue_burn_share
            + self.revenue_lp_share
            + self.revenue_gas_share
        )
        if abs(allocation - 1.0) > 1e-12:
            raise ValueError(f"capital allocation must equal 1, got {allocation}")
        if abs(revenue_split - 1.0) > 1e-12:
            raise ValueError(f"revenue allocation must equal 1, got {revenue_split}")
        if not (0 < self.pa_share_of_lp < 1):
            raise ValueError("pa_share_of_lp must be between zero and one")


@dataclass
class State:
    net_external_capital: float = 0.0
    liquid_reserve: float = 0.0
    insurance: float = 0.0
    gas_reserve: float = 0.0
    operations_reserve: float = 0.0
    lp_pol_syna: float = 0.0
    lp_pol_synr: float = 0.0
    cross_pool_internal_notional: float = 0.0
    protocol_inventory: float = 0.0
    external_emission_liability: float = 0.0
    cumulative_internal_emission: float = 0.0
    cumulative_external_emission: float = 0.0
    cumulative_external_burn: float = 0.0
    realized_external_pnl: float = 0.0
    cumulative_external_revenue: float = 0.0
    cumulative_external_cost: float = 0.0
    total_dividends: float = 0.0
    gas_spent: float = 0.0
    internal_transfer_volume: float = 0.0
    rejected_actions: int = 0
    useful_actions: int = 0
    keeper_deposits: int = 0
    pauses: int = 0
    maximum_drawdown: float = 0.0
    peak_nav: float = 0.0
    minimum_active_invariant: float = math.inf
    minimum_active_multiplier: float = math.inf
    minimum_observed_multiplier: float = math.inf


def adaptive_target_multiplier(sigma_latency: float) -> float:
    if sigma_latency <= 0.025:
        return 5.0
    if sigma_latency <= 0.070:
        return 4.0
    if sigma_latency <= MAX_SUPPORTED_SIGMA:
        return 3.0
    return math.inf


def v2_depth_per_unit_capital(epsilon: float = EPSILON_PRICE_IMPACT) -> float:
    up = 0.5 * (math.sqrt(1.0 + epsilon) - 1.0)
    down = 0.5 * (1.0 - math.sqrt(1.0 - epsilon))
    return min(up, down)


def concentrated_equivalent_per_capital(
    range_half_width: float,
    sigma_latency: float,
    *,
    epsilon: float = EPSILON_PRICE_IMPACT,
    tail_z: float = TAIL_Z,
) -> float:
    if not (0 < range_half_width < 0.95):
        return 0.0

    lower = 1.0 - range_half_width
    upper = 1.0 + range_half_width
    sqrt_lower = math.sqrt(lower)
    sqrt_upper = math.sqrt(upper)
    capital_per_liquidity = (1.0 - 1.0 / sqrt_upper) + (1.0 - sqrt_lower)
    liquidity_per_capital = 1.0 / capital_per_liquidity
    baseline = v2_depth_per_unit_capital(epsilon)

    tail_values: List[float] = []
    for log_shock in (-tail_z * sigma_latency, tail_z * sigma_latency):
        price = math.exp(log_shock)
        if not (lower < price < upper):
            tail_values.append(0.0)
            continue
        price_up = min(upper, price * (1.0 + epsilon))
        price_down = max(lower, price * (1.0 - epsilon))
        quote_in_up = liquidity_per_capital * (math.sqrt(price_up) - math.sqrt(price))
        quote_out_down = liquidity_per_capital * (math.sqrt(price) - math.sqrt(price_down))
        executable_quote = min(quote_in_up, quote_out_down)
        tail_values.append(executable_quote / baseline)

    return min(tail_values)


def optimize_range(sigma_latency: float) -> Tuple[float, float]:
    minimum_width = min(0.90, TAIL_Z * sigma_latency + EPSILON_PRICE_IMPACT + 0.005)
    grid = np.linspace(max(0.05, minimum_width), 0.80, 240)
    values = np.array(
        [concentrated_equivalent_per_capital(float(width), sigma_latency) for width in grid]
    )
    index = int(np.argmax(values))
    return float(grid[index]), float(values[index])


def allocate_external_capital(state: State, gross_pol: float, params: Parameters) -> None:
    if gross_pol <= 0:
        return
    state.net_external_capital += gross_pol
    lp_budget = gross_pol * params.lp_fraction
    state.lp_pol_syna += lp_budget * params.pa_share_of_lp
    state.lp_pol_synr += lp_budget * (1.0 - params.pa_share_of_lp)
    state.liquid_reserve += gross_pol * params.liquid_fraction
    state.insurance += gross_pol * params.insurance_fraction
    state.gas_reserve += gross_pol * params.gas_fraction
    state.operations_reserve += gross_pol * params.operations_fraction

    internal_emission = lp_budget
    state.protocol_inventory += internal_emission
    state.cumulative_internal_emission += internal_emission
    state.cross_pool_internal_notional += 0.25 * lp_budget
    state.internal_transfer_volume += gross_pol


def system_metrics(
    state: State,
    params: Parameters,
    *,
    sigma_latency: float,
    redemption_shock: float,
    operating_outflow_30d: float,
) -> Dict[str, float | str | bool]:
    target = adaptive_target_multiplier(sigma_latency)
    range_pa, efficiency_pa = optimize_range(sigma_latency)
    range_pr, efficiency_pr = optimize_range(0.70 * sigma_latency)

    raw_effective_liquidity = (
        state.lp_pol_syna * efficiency_pa + state.lp_pol_synr * efficiency_pr
    )
    effective_liquidity = min(
        raw_effective_liquidity,
        RECOGNIZED_MULTIPLIER_CAP * state.net_external_capital,
    )
    multiplier = (
        effective_liquidity / state.net_external_capital
        if state.net_external_capital > 0
        else 0.0
    )

    haircut_assets = (
        state.liquid_reserve
        + state.gas_reserve
        + params.insurance_haircut * state.insurance
        + params.lp_haircut * (state.lp_pol_syna + state.lp_pol_synr)
    )
    stress_liabilities = (
        state.external_emission_liability + operating_outflow_30d + redemption_shock
    )
    immediate_liquidity = (
        state.liquid_reserve + state.gas_reserve + 0.50 * state.insurance
    )
    stressed_outflows = (
        operating_outflow_30d
        + 0.35 * state.external_emission_liability
        + redemption_shock
    )

    solvency_ratio = (
        haircut_assets / stress_liabilities if stress_liabilities > 0 else math.inf
    )
    liquidity_coverage = (
        immediate_liquidity / stressed_outflows if stressed_outflows > 0 else math.inf
    )
    gas_coverage = (
        (state.gas_spent + state.gas_reserve) / state.gas_spent
        if state.gas_spent > 0
        else math.inf
    )
    external_backing = (
        state.liquid_reserve
        + state.insurance
        + 0.50 * (state.lp_pol_syna + state.lp_pol_synr)
    )
    emission_coverage = (
        external_backing / state.external_emission_liability
        if state.external_emission_liability > 0
        else math.inf
    )
    pool_floor_ratio = min(state.lp_pol_syna, state.lp_pol_synr) / POOL_FLOOR_POL

    if not math.isfinite(target):
        invariant = 0.0
        mode = "PAUSED"
    else:
        component_scores = [
            multiplier / target,
            solvency_ratio / SOLVENCY_FLOOR,
            liquidity_coverage / LIQUIDITY_FLOOR,
            gas_coverage / GAS_FLOOR,
            emission_coverage / EMISSION_COVERAGE_FLOOR,
            pool_floor_ratio,
        ]
        invariant = min(component_scores)
        mode = "ACTIVE" if invariant >= 1.0 else "PAUSED"

    nav = haircut_assets - stress_liabilities
    return {
        "mode": mode,
        "target_multiplier": target,
        "range_pol_syna": range_pa,
        "range_pol_synr": range_pr,
        "raw_stress_equivalent_liquidity_pol": raw_effective_liquidity,
        "stress_equivalent_liquidity_pol": effective_liquidity,
        "real_liquidity_multiplier": multiplier,
        "haircut_assets_pol": haircut_assets,
        "stress_liabilities_pol": stress_liabilities,
        "economic_solvency_ratio": solvency_ratio,
        "immediate_liquidity_pol": immediate_liquidity,
        "stressed_outflows_30d_pol": stressed_outflows,
        "liquidity_coverage": liquidity_coverage,
        "gas_coverage": gas_coverage,
        "external_emission_coverage": emission_coverage,
        "minimum_anchor_pool_floor_ratio": pool_floor_ratio,
        "single_invariant": invariant,
        "consolidated_nav_pol": nav,
        "cross_pool_excluded_from_multiplier": True,
    }


def projected_action_is_safe(
    state: State,
    params: Parameters,
    *,
    sigma_latency: float,
    redemption_shock: float,
    operating_outflow_30d: float,
    gas_cost: float,
) -> bool:
    projected_gas_spent = state.gas_spent + gas_cost
    projected_gas_coverage = (
        (projected_gas_spent + state.gas_reserve) / projected_gas_spent
        if projected_gas_spent > 0
        else math.inf
    )
    if projected_gas_coverage < 1.2005:
        return False
    current = system_metrics(
        state,
        params,
        sigma_latency=sigma_latency,
        redemption_shock=redemption_shock,
        operating_outflow_30d=operating_outflow_30d,
    )
    return current["mode"] == "ACTIVE"


def run_path(
    *,
    blocks: int = 20_000,
    seed: int = 42,
    params: Parameters | None = None,
    allow_investor_deposits: bool = True,
    force_zero_revenue: bool = False,
) -> Tuple[State, List[Dict[str, float | int | str | bool]]]:
    params = params or Parameters()
    params.validate()
    rng = np.random.default_rng(seed)
    state = State()
    allocate_external_capital(state, params.anchor_pol, params)

    initial = system_metrics(
        state,
        params,
        sigma_latency=0.03,
        redemption_shock=0.0,
        operating_outflow_30d=2.0 + 0.002 * state.net_external_capital,
    )
    state.peak_nav = float(initial["consolidated_nav_pol"])
    history: List[Dict[str, float | int | str | bool]] = []

    for block in range(1, blocks + 1):
        sigma_latency = float(
            np.clip(rng.lognormal(math.log(0.025), 0.38), 0.008, 0.16)
        )
        operating_outflow = 2.0 + 0.002 * state.net_external_capital
        redemption_shock = 0.0
        if block % 50 == 0:
            shock_fraction = max(0.0, float(rng.normal(0.06, 0.025)))
            redemption_shock = shock_fraction * state.external_emission_liability

        if allow_investor_deposits and block % params.keeper_deposit_interval == 0:
            gross_deposit = max(0.0, float(rng.lognormal(math.log(3.0), 0.50)))
            keeper_gas = 0.003
            net_deposit = max(0.0, gross_deposit - keeper_gas)
            candidate = State(**asdict(state))
            allocate_external_capital(candidate, net_deposit, params)
            candidate.gas_spent += keeper_gas
            candidate.cumulative_external_cost += keeper_gas
            candidate.realized_external_pnl -= keeper_gas
            post = system_metrics(
                candidate,
                params,
                sigma_latency=sigma_latency,
                redemption_shock=redemption_shock,
                operating_outflow_30d=operating_outflow,
            )
            if post["single_invariant"] >= 1.0:
                state = candidate
                state.keeper_deposits += 1
            else:
                state.rejected_actions += 1

        metrics = system_metrics(
            state,
            params,
            sigma_latency=sigma_latency,
            redemption_shock=redemption_shock,
            operating_outflow_30d=operating_outflow,
        )
        state.minimum_observed_multiplier = min(
            state.minimum_observed_multiplier,
            float(metrics["real_liquidity_multiplier"]),
        )

        if metrics["mode"] != "ACTIVE":
            state.pauses += 1
        else:
            capacity = float(metrics["stress_equivalent_liquidity_pol"])
            demand = float(
                rng.lognormal(math.log(max(0.20, 0.010 * capacity)), 0.65)
            )
            external_volume = min(demand, 0.08 * capacity)

            gross_fee = (
                external_volume * params.fee_rate * params.protocol_fee_capture
            )
            service_revenue = (
                0.0
                if force_zero_revenue
                else max(0.0, float(rng.lognormal(-9.0, 0.80)))
            )
            gross_external_revenue = (
                0.0 if force_zero_revenue else gross_fee + service_revenue
            )

            gas_cost = max(0.00010, float(rng.lognormal(-8.9, 0.50)))
            slippage = 0.00010 * external_volume
            adverse_selection = (
                0.00005
                * external_volume
                * max(0.0, float(rng.normal(1.0, 0.30)))
            )
            external_cost = gas_cost + slippage + adverse_selection
            net_external_profit = gross_external_revenue - external_cost

            if (
                net_external_profit <= params.minimum_margin
                or not projected_action_is_safe(
                    state,
                    params,
                    sigma_latency=sigma_latency,
                    redemption_shock=redemption_shock,
                    operating_outflow_30d=operating_outflow,
                    gas_cost=gas_cost,
                )
            ):
                state.rejected_actions += 1
            else:
                state.cumulative_external_revenue += gross_external_revenue
                state.cumulative_external_cost += external_cost
                state.realized_external_pnl += net_external_profit
                state.gas_spent += gas_cost

                reserve_allocation = (
                    net_external_profit * params.revenue_reserve_share
                )
                burn_budget = net_external_profit * params.revenue_burn_share
                lp_allocation = net_external_profit * params.revenue_lp_share
                gas_allocation = net_external_profit * params.revenue_gas_share

                state.liquid_reserve += reserve_allocation
                state.gas_reserve += gas_allocation
                state.lp_pol_syna += (
                    lp_allocation * params.pa_share_of_lp
                )
                state.lp_pol_synr += (
                    lp_allocation * (1.0 - params.pa_share_of_lp)
                )

                sale_proceeds = min(
                    0.0020 * external_volume,
                    0.02 * state.protocol_inventory,
                )
                if sale_proceeds > 0:
                    liability_issued = sale_proceeds / (
                        1.0 + params.external_sale_premium
                    )
                    post_liability = (
                        state.external_emission_liability + liability_issued
                    )
                    post_backing = (
                        state.liquid_reserve
                        + state.insurance
                        + 0.50 * (state.lp_pol_syna + state.lp_pol_synr)
                        + sale_proceeds
                    )
                    if (
                        post_backing
                        >= EMISSION_COVERAGE_FLOOR * post_liability
                    ):
                        state.protocol_inventory -= liability_issued
                        state.external_emission_liability = post_liability
                        state.cumulative_external_emission += liability_issued
                        state.liquid_reserve += sale_proceeds
                        issuance_premium = sale_proceeds - liability_issued
                        state.realized_external_pnl += issuance_premium
                        state.cumulative_external_revenue += issuance_premium

                if state.external_emission_liability > 0 and burn_budget > 0:
                    liability_retired = min(
                        state.external_emission_liability,
                        burn_budget / params.qt_discount,
                    )
                    payment = liability_retired * params.qt_discount
                    payment = min(payment, state.liquid_reserve)
                    liability_retired = payment / params.qt_discount
                    state.liquid_reserve -= payment
                    state.external_emission_liability -= liability_retired
                    state.cumulative_external_burn += liability_retired
                    discount_profit = liability_retired - payment
                    state.realized_external_pnl += discount_profit
                else:
                    state.insurance += burn_budget

                state.internal_transfer_volume += (
                    reserve_allocation + burn_budget + lp_allocation + gas_allocation
                )
                state.useful_actions += 1

        if block % 2_000 == 0:
            post = system_metrics(
                state,
                params,
                sigma_latency=sigma_latency,
                redemption_shock=redemption_shock,
                operating_outflow_30d=operating_outflow,
            )
            realized_bound = max(
                0.0, state.realized_external_pnl - state.total_dividends
            )
            liquidity_excess = max(
                0.0,
                float(post["immediate_liquidity_pol"])
                - 1.205 * float(post["stressed_outflows_30d_pol"]),
            )
            dividend = min(0.05 * realized_bound, liquidity_excess)
            if post["single_invariant"] >= 1.10 and dividend > 0:
                state.liquid_reserve -= dividend
                state.total_dividends += dividend

        final_metrics = system_metrics(
            state,
            params,
            sigma_latency=sigma_latency,
            redemption_shock=redemption_shock,
            operating_outflow_30d=operating_outflow,
        )
        nav = float(final_metrics["consolidated_nav_pol"])
        state.peak_nav = max(state.peak_nav, nav)
        if state.peak_nav > 0:
            state.maximum_drawdown = max(
                state.maximum_drawdown,
                (state.peak_nav - nav) / state.peak_nav,
            )

        if final_metrics["mode"] == "ACTIVE":
            state.minimum_active_invariant = min(
                state.minimum_active_invariant,
                float(final_metrics["single_invariant"]),
            )
            state.minimum_active_multiplier = min(
                state.minimum_active_multiplier,
                float(final_metrics["real_liquidity_multiplier"]),
            )

        if block == 1 or block % 100 == 0 or block == blocks:
            history.append(
                {
                    "block": block,
                    "sigma_latency": sigma_latency,
                    "net_external_capital": state.net_external_capital,
                    "realized_external_pnl": state.realized_external_pnl,
                    "dividends": state.total_dividends,
                    "external_emission_liability": state.external_emission_liability,
                    "protocol_inventory": state.protocol_inventory,
                    "pauses": state.pauses,
                    "rejected_actions": state.rejected_actions,
                    **final_metrics,
                }
            )

    return state, history


def optimize_parameters(seed: int = 42) -> List[Dict[str, float | bool]]:
    rows: List[Dict[str, float | bool]] = []
    for lp_fraction in np.linspace(0.50, 0.64, 8):
        for pa_share in np.linspace(0.50, 0.70, 5):
            remaining = 1.0 - lp_fraction
            params = Parameters(
                lp_fraction=float(lp_fraction),
                pa_share_of_lp=float(pa_share),
                liquid_fraction=0.60 * remaining,
                insurance_fraction=0.20 * remaining,
                gas_fraction=0.12 * remaining,
                operations_fraction=0.08 * remaining,
            )
            params.validate()
            state = State()
            allocate_external_capital(state, params.anchor_pol, params)
            scenario_scores: List[float] = []
            multipliers: List[float] = []
            for sigma in (0.02, 0.05, 0.10):
                metric = system_metrics(
                    state,
                    params,
                    sigma_latency=sigma,
                    redemption_shock=5.0,
                    operating_outflow_30d=3.0,
                )
                scenario_scores.append(float(metric["single_invariant"]))
                multipliers.append(float(metric["real_liquidity_multiplier"]))
            rows.append(
                {
                    "lp_fraction": float(lp_fraction),
                    "pa_share": float(pa_share),
                    "minimum_single_invariant": min(scenario_scores),
                    "low_vol_multiplier": multipliers[0],
                    "normal_vol_multiplier": multipliers[1],
                    "high_vol_multiplier": multipliers[2],
                    "robust_pass": min(scenario_scores) >= 1.0,
                }
            )
    return sorted(
        rows,
        key=lambda row: (
            bool(row["robust_pass"]),
            float(row["minimum_single_invariant"]),
        ),
        reverse=True,
    )


def write_outputs(
    state: State,
    history: Iterable[Dict[str, object]],
    frontier: Iterable[Dict[str, object]],
    output_dir: Path,
) -> Dict[str, object]:
    output_dir.mkdir(parents=True, exist_ok=True)
    history_rows = list(history)
    frontier_rows = list(frontier)

    with (output_dir / "real_liquidity_multiplier_v4_trajectory.csv").open(
        "w", newline="", encoding="utf-8"
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=list(history_rows[0].keys()))
        writer.writeheader()
        writer.writerows(history_rows)

    with (output_dir / "real_liquidity_multiplier_v4_frontier.csv").open(
        "w", newline="", encoding="utf-8"
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=list(frontier_rows[0].keys()))
        writer.writeheader()
        writer.writerows(frontier_rows)

    final = history_rows[-1]
    summary: Dict[str, object] = {
        "model": "SYNERGY Real Liquidity Multiplier V4",
        "definition": (
            "stress V2-equivalent executable liquidity across the POL anchor "
            "min-cut divided by net external POL capital"
        ),
        "single_invariant_formula": (
            "min(multiplier/K(sigma), solvency/1.20, liquidity/1.20, "
            "gas/1.20, emissionCoverage/1.20, poolFloor) >= 1"
        ),
        "state": asdict(state),
        "metrics": {
            "final_real_liquidity_multiplier": final[
                "real_liquidity_multiplier"
            ],
            "minimum_active_multiplier": state.minimum_active_multiplier,
            "minimum_active_single_invariant": state.minimum_active_invariant,
            "minimum_observed_multiplier_including_pauses": (
                state.minimum_observed_multiplier
            ),
            "final_economic_solvency_ratio": final[
                "economic_solvency_ratio"
            ],
            "final_liquidity_coverage": final["liquidity_coverage"],
            "final_gas_coverage": final["gas_coverage"],
            "final_external_emission_coverage": final[
                "external_emission_coverage"
            ],
            "maximum_drawdown": state.maximum_drawdown,
            "internal_transfer_revenue": 0.0,
            "cross_pool_counted_in_multiplier": False,
            "dividend_bound": (
                state.total_dividends
                <= max(0.0, state.realized_external_pnl) + 1e-9
            ),
        },
        "parameter_frontier_best": frontier_rows[0],
        "limitations": [
            "The multiplier is V2-equivalent executable depth, not withdrawable POL.",
            "Capital efficiency falls when volatility or keeper latency rises.",
            "Internal SYNA/SYNR emission is assigned zero NAV and excluded from the multiplier.",
            "Future external volume and fee revenue are stochastic assumptions, not guaranteed income.",
        ],
    }
    (output_dir / "real_liquidity_multiplier_v4_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    x = [int(row["block"]) for row in history_rows]
    charts = [
        (
            "real_liquidity_multiplier_v4.png",
            "Stress Real Liquidity Multiplier",
            [float(row["real_liquidity_multiplier"]) for row in history_rows],
        ),
        (
            "single_invariant_v4.png",
            "Single Composite Invariant",
            [float(row["single_invariant"]) for row in history_rows],
        ),
        (
            "solvency_liquidity_v4.png",
            "Economic Solvency Ratio",
            [float(row["economic_solvency_ratio"]) for row in history_rows],
        ),
    ]
    for filename, title, values in charts:
        plt.figure(figsize=(10, 5))
        plt.plot(x, values)
        plt.xlabel("Block")
        plt.ylabel(title)
        plt.title(title)
        plt.tight_layout()
        plt.savefig(output_dir / filename, dpi=160)
        plt.close()

    return summary


def main() -> None:
    params = Parameters()
    state, history = run_path(params=params)
    frontier = optimize_parameters()
    summary = write_outputs(state, history, frontier, Path("reports"))
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
