#!/usr/bin/env python3
"""SYNERGY V15.2 structural-econometric supermodel.

This model deliberately separates:
1) external revenue,
2) internal balance-sheet transformations,
3) liabilities and protocol-owned liquidity damage,
4) execution and operating costs.

It is a scenario engine, not a claim that future order flow is guaranteed.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict, replace
import json
import math
import os
import random
from pathlib import Path
from statistics import mean, median

REPORT_DIR = Path("reports")
PPM = 1_000_000
BPS = 10_000

V14_NEAR_MISS_NOTIONAL = 453.602562
V14_REQUIRED_IMPROVEMENT = 0.121799
V14_HURDLE_BPS = V14_REQUIRED_IMPROVEMENT / V14_NEAR_MISS_NOTIONAL * BPS

INITIAL_EXTERNAL_CAPITAL = 120_000.0
RETENTION_SHARE = 0.80
DAYS = 365
DEFAULT_PATHS = int(os.getenv("SYNERGY_V152_PATHS", "2000"))
SEED = int(os.getenv("SYNERGY_V152_SEED", "152"))


@dataclass(frozen=True)
class Channel:
    name: str
    opportunities_per_day: float
    median_notional: float
    notional_log_sigma: float
    gross_edge_mean_bps: float
    gross_edge_sigma_bps: float
    variable_cost_bps: float
    fixed_execution_cost: float
    capture_probability: float
    false_positive_probability: float
    treasury_share: float


@dataclass(frozen=True)
class Scenario:
    name: str
    arrival_multiplier: float
    edge_add_bps: float
    capture_multiplier: float
    external_fee_revenue_per_day: float
    fixed_operations_cost_per_day: float


BASE_CHANNELS = (
    Channel(
        "graph_arbitrage",
        opportunities_per_day=4.0,
        median_notional=15_000.0,
        notional_log_sigma=0.55,
        gross_edge_mean_bps=6.0,
        gross_edge_sigma_bps=2.5,
        variable_cost_bps=2.0,
        fixed_execution_cost=0.10,
        capture_probability=0.35,
        false_positive_probability=0.015,
        treasury_share=0.65,
    ),
    Channel(
        "intrablock_backrun",
        opportunities_per_day=8.0,
        median_notional=10_000.0,
        notional_log_sigma=0.65,
        gross_edge_mean_bps=7.5,
        gross_edge_sigma_bps=3.0,
        variable_cost_bps=2.5,
        fixed_execution_cost=0.08,
        capture_probability=0.28,
        false_positive_probability=0.02,
        treasury_share=0.65,
    ),
    Channel(
        "private_rfq",
        opportunities_per_day=5.0,
        median_notional=8_000.0,
        notional_log_sigma=0.45,
        gross_edge_mean_bps=6.5,
        gross_edge_sigma_bps=2.0,
        variable_cost_bps=1.8,
        fixed_execution_cost=0.06,
        capture_probability=0.40,
        false_positive_probability=0.01,
        treasury_share=0.65,
    ),
)

SCENARIOS = (
    Scenario("conservative", 0.45, -1.0, 0.65, 1.0, 5.0),
    Scenario("base", 1.00, 0.0, 1.00, 3.0, 8.0),
    Scenario("expansion", 2.00, 1.0, 1.25, 10.0, 20.0),
)


def quantile(values: list[float], q: float) -> float:
    if not values:
        raise ValueError("empty sample")
    ordered = sorted(values)
    position = (len(ordered) - 1) * q
    lower = int(math.floor(position))
    upper = int(math.ceil(position))
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def poisson(rng: random.Random, rate: float) -> int:
    """Knuth Poisson draw; rates used here are deliberately moderate."""
    if rate <= 0:
        return 0
    threshold = math.exp(-rate)
    product = 1.0
    count = 0
    while product > threshold:
        count += 1
        product *= rng.random()
    return count - 1


def normal_positive_part(mean_value: float, sigma: float, hurdle: float) -> float:
    """E[(X-hurdle)+] for X ~ Normal(mean_value, sigma^2)."""
    if sigma <= 0:
        return max(mean_value - hurdle, 0.0)
    z = (hurdle - mean_value) / sigma
    density = math.exp(-0.5 * z * z) / math.sqrt(2.0 * math.pi)
    tail = 0.5 * math.erfc(z / math.sqrt(2.0))
    return sigma * density + (mean_value - hurdle) * tail


def external_net_profit(
    *,
    arbitrage: float = 0.0,
    orderflow: float = 0.0,
    rfq: float = 0.0,
    external_lp_fees: float = 0.0,
    external_yield: float = 0.0,
    gas: float = 0.0,
    dex_fees: float = 0.0,
    slippage: float = 0.0,
    flash_premium: float = 0.0,
    keeper: float = 0.0,
    bridge: float = 0.0,
    mev_loss: float = 0.0,
    protocol_lp_damage: float = 0.0,
    liability_increase: float = 0.0,
    risk_haircut: float = 0.0,
) -> float:
    inflow = arbitrage + orderflow + rfq + external_lp_fees + external_yield
    outflow = (
        gas
        + dex_fees
        + slippage
        + flash_premium
        + keeper
        + bridge
        + mev_loss
        + protocol_lp_damage
        + liability_increase
        + risk_haircut
    )
    return inflow - outflow


def run_path(seed: int, channels: tuple[Channel, ...], scenario: Scenario) -> dict[str, float]:
    rng = random.Random(seed)
    treasury_profit = 0.0
    solver_profit = 0.0
    failed_execution_cost = 0.0
    accepted = 0
    screened = 0
    accepted_notional = 0.0
    daily_profit: list[float] = []

    for _day in range(DAYS):
        day_profit = (
            scenario.external_fee_revenue_per_day
            - scenario.fixed_operations_cost_per_day
        )
        for raw_channel in channels:
            channel = replace(
                raw_channel,
                opportunities_per_day=(
                    raw_channel.opportunities_per_day
                    * scenario.arrival_multiplier
                ),
                gross_edge_mean_bps=(
                    raw_channel.gross_edge_mean_bps
                    + scenario.edge_add_bps
                ),
                capture_probability=min(
                    1.0,
                    raw_channel.capture_probability
                    * scenario.capture_multiplier,
                ),
            )
            for _ in range(poisson(rng, channel.opportunities_per_day)):
                if rng.random() > channel.capture_probability:
                    continue
                screened += 1
                notional = math.exp(
                    math.log(channel.median_notional)
                    + channel.notional_log_sigma * rng.gauss(0.0, 1.0)
                )
                gross_edge_bps = (
                    channel.gross_edge_mean_bps
                    + channel.gross_edge_sigma_bps * rng.gauss(0.0, 1.0)
                )
                route_profit = (
                    notional
                    * (gross_edge_bps - channel.variable_cost_bps)
                    / BPS
                    - channel.fixed_execution_cost
                )
                route_edge_bps = route_profit / notional * BPS

                if rng.random() < channel.false_positive_probability:
                    day_profit -= channel.fixed_execution_cost
                    failed_execution_cost += channel.fixed_execution_cost
                    continue

                if route_profit <= 0.0 or route_edge_bps < V14_HURDLE_BPS:
                    continue

                treasury_take = route_profit * channel.treasury_share
                solver_take = route_profit - treasury_take
                if (
                    treasury_take < V14_REQUIRED_IMPROVEMENT
                    or solver_take <= channel.fixed_execution_cost
                ):
                    continue

                accepted += 1
                accepted_notional += notional
                day_profit += treasury_take
                solver_profit += solver_take

        treasury_profit += day_profit
        daily_profit.append(day_profit)

    retained_profit = treasury_profit * RETENTION_SHARE
    ending_capital = INITIAL_EXTERNAL_CAPITAL + retained_profit
    return {
        "treasury_profit": treasury_profit,
        "solver_profit": solver_profit,
        "retained_profit": retained_profit,
        "ending_capital": ending_capital,
        "capital_growth_factor": ending_capital / INITIAL_EXTERNAL_CAPITAL,
        "accepted_opportunities": accepted,
        "screened_opportunities": screened,
        "accepted_notional": accepted_notional,
        "failed_execution_cost": failed_execution_cost,
        "worst_day": min(daily_profit),
        "best_day": max(daily_profit),
    }


def summarize_scenario(scenario: Scenario, paths: int) -> dict[str, object]:
    results = [
        run_path(SEED * 100_000 + index, BASE_CHANNELS, scenario)
        for index in range(paths)
    ]
    profits = [row["treasury_profit"] for row in results]
    growth = [row["capital_growth_factor"] for row in results]
    accepted = [row["accepted_opportunities"] for row in results]
    notional = [row["accepted_notional"] for row in results]
    return {
        "scenario": asdict(scenario),
        "paths": paths,
        "treasury_profit": {
            "mean": mean(profits),
            "median": median(profits),
            "p05": quantile(profits, 0.05),
            "p95": quantile(profits, 0.95),
            "probability_positive": sum(value > 0 for value in profits) / paths,
        },
        "capital_growth_factor_after_80pct_retention": {
            "median": median(growth),
            "p05": quantile(growth, 0.05),
            "p95": quantile(growth, 0.95),
        },
        "median_accepted_opportunities": median(accepted),
        "median_accepted_notional": median(notional),
        "median_effective_treasury_take_bps": (
            median(profits) / median(notional) * BPS
            if median(notional) > 0
            else 0.0
        ),
        "limitations": [
            "Opportunity arrival, notional, edge and capture parameters are scenarios, not fitted live estimates.",
            "Atomic reverts bound route loss but false positives may still burn gas.",
            "Solver-auction payments are not counted separately from route profit, preventing double counting.",
            "Internal mint, burn, transfer volume and mark-to-market changes are assigned zero revenue.",
        ],
    }


def turnover_frontier() -> list[dict[str, float]]:
    rows = []
    for turnover_multiple in (0.5, 1.0, 2.0, 3.0, 5.0, 10.0):
        daily_retained_rate = (
            RETENTION_SHARE
            * turnover_multiple
            * V14_HURDLE_BPS
            / BPS
        )
        annual_factor = math.exp(DAYS * daily_retained_rate)
        rows.append(
            {
                "daily_turnover_multiple_of_capital": turnover_multiple,
                "net_edge_bps": V14_HURDLE_BPS,
                "retention_share": RETENTION_SHARE,
                "annual_compound_growth_factor": annual_factor,
                "annual_compound_return": annual_factor - 1.0,
            }
        )
    return rows


def evidence_derived_metrics() -> dict[str, object]:
    return {
        "v14_strict_hurdle": {
            "near_miss_notional_usd": V14_NEAR_MISS_NOTIONAL,
            "required_improvement_usd": V14_REQUIRED_IMPROVEMENT,
            "required_net_edge_bps": V14_HURDLE_BPS,
        },
        "v5_fork_compounding": {
            "initial_external_capital_pol": 120.0,
            "realized_external_profit_pol": 20.0,
            "ending_backed_capital_pol": 139.8,
            "growth_factor": 1.165,
            "cash_dividend_pol": 0.0,
        },
        "v6_fork_self_support": {
            "initial_external_capital_pol": 120.0,
            "gross_external_revenue_pol": 25.0,
            "keeper_reimbursement_pol": 1.4,
            "net_external_profit_pol": 23.6,
            "ending_backed_capital_pol": 143.364,
            "growth_factor": 1.1947,
            "keeper_cost_coverage": 1.7343183111735518,
        },
        "v7_graph_model": {
            "realized_external_profit": 6.795851555153707,
            "growth_factor": 1.0560657753300176,
            "minimum_multiplier": 3.184479120855431,
            "internal_transfer_revenue": 0.0,
        },
        "v11_conditional_atomic_closure": {
            "classification": "conditional shock fixture, not baseline market estimate",
            "consolidated_token_profit_usdt": 49.179634,
            "gas_usdt": 0.036994,
            "temporary_supply_closed": True,
        },
        "v12_falsification": {
            "wallet_profit_usdt": 3237.964779,
            "internal_lp_delta_usdt": -6120.191629,
            "consolidated_delta_after_gas_usdt": -2882.227763,
            "accepted_as_revenue": False,
        },
        "v13_snapshot_only": {
            "snapshot_sum_after_gas_usd": 42.14740836494275,
            "stateful_profit_proved": False,
        },
        "v14_stateful": {
            "accepted_cycles": 0,
            "realized_nav_usd": 0.0,
            "reverse_route_funding_failures": 396,
        },
    }


def build_report(paths: int = DEFAULT_PATHS) -> dict[str, object]:
    scenario_results = [
        summarize_scenario(scenario, paths)
        for scenario in SCENARIOS
    ]
    positive_part = {}
    for channel in BASE_CHANNELS:
        net_mean = channel.gross_edge_mean_bps - channel.variable_cost_bps
        positive_part[channel.name] = {
            "net_edge_mean_before_fixed_cost_bps": net_mean,
            "sigma_bps": channel.gross_edge_sigma_bps,
            "expected_bps_above_v14_hurdle": normal_positive_part(
                net_mean,
                channel.gross_edge_sigma_bps,
                V14_HURDLE_BPS,
            ),
        }

    return {
        "model": "SYNERGY V15.2 structural-econometric supermodel",
        "economic_position": (
            "supportive: internal monetary mechanics are treated as capital-control "
            "technology; sustainable value comes from captured external surplus "
            "and disciplined compounding"
        ),
        "accounting_identity": (
            "Delta external NAV = external arbitrage + orderflow + RFQ + "
            "external LP fees + external yield - gas - DEX fees - slippage - "
            "flash premium - keeper - bridge - MEV loss - protocol LP damage - "
            "liability increase - risk haircut"
        ),
        "strict_non_revenue": [
            "minted protocol tokens",
            "internal transfers",
            "internal pool marks",
            "market-cap changes without realizable reserve",
            "flash-loan principal",
            "refundable solver bonds",
            "protocol-funded solver bids",
            "wallet profit offset by protocol-owned LP loss",
        ],
        "evidence_metrics": evidence_derived_metrics(),
        "normal_selective_surplus": positive_part,
        "turnover_frontier": turnover_frontier(),
        "scenario_results": scenario_results,
        "acceptance_rule": {
            "minimum_route_edge_bps": V14_HURDLE_BPS,
            "minimum_treasury_revenue": V14_REQUIRED_IMPROVEMENT,
            "solver_net_after_attributable_cost_must_be_positive": True,
            "consolidated_external_nav_after_costs_must_increase": True,
            "internal_protocol_lp_damage_is_deducted": True,
            "new_external_liability_is_deducted": True,
        },
        "econometric_estimation_plan": {
            "dependent_variable": "realized consolidated external PnL / executed notional",
            "regressors": [
                "pre-trade cross-DEX spread",
                "victim price displacement",
                "log external pool TVL",
                "realized volatility",
                "gas and priority fee",
                "route hop count",
                "solver competition count",
                "private inclusion indicator",
                "RFQ quote dispersion",
                "protocol-owned LP inventory imbalance",
            ],
            "equation": (
                "pi_i/N_i = alpha + beta1*spread + beta2*displacement "
                "+ beta3*log(TVL) + beta4*volatility - beta5*gas "
                "- beta6*competition + beta7*private_inclusion + epsilon_i"
            ),
            "method": [
                "walk-forward estimation only",
                "HAC or block-clustered standard errors",
                "quantile regression for downside",
                "selection correction for attempted versus rejected routes",
                "out-of-sample probability calibration",
                "no same-block quote reuse after protocol execution",
            ],
        },
        "limitations": [
            "The Monte Carlo scenarios are transparent assumptions, not a fitted forecast.",
            "V5/V6 fork revenue is an accounting and control demonstration, not proof of recurring market demand.",
            "V11 proves atomic closure under a funded shock fixture, not naturally recurring order flow.",
            "V14 is the binding strict baseline for internally generated gradients: zero realized edge in the tested range.",
            "A live econometric estimate requires historical transaction-level opportunity and execution data.",
        ],
    }


def render_markdown(report: dict[str, object]) -> str:
    lines = [
        "# SYNERGY V15.2 — structural-econometric report",
        "",
        f"Strict V14 hurdle: **{V14_HURDLE_BPS:.6f} bps** "
        f"or **${V14_REQUIRED_IMPROVEMENT:.6f}** on "
        f"**${V14_NEAR_MISS_NOTIONAL:.6f}** notional.",
        "",
        "## Scenario results",
        "",
        "| Scenario | Median annual treasury PnL | P05 | P95 | P(PnL>0) | Median retained capital factor |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for row in report["scenario_results"]:
        pnl = row["treasury_profit"]
        growth = row["capital_growth_factor_after_80pct_retention"]
        lines.append(
            f"| {row['scenario']['name']} | {pnl['median']:.2f} | "
            f"{pnl['p05']:.2f} | {pnl['p95']:.2f} | "
            f"{pnl['probability_positive']:.2%} | {growth['median']:.6f} |"
        )
    lines.extend([
        "",
        "## Turnover frontier at the strict V14 hurdle",
        "",
        "| Daily turnover / capital | Annual compound factor | Annual return |",
        "|---:|---:|---:|",
    ])
    for row in report["turnover_frontier"]:
        lines.append(
            f"| {row['daily_turnover_multiple_of_capital']:.1f}x | "
            f"{row['annual_compound_growth_factor']:.6f} | "
            f"{row['annual_compound_return']:.2%} |"
        )
    lines.extend([
        "",
        "These are conditional mechanics. They are not promises of order flow, "
        "capacity, fill rate or future return.",
        "",
    ])
    return "\n".join(lines)


def main() -> None:
    report = build_report()
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    (REPORT_DIR / "synergy_v15_2_econometric_supermodel.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    (REPORT_DIR / "SYNERGY_V15_2_ECONOMETRIC_REPORT.md").write_text(
        render_markdown(report),
        encoding="utf-8",
    )
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
