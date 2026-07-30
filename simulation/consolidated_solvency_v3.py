"""Consolidated SYNERGY solvency model V3.

Market capitalization is excluded from NAV. Transfers among system-owned
modules never create revenue. Every action is checked against projected,
post-action solvency, liquidity and gas coverage.
"""
from __future__ import annotations

import csv
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Dict, Iterable, List

import matplotlib.pyplot as plt
import numpy as np

NORMAL_SOLVENCY = 1.20
DEFENSIVE_SOLVENCY = 1.05
NORMAL_LIQUIDITY = 1.20
LIQUIDITY_ACTION_BUFFER = 1.205
MIN_GAS_COVERAGE = 1.20
GAS_ACTION_BUFFER = 1.2005
MIN_POLICY_RATIO = 0.70
MIN_POOL_DEPTH = 25.0
BASE_STRESSED_OUTFLOWS = 45.0


@dataclass
class State:
    liquid: float = 100.0
    stable_lp: float = 40.0
    volatile_lp: float = 20.0
    bridge: float = 20.0
    insurance: float = 10.0
    productive_yield: float = 10.0
    gas_reserve: float = 6.0
    inventory_value: float = 0.0
    external_syn_liability: float = 70.0
    external_synr_claims: float = 20.0
    vested_mev_claims: float = 5.0
    bridge_obligations: float = 2.0
    keeper_accrual: float = 1.0
    external_debt: float = 0.0
    operating_cost_30d: float = 2.0
    redemption_shock: float = 0.0
    immediate_liquid: float = 75.0
    stressed_outflows_30d: float = BASE_STRESSED_OUTFLOWS
    reimbursed_gas: float = 30.0
    reserve_policy_capital: float = 105.0
    conservative_obligations: float = 140.0
    realized_external_pnl: float = 0.0
    cumulative_external_revenue: float = 0.0
    cumulative_external_cost: float = 0.0
    internal_transfer_volume: float = 0.0
    dividends: float = 0.0
    external_supply: float = 70.0
    protocol_inventory: float = 30.0
    main_pool_depth: float = 60.0
    maximum_drawdown: float = 0.0
    peak_nav: float = 0.0
    pauses: int = 0
    useful_actions: int = 0
    gas_skips: int = 0
    insolvency_events: int = 0
    mode: str = "BOOTSTRAP"


def haircut_assets(s: State) -> float:
    return (
        s.liquid
        + s.gas_reserve
        + 0.85 * s.stable_lp
        + 0.65 * s.volatile_lp
        + 0.70 * s.bridge
        + 0.90 * s.insurance
        + 0.80 * s.productive_yield
        + 0.25 * s.inventory_value
    )


def stress_liabilities(s: State) -> float:
    return (
        s.external_syn_liability
        + s.external_synr_claims
        + s.vested_mev_claims
        + s.bridge_obligations
        + s.keeper_accrual
        + s.external_debt
        + s.operating_cost_30d
        + s.redemption_shock
    )


def consolidated_nav(s: State) -> float:
    return haircut_assets(s) - stress_liabilities(s)


def solvency_ratio(s: State) -> float:
    liabilities = stress_liabilities(s)
    return float("inf") if liabilities <= 0 else haircut_assets(s) / liabilities


def liquidity_coverage(s: State) -> float:
    return float("inf") if s.stressed_outflows_30d <= 0 else s.immediate_liquid / s.stressed_outflows_30d


def gas_coverage(s: State) -> float:
    return float("inf") if s.reimbursed_gas <= 0 else (s.reimbursed_gas + s.gas_reserve) / s.reimbursed_gas


def reserve_policy_ratio(s: State) -> float:
    return (
        float("inf")
        if s.conservative_obligations <= 0
        else s.reserve_policy_capital / s.conservative_obligations
    )


def determine_mode(
    s: State,
    *,
    external_opportunity: bool,
    oracle_fresh: bool = True,
    bridge_available: bool = True,
) -> str:
    sr = solvency_ratio(s)
    lc = liquidity_coverage(s)
    gc = gas_coverage(s)
    pr = reserve_policy_ratio(s)
    if not oracle_fresh or not bridge_available or not external_opportunity:
        return "PAUSED"
    if sr < DEFENSIVE_SOLVENCY or lc < DEFENSIVE_SOLVENCY or gc < MIN_GAS_COVERAGE:
        return "PAUSED"
    if sr < NORMAL_SOLVENCY or lc < NORMAL_LIQUIDITY or pr < MIN_POLICY_RATIO:
        return "DEFENSIVE"
    return "NORMAL"


def required_capital(s: State) -> float:
    return NORMAL_SOLVENCY * stress_liabilities(s) + 5.0 + 3.0 + 3.0


