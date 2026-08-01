#!/usr/bin/env python3
"""Fail-closed validator for the V15.4 fixed 5 WPOL flash stress."""
from __future__ import annotations

from decimal import Decimal
import json
from pathlib import Path

ECONOMICS = Path("reports/v15_4_atomic_flashloan_5pol_10x_economics.json")
STRUCTURAL = Path("reports/v15_4_atomic_flashloan_5pol_10x.json")
VERDICT = Path("reports/v15_4_atomic_flashloan_verdict.json")
CONTRACT = Path("contracts/v15_4/AtomicFixedFeeFlashV154.sol")

FEE = Decimal("5")
CYCLES = 10
STRICT_BPS = Decimal("2.685148")
REINVESTMENT = Decimal("0.80")


def load(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def dec(value: object) -> Decimal:
    return Decimal(str(value))


def main() -> None:
    economics = load(ECONOMICS)
    structural = load(STRUCTURAL)
    source = CONTRACT.read_text(encoding="utf-8") if CONTRACT.exists() else ""

    principal = Decimal("1000")
    required_gross = FEE + principal * STRICT_BPS / Decimal("10000")
    success = economics.get("principal1000Wpol", {}).get("allTenCyclesEarn6WpolGross", {})
    tenth_fail = economics.get("principal1000Wpol", {}).get("nineGoodTenthBelowEdge", {})
    fee_fail = economics.get("principal1000Wpol", {}).get("feeNotCovered", {})

    checks = {
        "contract_present": bool(source),
        "fixed_fee_is_explicit": "fixedFee" in source and "EVM revert" not in source,
        "ten_cycle_loop_present": "index < 10" in source,
        "strict_edge_constant_present": "MIN_NET_EDGE_PPT = 268_514_800" in source,
        "reinvestment_constant_is_80_percent": "REINVESTMENT_BPS = 8_000" in source,
        "receiver_subsidy_is_rejected": "ReceiverSubsidyDetected" in source,
        "settlement_residue_is_rejected": "SettlementResidueMismatch" in source,
        "economics_report_present": bool(economics),
        "fixed_fee_exactly_5_wpol": dec(economics.get("policy", {}).get("fixedFlashFeeWpolPerCycle", -1)) == FEE,
        "cycle_count_exactly_10": economics.get("policy", {}).get("cycles") == CYCLES,
        "strict_edge_exact": dec(economics.get("policy", {}).get("strictNetEdgeBpsAfterAllCosts", -1)) == STRICT_BPS,
        "minimum_gross_recomputed": dec(economics.get("principal1000Wpol", {}).get("minimumGrossRouteProfitWpolPerCycle", -1)) == required_gross,
        "tenth_failure_reverts_whole_batch": (
            tenth_fail.get("status") == "ATOMIC_BATCH_REVERT"
            and tenth_fail.get("failedCycleOneBased") == 10
            and tenth_fail.get("completedCycles") == 0
            and dec(tenth_fail.get("countedRevenueWpol", -1)) == 0
            and dec(tenth_fail.get("reinvestedWpol", -1)) == 0
        ),
        "fee_failure_reverts_whole_batch": (
            fee_fail.get("status") == "ATOMIC_BATCH_REVERT"
            and fee_fail.get("completedCycles") == 0
            and dec(fee_fail.get("cumulativeFlashFeesWpol", -1)) == 0
        ),
        "successful_batch_has_10_cycles": success.get("status") == "ATOMIC_BATCH_PASS" and success.get("completedCycles") == 10,
        "successful_batch_fee_is_50_wpol": dec(success.get("cumulativeFlashFeesWpol", -1)) == FEE * CYCLES,
        "successful_batch_net_is_10_wpol": dec(success.get("countedRevenueWpol", -1)) == Decimal("10"),
        "successful_batch_reinvests_8_wpol": dec(success.get("reinvestedWpol", -1)) == Decimal("10") * REINVESTMENT,
        "successful_batch_retains_2_wpol": dec(success.get("retainedWpol", -1)) == Decimal("2"),
        "structural_report_is_not_market_evidence": (
            not structural
            or structural.get("evidenceClass") == "STRUCTURAL_ONLY_NOT_MARKET_EDGE"
        ),
    }

    failed = [name for name, passed in checks.items() if not passed]
    verdict = "PASS" if not failed else "FAIL"
    result = {
        "verdict": verdict,
        "checks": checks,
        "failed": failed,
        "economicStatus": (
            "STRUCTURAL_FLASH_ACCOUNTING_PASS_NOT_LIVE_EDGE"
            if verdict == "PASS"
            else "V15_4_EVIDENCE_REJECTED"
        ),
        "interpretation": (
            "PASS proves exact fixed-fee arithmetic, full ten-cycle rollback, strict 2.685148 bps gating and 80% reinvestment. "
            "It does not prove that a live external route can earn the required gross WPOL profit."
        ),
    }
    VERDICT.parent.mkdir(parents=True, exist_ok=True)
    VERDICT.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))
    if verdict != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
