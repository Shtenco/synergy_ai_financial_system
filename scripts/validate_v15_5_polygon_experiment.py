#!/usr/bin/env python3
"""Fail-closed validator for the V15.5 Polygon mainnet micro-experiment."""
from __future__ import annotations

from decimal import Decimal
import json
from pathlib import Path

CONTRACT = Path("contracts/v15_5/MainnetAtomicAddLpExperimentV155.sol")
FORK_REPORT = Path("reports/v15_5_polygon_mainnet_addlp_fork.json")
DEPLOYMENT = Path("reports/v15_5_polygon_mainnet_deployment.json")
PREFLIGHT = Path("reports/v15_5_polygon_mainnet_preflight.json")
PROBE = Path("reports/v15_5_polygon_mainnet_probe_result.json")
VERDICT = Path("reports/v15_5_polygon_experiment_verdict.json")

MAX_RISK_WEI = Decimal(10) * Decimal(10) ** 18


def load(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def dec(value: object, default: str = "-1") -> Decimal:
    try:
        return Decimal(str(value))
    except Exception:
        return Decimal(default)


def main() -> None:
    source = CONTRACT.read_text(encoding="utf-8") if CONTRACT.exists() else ""
    fork = load(FORK_REPORT)
    deployment = load(DEPLOYMENT)
    preflight = load(PREFLIGHT)
    probe = load(PROBE)

    static_checks = {
        "contract_present": bool(source),
        "polygon_chain_gate_present": "block.chainid != 137" in source,
        "aave_simple_flash_present": "flashLoanSimple" in source,
        "seed_and_cycle_addlp_present": source.count("router.addLiquidity(") >= 4,
        "cycle_and_recovery_remove_lp_present": source.count("router.removeLiquidity(") >= 4,
        "reversible_gradient_present": source.count("swapExactTokensForTokens(") >= 4,
        "receiver_subsidy_rejected": "ReceiverSubsidyDetected" in source,
        "pair_damage_rejected": "PairDamage" in source,
        "lp_mismatch_rejected": "LpPositionMismatch" in source,
        "repayment_shortfall_rejected": "RepaymentShortfall" in source,
        "strict_edge_exact": "MIN_NET_EDGE_PPT = 268_514_800" in source,
        "reinvestment_exact": "REINVESTMENT_BPS = 8_000" in source,
        "seed_cap_two_pol": "MAX_NATIVE_SEED_POL = 2 ether" in source,
        "cycle_gas_cap_below_ten_pol": "MAX_CYCLE_GAS_RISK_WEI = 95 ether / 10" in source,
        "tokens_marked_no_value": source.count("NO VALUE") >= 2,
        "no_arbitrary_external_call_plan": "address target" not in source and "bytes callData" not in source,
    }

    fork_checks = {
        "fork_report_present": bool(fork),
        "fork_real_protocol_class": (
            fork.get("evidenceClass")
            == "REAL_PROTOCOL_FORK_ATOMIC_ROLLBACK_NOT_MAINNET_BROADCAST"
        ),
        "fork_chain_polygon": fork.get("chainId") == 137,
        "fork_expected_revert": fork.get("actualOutcome") == "ATOMIC_REVERT",
        "fork_pools_restored": fork.get("poolsRestoredExactly") is True,
        "fork_aave_restored": fork.get("aaveLiquidityRestoredExactly") is True,
        "fork_supply_restored": fork.get("experimentTokenSupplyRestoredExactly") is True,
        "fork_zero_revenue": dec(fork.get("countedRevenueWpol", -1)) == 0,
        "fork_zero_reinvestment": dec(fork.get("reinvestedWpol", -1)) == 0,
    }

    deployment_status = "NOT_DEPLOYED"
    deployment_checks: dict[str, bool] = {}
    if deployment:
        risk = deployment.get("riskBudget") or {}
        deployment_checks = {
            "deployment_chain_polygon": deployment.get("chainId") == 137,
            "deployment_not_profit_evidence": (
                deployment.get("evidenceClass")
                == "LIVE_MAINNET_DEPLOYMENT_NOT_PROFIT_EVIDENCE"
            ),
            "deployment_contract_address_present": bool(
                (deployment.get("deployed") or {}).get("experiment")
            ),
            "deployment_budget_within_ten_pol": (
                dec(risk.get("conservativeCommittedWei")) <= MAX_RISK_WEI
            ),
            "seed_recoverable": (
                (deployment.get("seed") or {}).get("recoverableProtocolOwnedSeed") is True
            ),
        }
        deployment_status = (
            "DEPLOYED_AND_SEEDED" if all(deployment_checks.values())
            else "DEPLOYMENT_REJECTED"
        )

    preflight_status = "NOT_RUN"
    preflight_checks: dict[str, bool] = {}
    if preflight:
        gas = preflight.get("gas") or {}
        preflight_checks = {
            "preflight_chain_polygon": preflight.get("chainId") == 137,
            "preflight_budget_within_ten_pol": (
                dec(gas.get("maximumCombinedRiskWei")) <= MAX_RISK_WEI
            ),
            "preflight_no_receiver_subsidy": (
                dec((preflight.get("stateBefore") or {}).get("experimentWpol", -1)) == 0
            ),
            "preflight_static_expected_revert_or_unexpected_pass": (
                preflight.get("staticResult") in {
                    "EXPECTED_ATOMIC_REVERT_NO_EXTERNAL_SURPLUS",
                    "UNEXPECTED_STATIC_PASS",
                }
            ),
        }
        preflight_status = "PREFLIGHT_ACCEPTED" if all(preflight_checks.values()) else "PREFLIGHT_REJECTED"

    probe_status = "NOT_BROADCAST"
    probe_checks: dict[str, bool] = {}
    if probe:
        gas = probe.get("gas") or {}
        receipt_status = int(probe.get("receiptStatus", -1))
        probe_checks = {
            "probe_chain_polygon": probe.get("chainId") == 137,
            "probe_budget_within_ten_pol": (
                dec(gas.get("maximumCombinedRiskWei")) <= MAX_RISK_WEI
            ),
            "probe_has_transaction_hash": bool(probe.get("transactionHash")),
            "probe_classified_live": (
                probe.get("evidenceClass")
                == "LIVE_POLYGON_MAINNET_ONE_TRANSACTION_PROBE"
            ),
            "reverted_probe_exact_rollback": (
                receipt_status != 0 or probe.get("exactAtomicRollback") is True
            ),
            "reverted_probe_zero_revenue": (
                receipt_status != 0 or dec(probe.get("countedRevenueWpolWei", -1)) == 0
            ),
        }
        if all(probe_checks.values()):
            probe_status = (
                "EXPECTED_REVERT_CONFIRMED_ONLY_GAS_SPENT"
                if receipt_status == 0
                else "UNEXPECTED_SUCCESS_REQUIRES_TRACE_AUDIT"
            )
        else:
            probe_status = "PROBE_EVIDENCE_REJECTED"

    failed_static = [name for name, passed in static_checks.items() if not passed]
    failed_fork = [name for name, passed in fork_checks.items() if not passed]
    failed_deployment = [name for name, passed in deployment_checks.items() if not passed]
    failed_preflight = [name for name, passed in preflight_checks.items() if not passed]
    failed_probe = [name for name, passed in probe_checks.items() if not passed]

    if failed_static or failed_fork:
        verdict = "FAIL"
    elif (
        probe_status == "PROBE_EVIDENCE_REJECTED"
        or deployment_status == "DEPLOYMENT_REJECTED"
        or preflight_status == "PREFLIGHT_REJECTED"
    ):
        verdict = "FAIL"
    elif probe_status == "EXPECTED_REVERT_CONFIRMED_ONLY_GAS_SPENT":
        verdict = "MAINNET_REVERT_PROOF_PASS"
    elif probe_status == "UNEXPECTED_SUCCESS_REQUIRES_TRACE_AUDIT":
        verdict = "HOLD_SUCCESS_NOT_YET_REVENUE"
    elif deployment_status == "DEPLOYED_AND_SEEDED":
        verdict = "DEPLOYED_AWAITING_ONE_CYCLE"
    else:
        verdict = "FORK_READY_NOT_DEPLOYED"

    result = {
        "verdict": verdict,
        "staticChecks": static_checks,
        "forkChecks": fork_checks,
        "deploymentChecks": deployment_checks,
        "preflightChecks": preflight_checks,
        "probeChecks": probe_checks,
        "failed": (
            failed_static + failed_fork + failed_deployment
            + failed_preflight + failed_probe
        ),
        "deploymentStatus": deployment_status,
        "preflightStatus": preflight_status,
        "probeStatus": probe_status,
        "recognizedMainnetRevenueWpol": (
            "0" if probe_status != "UNEXPECTED_SUCCESS_REQUIRES_TRACE_AUDIT"
            else "PENDING_TRACE_AUDIT"
        ),
        "interpretation": (
            "Internal ADDLP, mint, burn and reversible self-swaps are not revenue. "
            "The expected scientific result is an atomic revert with exact pool restoration and gas-only loss. "
            "A successful receipt remains unrecognized until an independent transaction-trace and consolidated-NAV audit passes."
        ),
    }
    VERDICT.parent.mkdir(parents=True, exist_ok=True)
    VERDICT.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))
    if verdict == "FAIL":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