def dividendable_capital(s: State) -> float:
    realized_bound = max(0.0, s.realized_external_pnl - s.dividends)
    nav_bound = max(0.0, consolidated_nav(s) - 11.0 - s.operating_cost_30d)
    return min(realized_bound, nav_bound)


def projected_gas_coverage(s: State, gas_cost: float, net: float) -> float:
    reimbursed = s.reimbursed_gas + gas_cost
    reserve = s.gas_reserve + 0.20 * net
    return (reimbursed + reserve) / reimbursed


def projected_liquidity_coverage(s: State, net: float) -> float:
    return (s.immediate_liquid + 0.70 * net) / s.stressed_outflows_30d


def liquidity_slack(s: State) -> float:
    return max(0.0, s.immediate_liquid - LIQUIDITY_ACTION_BUFFER * s.stressed_outflows_30d)


def run_path(
    blocks: int = 20_000,
    seed: int = 42,
    *,
    external_revenue: bool = True,
    mev_enabled: bool = True,
    user_volume_enabled: bool = True,
    gas_multiplier: float = 1.0,
    redemption_multiplier: float = 1.0,
    bridge_available: bool = True,
    oracle_fresh: bool = True,
) -> tuple[State, List[Dict[str, float | int | str]]]:
    rng = np.random.default_rng(seed)
    s = State()
    s.peak_nav = consolidated_nav(s)
    history: List[Dict[str, float | int | str]] = []

    for block in range(1, blocks + 1):
        user_volume = float(rng.lognormal(-2.7, 0.65)) if user_volume_enabled else 0.0
        mev_fee = float(rng.lognormal(-5.0, 0.8)) if mev_enabled else 0.0
        service_revenue = float(rng.lognormal(-5.2, 0.55)) if external_revenue else 0.0
        yield_revenue = max(0.0, s.productive_yield * float(rng.normal(0.000018, 0.000006)))
        gross_external = 0.0025 * user_volume + mev_fee + service_revenue + yield_revenue
        external_opportunity = gross_external > 0.00015

        gas_cost = gas_multiplier * max(0.00008, float(rng.lognormal(-8.7, 0.45)))
        slippage = 0.0008 * user_volume * (1.0 + max(0.0, float(rng.normal(0.0, 0.4))))
        adverse_selection = 0.00035 * user_volume * max(0.0, float(rng.normal(1.0, 0.35)))
        total_cost = gas_cost + slippage + adverse_selection
        minimum_margin = 0.0001
        net_candidate = gross_external - total_cost

        s.mode = determine_mode(
            s,
            external_opportunity=external_opportunity,
            oracle_fresh=oracle_fresh,
            bridge_available=bridge_available,
        )
        execute = (
            s.mode in {"NORMAL", "DEFENSIVE"}
            and net_candidate > minimum_margin
            and projected_gas_coverage(s, gas_cost, net_candidate) >= GAS_ACTION_BUFFER
            and projected_liquidity_coverage(s, net_candidate) >= NORMAL_LIQUIDITY
        )

        if not execute:
            s.pauses += 1
            if external_opportunity:
                s.gas_skips += 1
        else:
            net = net_candidate
            s.cumulative_external_revenue += gross_external
            s.cumulative_external_cost += total_cost
            s.realized_external_pnl += net
            s.liquid += net
            s.immediate_liquid += 0.70 * net
            s.gas_reserve += 0.20 * net
            s.insurance += 0.10 * net
            s.reimbursed_gas += gas_cost
            s.useful_actions += 1

            external_issue = min(0.018 * user_volume, s.protocol_inventory)
            external_redeem = min(
                s.external_supply,
                external_issue * float(rng.uniform(0.70, 1.05)),
            )
            s.protocol_inventory -= external_issue
            s.external_supply += external_issue - external_redeem
            s.external_syn_liability += external_issue - external_redeem
            s.internal_transfer_volume += 3.0 * gross_external
            s.main_pool_depth += 0.25 * net

        if block % 50 == 0:
            shock = redemption_multiplier * max(0.0, float(rng.normal(0.08, 0.035)))
            s.redemption_shock = shock * (s.external_syn_liability + s.external_synr_claims)
        if block % 200 == 0:
            s.redemption_shock *= 0.50
        if block % 50 == 0:
            s.stressed_outflows_30d = max(20.0, BASE_STRESSED_OUTFLOWS + s.redemption_shock)

        if block % 500 == 0 and s.mode == "NORMAL":
            excess = max(0.0, s.liquid - required_capital(s))
            qe = min(0.10 * excess, 5.0, liquidity_slack(s))
            if qe > 0:
                s.liquid -= qe
                s.stable_lp += 0.50 * qe
                s.bridge += 0.25 * qe
                s.insurance += 0.25 * qe
                s.immediate_liquid -= qe
                s.internal_transfer_volume += qe

        if block % 1000 == 0 and s.mode == "NORMAL":
            capacity = dividendable_capital(s)
            dividend = min(
                0.10 * capacity,
                max(0.0, s.liquid - required_capital(s)),
                liquidity_slack(s),
            )
            if dividend > 0:
                s.liquid -= dividend
                s.immediate_liquid -= dividend
                s.dividends += dividend

        s.mode = determine_mode(
            s,
            external_opportunity=external_opportunity,
            oracle_fresh=oracle_fresh,
            bridge_available=bridge_available,
        )
        nav = consolidated_nav(s)
        s.peak_nav = max(s.peak_nav, nav)
        if s.peak_nav > 0:
            s.maximum_drawdown = max(s.maximum_drawdown, (s.peak_nav - nav) / s.peak_nav)
        if solvency_ratio(s) < 1.0:
            s.insolvency_events += 1
            s.mode = "PAUSED"

        if block == 1 or block % 100 == 0 or block == blocks:
            history.append(
                {
                    "block": block,
                    "mode": s.mode,
                    "haircut_assets": haircut_assets(s),
                    "stress_liabilities": stress_liabilities(s),
                    "nav": nav,
                    "solvency_ratio": solvency_ratio(s),
                    "liquidity_coverage": liquidity_coverage(s),
                    "gas_coverage": gas_coverage(s),
                    "reserve_policy_ratio": reserve_policy_ratio(s),
                    "external_pnl": s.realized_external_pnl,
                    "internal_transfers": s.internal_transfer_volume,
                    "dividends": s.dividends,
                    "external_supply": s.external_supply,
                    "protocol_inventory": s.protocol_inventory,
                    "pool_depth": s.main_pool_depth,
                }
            )

    return s, history


