#!/usr/bin/env python3
"""Fail-closed validator for the V15.4 fixed 5 WPOL flash stress.

The validator deliberately refuses PASS unless both independent evidence paths
exist: deterministic economics and a completed Solidity/Hardhat structural test
report. A missing structural report is therefore a hard failure, not an optional
condition.
"""
from __future__ import annotations

from decimal import Decimal
import hashlib
import json
from pathlib import Path
import re

ECONOMICS = Path("reports/v15_4_atomic_flashloan_5pol_10x_economics.json")
STRUCTURAL = Path("reports/v15_4_atomic_flashloan_5pol_10x.json")
VERDICT = Path("reports/v15_4_atomic_flashloan_verdict.json")
CONTRACT = Path("contracts/v15_4/AtomicFixedFeeFlashV154.sol")
TEST = Path("test/atomic_flashloan_5pol_10x_v15_4.js")

FEE = Decimal("5")
CYCLES = 10
STRICT_BPS = Decimal("2.685148")
REINVESTMENT = Decimal("0.80")
PRINCIPAL = Decimal("1000")
EXPECTED_NET_PER_SUCCESS_CYCLE = Decimal("1")


def load(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def dec(value: object, default: str = "-1") -> Decimal:
    if value is None:
        return Decimal(default)
    try:
        return Decimal(str(value))
    except Exception:
        return Decimal(default)


def sha256(path: Path) -> str:
    if not path.exists():
        return ""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def all_success_rows_are_exact(rows: object) -> bool:
    if not isinstance(rows, list) or len(rows) != CYCLES:
        return False
    for row in rows:
        if not isinstance(row, dict):
            return False
        if row.get("status") != "STRICT_NET_EDGE_PASS":
            return False
        if dec(row.get("flashFeeWpol")) != FEE:
            return False
        if dec(row.get("netProtocolProfitWpol")) != EXPECTED_NET_PER_SUCCESS_CYCLE:
            return False
        if dec(row.get("netEdgeBps")) < STRICT_BPS:
            return False
        if dec(row.get("countedRevenueWpol")) != EXPECTED_NET_PER_SUCCESS_CYCLE:
            return False
    return True


def main() -> None:
    economics = load(ECONOMICS)
    structural = load(STRUCTURAL)
    source = CONTRACT.read_text(encoding="utf-8") if CONTRACT.exists() else ""
    test_source = TEST.read_text(encoding="utf-8") if TEST.exists() else ""

    required_gross = FEE + PRINCIPAL * STRICT_BPS / Decimal("10000")
    required_net = PRINCIPAL * STRICT_BPS / Decimal("10000")
    required_reinvested = required_net * REINVESTMENT
    required_retained = required_net - required_reinvested

    principal_section = economics.get("principal1000Wpol", {})
    success = principal_section.get("allTenCyclesEarn6WpolGross", {})
    tenth_fail = principal_section.get("nineGoodTenthBelowEdge", {})
    fee_fail = principal_section.get("feeNotCovered", {})
    exact_boundary = principal_section.get("exactBoundary", {})

    structural_flags = (
        "atomicRollbackOnTenthFailure",
        "profitableTenCycleBatch",
        "exactBoundaryPass",
        "boundaryMinusOneWeiRevert",
        "receiverSubsidyRejected",
    )

    checks = {
        "contract_present": bool(source),
        "test_present": bool(test_source),
        "fixed_fee_accounting_present": (
            "uint256 public immutable fixedFee" in source
            and "amount + fixedFee" in source
            and "cumulativeFees += fixedFee" in source
        ),
        "ten_cycle_loop_is_exact": bool(
            re.search(r"for\s*\([^;]+;\s*index\s*<\s*10\s*;", source)
        ),
        "strict_edge_constant_is_exact": (
            "MIN_NET_EDGE_PPT = 268_514_800" in source
        ),
        "reinvestment_constant_is_exact": "REINVESTMENT_BPS = 8_000" in source,
        "receiver_subsidy_is_rejected_in_contract": (
            "ReceiverSubsidyDetected" in source
            and "balanceAtCallback != amount" in source
        ),
        "settlement_residue_is_rejected_in_contract": (
            "SettlementResidueMismatch" in source
            and "asset.balanceOf(address(this)) != 0" in source
        ),
        "economics_report_present": bool(economics),
        "structural_report_present": bool(structural),
        "structural_report_is_test_bound": (
            bool(structural)
            and structural.get("contractSha256") == sha256(CONTRACT)
            and structural.get("testSha256") == sha256(TEST)
        ),
        "structural_report_is_not_market_evidence": (
            structural.get("evidenceClass") == "STRUCTURAL_ONLY_NOT_MARKET_EDGE"
        ),
        "all_structural_assertions_completed": (
            structural.get("allAssertionsPassed") is True
            and all(structural.get(flag) is True for flag in structural_flags)
        ),
        "structural_fee_exactly_5_wpol": (
            dec(structural.get("fixedFlashFeeWpolPerCycle")) == FEE
        ),
        "structural_cycle_count_exactly_10": structural.get("cycles") == CYCLES,
        "structural_success_accounting_exact": (
            dec(structural.get("cumulativeGrossRouteProfitWpol")) == Decimal("60")
            and dec(structural.get("cumulativeFlashFeesWpol")) == Decimal("50")
            and dec(structural.get("cumulativeNetProtocolProfitWpol")) == Decimal("10")
            and dec(structural.get("reinvestedWpol")) == Decimal("8")
            and dec(structural.get("retainedWpol")) == Decimal("2")
            and dec(structural.get("settlementResidueWpol")) == Decimal("0")
            and structural.get("lenderPrincipalRestoredEveryCycle") is True
        ),
        "fixed_fee_exactly_5_wpol": (
            dec(economics.get("policy", {}).get("fixedFlashFeeWpolPerCycle")) == FEE
        ),
        "cycle_count_exactly_10": economics.get("policy", {}).get("cycles") == CYCLES,
        "strict_edge_exact": (
            dec(economics.get("policy", {}).get("strictNetEdgeBpsAfterAllCosts"))
            == STRICT_BPS
        ),
        "minimum_gross_recomputed": (
            dec(principal_section.get("minimumGrossRouteProfitWpolPerCycle"))
            == required_gross
        ),
        "exact_boundary_passes": (
            exact_boundary.get("status") == "STRICT_NET_EDGE_PASS"
            and dec(exact_boundary.get("grossRouteProfitWpol")) == required_gross
            and dec(exact_boundary.get("netProtocolProfitWpol")) == required_net
            and dec(exact_boundary.get("netEdgeBps")) == STRICT_BPS
            and dec(exact_boundary.get("countedRevenueWpol")) == required_net
            and dec(exact_boundary.get("reinvestedWpol")) == required_reinvested
            and dec(exact_boundary.get("retainedWpol")) == required_retained
        ),
        "tenth_failure_reverts_whole_batch": (
            tenth_fail.get("status") == "ATOMIC_BATCH_REVERT"
            and tenth_fail.get("failedCycleOneBased") == 10
            and tenth_fail.get("completedCycles") == 0
            and dec(tenth_fail.get("cumulativeFlashFeesWpol")) == 0
            and dec(tenth_fail.get("countedRevenueWpol")) == 0
            and dec(tenth_fail.get("reinvestedWpol")) == 0
            and dec(tenth_fail.get("retainedWpol")) == 0
        ),
        "fee_failure_reverts_whole_batch": (
            fee_fail.get("status") == "ATOMIC_BATCH_REVERT"
            and fee_fail.get("completedCycles") == 0
            and dec(fee_fail.get("cumulativeFlashFeesWpol")) == 0
            and dec(fee_fail.get("countedRevenueWpol")) == 0
        ),
        "successful_batch_has_10_cycles": (
            success.get("status") == "ATOMIC_BATCH_PASS"
            and success.get("completedCycles") == CYCLES
        ),
        "successful_batch_rows_are_exact": all_success_rows_are_exact(success.get("rows")),
        "successful_batch_fee_is_50_wpol": (
            dec(success.get("cumulativeFlashFeesWpol")) == FEE * CYCLES
        ),
        "successful_batch_net_is_10_wpol": (
            dec(success.get("countedRevenueWpol")) == Decimal("10")
        ),
        "successful_batch_reinvests_8_wpol": (
            dec(success.get("reinvestedWpol")) == Decimal("10") * REINVESTMENT
        ),
        "successful_batch_retains_2_wpol": (
            dec(success.get("retainedWpol")) == Decimal("2")
        ),
    }

    failed = [name for name, passed in checks.items() if not passed]
    verdict = "PASS" if not failed else "FAIL"
    result = {
        "verdict": verdict,
        "validationMode": "FAIL_CLOSED_DUAL_EVIDENCE",
        "checks": checks,
        "failed": failed,
        "economicStatus": (
            "STRUCTURAL_FLASH_ACCOUNTING_PASS_NOT_LIVE_EDGE"
            if verdict == "PASS"
            else "V15_4_EVIDENCE_REJECTED"
        ),
        "strictPolicy": {
            "principalWpolPerCycle": str(PRINCIPAL),
            "fixedFeeWpolPerCycle": str(FEE),
            "minimumGrossProfitWpolPerCycle": str(required_gross),
            "minimumNetEdgeBps": str(STRICT_BPS),
            "reinvestmentShare": str(REINVESTMENT),
            "failedBatchRevenueWpol": "0",
        },
        "interpretation": (
            "PASS requires both the deterministic economics report and the completed Solidity structural report, bound to the current contract and test SHA-256 hashes. "
            "It proves exact fixed-fee arithmetic, complete ten-cycle rollback, equality at 2.685148 bps, rejection one wei below the boundary, rejection of receiver subsidy and exact 80% reinvestment. "
            "It does not prove that a live Polygon route can supply the required external gross profit."
        ),
    }
    VERDICT.parent.mkdir(parents=True, exist_ok=True)
    VERDICT.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))
    if verdict != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
