#!/usr/bin/env python3
"""Fail-closed fork-to-mainnet gate for the SYNERGY bullish microcycle.

This script never loads a private key and never signs a transaction. It validates
fork evidence first. A separate reviewed mainnet adapter may only run after this
process exits with code 0.
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

    capital = report.get("startingCapital", {})
    if capital.get("cbAndRobotUsdt") != 1 or capital.get("poolUsdt") != 1:
        raise GateRejected("fork did not use the requested 1+1 USDT capital")
    if capital.get("gasBudgetUsdt") != 1:
        raise GateRejected("fork did not use the requested 1 USDT gas budget")
    if capital.get("fixtureIsRevenue") is not False:
        raise GateRejected("fixture capital was classified as revenue")

    accounting = report.get("accounting", {})
    gas = report.get("gas", {})
    tvl = report.get("tvl", {})
    price = report.get("price", {})
    supply = report.get("supply", {})

    conditions = {
        "price_increased": price.get("multiple", 0) > 1,
        "supply_contracted": supply.get("changePct", 0) < 0,
        "one_usdt_gas_budget": gas.get("oneUsdtBudgetCovered") is True,
        "external_revenue_positive": accounting.get("externalRevenueUsdt", 0) > 0,
        "organic_tvl_positive": tvl.get("organicExternalChangeUsdt", 0) > 0,
        "hard_nav_after_gas_positive": accounting.get("hardNavDeltaUsdt", 0) > 0,
        "fork_verdict_positive": report.get("strictVerdict") == "PASS_EXTERNAL_VALUE",
    }
    allowed = all(conditions.values())
    return {
        "stage": "POLYGON_MAINNET_GATE",
        "broadcastAllowed": allowed,
        "privateKeyLoaded": False,
        "transactionSigned": False,
        "conditions": conditions,
        "forkMainnetGate": report.get("mainnetGate"),
        "reason": "ALL_STRICT_GATES_PASS" if allowed else "FORK_DID_NOT_PROVE_EXTERNAL_VALUE_AFTER_GAS",
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
    if not decision["broadcastAllowed"]:
        print("MAINNET SKIPPED: no key loaded and no transaction signed")
        return 2
    print("MAINNET PRECONDITIONS PASS: a separate reviewed adapter is still required")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
