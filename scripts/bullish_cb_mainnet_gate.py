#!/usr/bin/env python3
"""Fork-to-mainnet solvency gate for the SYNERGY bullish microcycle.

The only economic criterion is:

    delta(TVL + robot balance + central-bank balance) > full gas cost

This script never loads a private key and never signs or broadcasts a transaction.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path


class GateRejected(RuntimeError):
    pass


def validate(report: dict) -> dict:
    required = {
        "chainId": 137,
        "coveredBlocks": 150,
        "cycles": 15,
        "trades": 105,
    }
    for key, expected in required.items():
        if report.get(key) != expected:
            raise GateRejected(f"{key} must equal {expected}")

    if report.get("criterion") != "DELTA_TVL_PLUS_ROBOT_BALANCE_PLUS_CB_BALANCE_GREATER_THAN_GAS":
        raise GateRejected("unexpected solvency criterion")

    capital = report.get("startingCapital", {})
    if capital.get("robotAndCbUsdt") != 1 or capital.get("poolUsdt") != 1:
        raise GateRejected("fork did not use the requested 1+1 USDT capital")
    if capital.get("gasBudgetUsdt") != 1:
        raise GateRejected("fork did not use the requested 1 USDT gas budget")

    solvency = report.get("solvency", {})
    gas = report.get("gas", {})
    gross_growth = float(solvency.get("grossGrowthUsdt", 0))
    gas_cost = float(solvency.get("gasUsdt", gas.get("totalGasUsdt", 0)))
    net_growth = float(solvency.get("netGrowthAfterGasUsdt", gross_growth - gas_cost))

    conditions = {
        "one_usdt_gas_budget": gas.get("oneUsdtBudgetCovered") is True,
        "tvl_robot_cb_growth_exceeds_gas": gross_growth > gas_cost,
        "net_growth_after_gas_positive": net_growth > 0,
        "fork_verdict_solvent": solvency.get("verdict") == "PASS_SOLVENT",
    }
    allowed = all(conditions.values())
    return {
        "stage": "POLYGON_MAINNET_GATE",
        "criterion": report.get("criterion"),
        "broadcastAllowedBySolvencyMetric": allowed,
        "privateKeyLoaded": False,
        "transactionSigned": False,
        "transactionBroadcast": False,
        "conditions": conditions,
        "initialTotalTvlRobotCbUsdt": solvency.get("initialTotalTvlRobotCbUsdt"),
        "finalTotalTvlRobotCbUsdt": solvency.get("finalTotalTvlRobotCbUsdt"),
        "grossGrowthUsdt": gross_growth,
        "gasUsdt": gas_cost,
        "netGrowthAfterGasUsdt": net_growth,
        "reason": "READY_BY_TVL_ROBOT_CB_SOLVENCY_METRIC" if allowed else "BLOCKED_BY_TVL_ROBOT_CB_SOLVENCY_METRIC",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fork-report", type=Path, required=True)
    parser.add_argument("--decision-out", type=Path, default=Path("reports/bullish_cb_mainnet_gate.json"))
    args = parser.parse_args()

    report = json.loads(args.fork_report.read_text(encoding="utf-8"))
    decision = validate(report)
    args.decision_out.parent.mkdir(parents=True, exist_ok=True)
    args.decision_out.write_text(json.dumps(decision, indent=2), encoding="utf-8")
    print(json.dumps(decision, indent=2))
    if not decision["broadcastAllowedBySolvencyMetric"]:
        print("MAINNET BLOCKED BY REQUESTED SOLVENCY METRIC")
        return 2
    print("MAINNET READY BY REQUESTED SOLVENCY METRIC; no key was loaded or transaction signed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