def write_outputs(output_dir: Path, state: State, history: Iterable[Dict[str, object]]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    rows = list(history)
    with (output_dir / "consolidated_trajectory.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    summary = {
        "state": asdict(state),
        "metrics": {
            "haircut_assets": haircut_assets(state),
            "stress_liabilities": stress_liabilities(state),
            "consolidated_nav": consolidated_nav(state),
            "economic_solvency_ratio": solvency_ratio(state),
            "liquidity_coverage": liquidity_coverage(state),
            "gas_coverage": gas_coverage(state),
            "reserve_policy_ratio": reserve_policy_ratio(state),
            "dividend_invariant": state.dividends <= max(0.0, state.realized_external_pnl),
            "internal_transfer_revenue": 0.0,
        },
    }
    (output_dir / "consolidated_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    x = [int(r["block"]) for r in rows]
    chart_specs = [
        ("consolidated_nav.png", "Consolidated NAV", "nav"),
        ("solvency_ratio.png", "Economic Solvency Ratio", "solvency_ratio"),
        ("liquidity_coverage.png", "Liquidity Coverage", "liquidity_coverage"),
    ]
    for filename, title, key in chart_specs:
        plt.figure(figsize=(10, 5.5))
        plt.plot(x, [float(r[key]) for r in rows])
        plt.xlabel("Block")
        plt.title(title)
        plt.tight_layout()
        plt.savefig(output_dir / filename, dpi=160)
        plt.close()

    plt.figure(figsize=(10, 5.5))
    plt.plot(x, [float(r["external_pnl"]) for r in rows], label="External realized PnL")
    plt.plot(x, [float(r["dividends"]) for r in rows], label="Dividends")
    plt.xlabel("Block")
    plt.title("External PnL and Dividends")
    plt.legend()
    plt.tight_layout()
    plt.savefig(output_dir / "external_pnl_dividends.png", dpi=160)
    plt.close()

    plt.figure(figsize=(10, 5.5))
    plt.plot(x, [float(r["external_supply"]) for r in rows], label="External supply")
    plt.plot(x, [float(r["protocol_inventory"]) for r in rows], label="Protocol inventory")
    plt.xlabel("Block")
    plt.title("External Supply and Protocol Inventory")
    plt.legend()
    plt.tight_layout()
    plt.savefig(output_dir / "mm_inventory.png", dpi=160)
    plt.close()


def main() -> None:
    state, history = run_path()
    write_outputs(Path("reports"), state, history)
    print(
        json.dumps(
            {
                "mode": state.mode,
                "solvency_ratio": solvency_ratio(state),
                "liquidity_coverage": liquidity_coverage(state),
                "gas_coverage": gas_coverage(state),
                "external_pnl": state.realized_external_pnl,
                "dividends": state.dividends,
                "insolvency_events": state.insolvency_events,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
