"""Twenty-scenario stress matrix for consolidated SYNERGY V3."""
from __future__ import annotations

import csv
import json
from dataclasses import asdict
from pathlib import Path
from typing import Callable, Dict

from consolidated_solvency_v3 import (
    State,
    consolidated_nav,
    determine_mode,
    gas_coverage,
    haircut_assets,
    liquidity_coverage,
    reserve_policy_ratio,
    run_path,
    solvency_ratio,
    stress_liabilities,
)


def apply_post_shock(state: State, scenario: Dict[str, object]) -> None:
    state.stable_lp *= float(scenario.get("stable_lp_mult", 1.0))
    state.volatile_lp *= float(scenario.get("volatile_lp_mult", 1.0))
    state.bridge *= float(scenario.get("bridge_mult", 1.0))
    state.productive_yield *= float(scenario.get("yield_mult", 1.0))
    state.inventory_value *= float(scenario.get("inventory_mult", 1.0))
    state.external_synr_claims *= float(scenario.get("synr_claim_mult", 1.0))
    state.redemption_shock += float(scenario.get("redemption_add", 0.0))
    state.stressed_outflows_30d += float(scenario.get("outflow_add", 0.0))


def main() -> None:
    scenarios = [
        {"name": "baseline"},
        {"name": "zero_external_revenue", "external_revenue": False},
        {"name": "zero_mev", "mev_enabled": False},
        {"name": "zero_user_volume", "user_volume_enabled": False},
        {"name": "gas_50_gwei", "gas_multiplier": 50 / 274},
        {"name": "gas_274_gwei", "gas_multiplier": 1.0},
        {"name": "gas_500_gwei", "gas_multiplier": 500 / 274},
        {"name": "gas_1000_gwei", "gas_multiplier": 1000 / 274},
        {"name": "gas_5000_gwei", "gas_multiplier": 5000 / 274},
        {"name": "syna_drop_30", "volatile_lp_mult": 0.70, "inventory_mult": 0.70},
        {"name": "syna_drop_50", "volatile_lp_mult": 0.50, "inventory_mult": 0.50},
        {"name": "syna_drop_80", "volatile_lp_mult": 0.20, "inventory_mult": 0.20},
        {"name": "synr_below_peg", "synr_claim_mult": 1.25},
        {"name": "redemption_10", "redemption_add": 10.0, "outflow_add": 10.0},
        {"name": "redemption_30", "redemption_add": 30.0, "outflow_add": 30.0},
        {"name": "redemption_50", "redemption_add": 50.0, "outflow_add": 50.0},
        {"name": "lp_liquidity_shock_50", "stable_lp_mult": 0.50, "volatile_lp_mult": 0.50},
        {"name": "bridge_downtime", "bridge_available": False, "bridge_mult": 0.50},
        {"name": "oracle_stale", "oracle_fresh": False},
        {"name": "flash_liquidity_unavailable", "external_revenue": False, "mev_enabled": False},
        {"name": "slippage_spike", "gas_multiplier": 3.0, "redemption_multiplier": 2.0},
        {"name": "mev_claim_wave", "redemption_add": 25.0, "outflow_add": 25.0},
        {"name": "keeper_outage", "external_revenue": False, "user_volume_enabled": False},
        {"name": "adverse_selection", "gas_multiplier": 2.0, "redemption_multiplier": 2.5},
        {"name": "dividend_before_shock", "redemption_add": 40.0, "outflow_add": 40.0},
    ]

    rows = []
    for index, scenario in enumerate(scenarios):
        state, _ = run_path(
            blocks=20_000,
            seed=42 + index,
            external_revenue=bool(scenario.get("external_revenue", True)),
            mev_enabled=bool(scenario.get("mev_enabled", True)),
            user_volume_enabled=bool(scenario.get("user_volume_enabled", True)),
            gas_multiplier=float(scenario.get("gas_multiplier", 1.0)),
            redemption_multiplier=float(scenario.get("redemption_multiplier", 1.0)),
            bridge_available=bool(scenario.get("bridge_available", True)),
            oracle_fresh=bool(scenario.get("oracle_fresh", True)),
        )
        apply_post_shock(state, scenario)
        state.mode = determine_mode(
            state,
            external_opportunity=state.realized_external_pnl > 0,
            oracle_fresh=bool(scenario.get("oracle_fresh", True)),
            bridge_available=bool(scenario.get("bridge_available", True)),
        )
        sr = solvency_ratio(state)
        lc = liquidity_coverage(state)
        gc = gas_coverage(state)
        pr = reserve_policy_ratio(state)
        no_false_dividend = state.dividends <= max(0.0, state.realized_external_pnl) + 1e-9
        no_negative_reserve = min(
            state.liquid,
            state.stable_lp,
            state.volatile_lp,
            state.bridge,
            state.insurance,
            state.productive_yield,
            state.gas_reserve,
        ) >= -1e-9
        safe = sr >= 1.0 and no_false_dividend and no_negative_reserve and state.insolvency_events == 0
        rows.append(
            {
                "scenario": scenario["name"],
                "mode": state.mode,
                "haircut_assets": haircut_assets(state),
                "stress_liabilities": stress_liabilities(state),
                "consolidated_nav": consolidated_nav(state),
                "solvency_ratio": sr,
                "liquidity_coverage": lc,
                "gas_coverage": gc,
                "reserve_policy_ratio": pr,
                "external_pnl": state.realized_external_pnl,
                "dividends": state.dividends,
                "pool_depth": state.main_pool_depth,
                "pauses": state.pauses,
                "gas_skips": state.gas_skips,
                "safe": safe,
            }
        )

    out = Path("reports")
    out.mkdir(parents=True, exist_ok=True)
    with (out / "stress_matrix.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    summary = {
        "scenarios": len(rows),
        "safe_scenarios": sum(bool(row["safe"]) for row in rows),
        "failed_scenarios": [row["scenario"] for row in rows if not row["safe"]],
        "minimum_solvency_ratio": min(float(row["solvency_ratio"]) for row in rows),
        "minimum_liquidity_coverage": min(float(row["liquidity_coverage"]) for row in rows),
        "minimum_gas_coverage": min(float(row["gas_coverage"]) for row in rows),
        "rows": rows,
    }
    (out / "stress_matrix.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
