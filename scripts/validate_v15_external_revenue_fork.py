#!/usr/bin/env python3
"""Fail-closed validator for the V15 pinned-Polygon external revenue proof."""
from __future__ import annotations

import json
import math
from pathlib import Path

REPORT = Path("reports/v15_external_revenue_fork.json")
VERDICT = Path("reports/v15_external_revenue_fork_verdict.json")


def finite(value: object) -> bool:
    return isinstance(value, (int, float)) and math.isfinite(float(value))


def main() -> None:
    if not REPORT.exists():
        raise SystemExit(f"missing {REPORT}")
    data = json.loads(REPORT.read_text(encoding="utf-8"))
    req = data.get("v14ClosureRequirement", {})
    md = data.get("multiDex", {})
    private = data.get("privateExecution", {})
    backrun = data.get("intrablockBackrun", {})
    rfq = data.get("signedRfq", {})
    auction = data.get("solverAuction", {})
    accounting = data.get("accounting", {})

    total = accounting.get("totalExternalRevenueAfterGasUsdt")
    required = req.get("requiredExternalRevenueUsdt")
    coverage_bps = accounting.get("coverageBps")
    required_bps = req.get("requiredBps")

    checks = {
        "polygon_chain": data.get("chainId") == 137,
        "pinned_fork_block": isinstance(data.get("forkBlock"), int) and data["forkBlock"] > 0,
        "two_real_dex_families": (
            md.get("dexes") == ["QuickSwap V2", "SushiSwap V2"]
            and isinstance(md.get("quickPair"), str)
            and isinstance(md.get("sushiPair"), str)
            and md.get("quickPair", "").lower() != md.get("sushiPair", "").lower()
        ),
        "victim_and_backrun_same_block": (
            private.get("automineDisabled") is True
            and private.get("sameBlockOrderedBundle") is True
            and private.get("victimBlock") == private.get("backrunBuyBlock") == private.get("backrunSellBlock")
        ),
        "backrun_positive_after_gas": finite(backrun.get("netProfitUsdt")) and float(backrun["netProfitUsdt"]) > 0,
        "rfq_signature_verified": rfq.get("signatureVerifiedOnchain") is True,
        "rfq_positive_after_gas": finite(rfq.get("netProfitUsdt")) and float(rfq["netProfitUsdt"]) > 0,
        "three_solver_bids": isinstance(auction.get("bidsUsdt"), list) and len(auction["bidsUsdt"]) == 3,
        "solver_revenue_positive_after_gas": finite(auction.get("netRevenueUsdt")) and float(auction["netRevenueUsdt"]) > 0,
        "no_internal_synthetic_profit": accounting.get("internalSyntheticSupplyDelta") == 0,
        "v14_gap_covered": (
            accounting.get("v14GapCovered") is True
            and finite(total)
            and finite(required)
            and float(total) > float(required)
        ),
        "required_bps_covered": (
            finite(coverage_bps)
            and finite(required_bps)
            and float(coverage_bps) > float(required_bps)
        ),
        "component_identity": (
            finite(accounting.get("backrunNetUsdt"))
            and finite(accounting.get("rfqNetUsdt"))
            and finite(accounting.get("solverNetUsdt"))
            and finite(total)
            and abs(
                float(accounting["backrunNetUsdt"])
                + float(accounting["rfqNetUsdt"])
                + float(accounting["solverNetUsdt"])
                - float(total)
            ) <= 2e-6
        ),
        "limitations_are_explicit": (
            "fork-local exogenous counterparties" in str(data.get("limitation", ""))
            and "not guaranteed live quote availability" in str(data.get("limitation", ""))
        ),
        "test_verdict_pass": data.get("verdict") == "PASS",
    }

    verdict = "PASS" if all(checks.values()) else "FAIL"
    result = {
        "verdict": verdict,
        "checks": checks,
        "fork_block": data.get("forkBlock"),
        "required_external_revenue_usdt": required,
        "total_external_revenue_after_gas_usdt": total,
        "coverage_bps": coverage_bps,
        "coverage_multiple": accounting.get("coverageMultiple"),
        "interpretation": (
            "PASS proves that the fork-executed V15 external revenue components cover the recorded V14 closure gap after operational gas. "
            "It does not prove live private-relay inclusion or future RFQ/solver quote availability."
        ),
    }
    VERDICT.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))
    if verdict != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
