#!/usr/bin/env python3
"""Fail-closed validator for the SYNERGY V15.2 economic synthesis."""
from __future__ import annotations

import json
import math
from pathlib import Path

REPORT = Path("reports/synergy_v15_2_econometric_supermodel.json")
LEDGER = Path("economics/synergy_v1_v15_evidence_ledger.json")
VERDICT = Path("reports/synergy_v15_2_econometric_verdict.json")


def finite_positive(value: object) -> bool:
    return isinstance(value, (int, float)) and math.isfinite(float(value)) and float(value) > 0


def main() -> None:
    if not REPORT.exists():
        raise SystemExit(f"missing {REPORT}")
    if not LEDGER.exists():
        raise SystemExit(f"missing {LEDGER}")

    report = json.loads(REPORT.read_text(encoding="utf-8"))
    ledger = json.loads(LEDGER.read_text(encoding="utf-8"))
    versions = ledger.get("versions", [])
    evidence = report.get("evidence_metrics", {})
    scenarios = report.get("scenario_results", [])
    frontier = report.get("turnover_frontier", [])
    strict_non_revenue = set(report.get("strict_non_revenue", []))

    v14 = evidence.get("v14_strict_hurdle", {})
    v12 = evidence.get("v12_falsification", {})
    v14_edge = float(v14.get("required_net_edge_bps", 0.0))
    recomputed_v14_edge = (
        float(v14.get("required_improvement_usd", 0.0))
        / float(v14.get("near_miss_notional_usd", 1.0))
        * 10_000.0
    )

    scenario_by_name = {
        row.get("scenario", {}).get("name"): row for row in scenarios
    }
    growth_values = [
        float(row.get("annual_compound_growth_factor", 0.0))
        for row in frontier
    ]

    checks = {
        "all_v1_to_v15_represented": (
            len(versions) == 15
            and [row.get("version") for row in versions[:14]]
            == [f"V{i}" for i in range(1, 15)]
            and versions[14].get("version") == "V15/V15.1"
        ),
        "v14_hurdle_recomputed": abs(v14_edge - recomputed_v14_edge) <= 1e-9,
        "v14_hurdle_is_about_2_685_bps": 2.68 <= v14_edge <= 2.69,
        "v12_wallet_profit_rejected": (
            v12.get("accepted_as_revenue") is False
            and float(v12.get("consolidated_delta_after_gas_usdt", 0.0)) < 0
        ),
        "internal_mint_not_revenue": "minted protocol tokens" in strict_non_revenue,
        "internal_transfers_not_revenue": "internal transfers" in strict_non_revenue,
        "solver_bonds_not_revenue": "refundable solver bonds" in strict_non_revenue,
        "own_solver_bids_not_revenue": "protocol-funded solver bids" in strict_non_revenue,
        "three_scenarios_present": set(scenario_by_name) == {
            "conservative", "base", "expansion"
        },
        "base_p05_positive": (
            float(
                scenario_by_name.get("base", {})
                .get("treasury_profit", {})
                .get("p05", -1)
            ) > 0
        ),
        "expansion_p05_positive": (
            float(
                scenario_by_name.get("expansion", {})
                .get("treasury_profit", {})
                .get("p05", -1)
            ) > 0
        ),
        "conservative_not_forced_positive": (
            float(
                scenario_by_name.get("conservative", {})
                .get("treasury_profit", {})
                .get("probability_positive", 1.0)
            ) < 1.0
        ),
        "turnover_frontier_monotone": (
            len(growth_values) >= 4
            and all(
                growth_values[index] < growth_values[index + 1]
                for index in range(len(growth_values) - 1)
            )
        ),
        "external_nav_acceptance_required": (
            report.get("acceptance_rule", {})
            .get("consolidated_external_nav_after_costs_must_increase") is True
        ),
        "lp_damage_deducted": (
            report.get("acceptance_rule", {})
            .get("internal_protocol_lp_damage_is_deducted") is True
        ),
        "liability_increase_deducted": (
            report.get("acceptance_rule", {})
            .get("new_external_liability_is_deducted") is True
        ),
        "econometric_plan_present": bool(
            report.get("econometric_estimation_plan", {}).get("regressors")
        ),
        "scenario_outputs_finite": all(
            finite_positive(
                row.get("capital_growth_factor_after_80pct_retention", {})
                .get("median")
            )
            for row in scenarios
        ),
    }

    failed = [name for name, passed in checks.items() if not passed]
    result = {
        "verdict": "PASS" if not failed else "FAIL",
        "checks": checks,
        "failed_checks": failed,
        "interpretation": (
            "PASS validates internal arithmetic, evidence classification and "
            "fail-closed economic rules. It does not convert scenario assumptions "
            "into a live revenue forecast or prove HISTORICAL_EDGE_PASS."
        ),
    }
    VERDICT.parent.mkdir(parents=True, exist_ok=True)
    VERDICT.write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
