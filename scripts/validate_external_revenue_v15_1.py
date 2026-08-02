#!/usr/bin/env python3
"""Fail-closed validator for strict V15.1 historical Polygon evidence."""
from __future__ import annotations

import json
import re
from pathlib import Path

DISCOVERY = Path("reports/v15_1_historical_victim_discovery.json")
REPORT = Path("reports/v15_1_historical_polygon_fork.json")
VERDICT = Path("reports/v15_1_strict_verdict.json")
WORKFLOW = Path(".github/workflows/stateful-supercycle-v8.yml")
CONTRACT_ROOT = Path("contracts/v15_1")

MIN_EDGE_PPM = 269
V14_REQUIRED_RAW = 121_799  # 6-decimal USDC


def load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def as_int(value: object, name: str) -> int:
    try:
        result = int(str(value))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid integer {name}: {value!r}") from exc
    if result < 0:
        raise ValueError(f"negative integer {name}: {result}")
    return result


def source_checks() -> dict[str, bool]:
    sources = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted(CONTRACT_ROOT.rglob("*.sol"))
    )
    workflow = WORKFLOW.read_text(encoding="utf-8") if WORKFLOW.exists() else ""
    forbidden_mint_burn = re.search(
        r"\bfunction\s+(?:mint|burn)\b|\.(?:mint|burn)\s*\(",
        sources,
    )
    auction_source = (CONTRACT_ROOT / "SolverAuctionV151.sol").read_text(encoding="utf-8")
    engine_source = (CONTRACT_ROOT / "ExternalRevenueEngineV151.sol").read_text(encoding="utf-8")
    return {
        "v151_contract_sources_present": bool(sources),
        "no_mint_or_burn_surface": forbidden_mint_burn is None,
        "auction_has_no_refund_loop": "for (" not in auction_source and "for(" not in auction_source,
        "auction_uses_pull_refunds": "withdrawRefund" in auction_source and "refunds[" in auction_source,
        "winner_bond_not_direct_revenue": "refunds[winner.solver] += bond" in auction_source,
        "route_hash_binds_epoch": "epoch," in engine_source and "ROUTE_KIND" in engine_source,
        "engine_enforces_adapter_codehash": "allowedAdapterCodehash" in engine_source and ".codehash" in engine_source,
        "engine_has_bounded_route": "MAX_ROUTE_STEPS" in engine_source,
        "ci_does_not_patch_sources": (
            "patch_external_revenue" not in workflow
            and "perl -0pi" not in workflow
            and "sed -i" not in workflow
        ),
    }


def validate_no_edge(discovery: dict, report: dict, checks: dict[str, bool]) -> str:
    selected = discovery.get("selected")
    status = report.get("evidenceStatus")
    if selected is None:
        checks["discovery_has_no_selected_victim"] = discovery.get("candidateCount", 0) == 0
        checks["no_false_historical_pass"] = status not in {"HISTORICAL_EDGE_PASS"}
        return "NO_HISTORICAL_VICTIM_IN_RANGE"

    checks["selected_victim_recorded"] = bool(selected.get("transactionHash"))
    checks["historical_report_present"] = bool(report)
    checks["no_edge_status_is_explicit"] = status in {
        "NO_HISTORICAL_EDGE_PROVEN_IN_SELECTED_TRANSACTION",
        "HISTORICAL_EXECUTION_BUT_NET_GATE_FAILED",
    }
    checks["strict_counted_revenue_is_zero_when_not_proven"] = (
        str(report.get("strictCountedRevenueRaw", "0")) == "0"
        if status == "NO_HISTORICAL_EDGE_PROVEN_IN_SELECTED_TRANSACTION"
        else True
    )
    return status or "MISSING_HISTORICAL_REPORT"


def validate_historical_pass(discovery: dict, report: dict, checks: dict[str, bool]) -> str:
    selected = discovery.get("selected") or {}
    victim = report.get("historicalVictim", {})
    auction = report.get("auction", {})
    accounting = report.get("rawAccounting", {})
    fixture = report.get("fixtureFunding", {})
    invariants = report.get("invariants", {})

    principal = as_int(accounting.get("principalUsdcRaw"), "principal")
    gross_reported = as_int(accounting.get("grossProfitUsdcRaw"), "gross profit")
    treasury = as_int(accounting.get("treasuryRevenueUsdcRaw"), "treasury revenue")
    solver = as_int(accounting.get("solverRevenueUsdcRaw"), "solver revenue")
    gas = as_int(accounting.get("operationalGasUsdcRaw"), "operational gas")
    aggregate_net_reported = as_int(
        accounting.get("aggregateNetAfterGasUsdcRaw"),
        "aggregate net",
    )
    solver_gas = as_int(accounting.get("solverGasUsdcRaw"), "solver gas")
    solver_net_reported = as_int(
        accounting.get("solverNetAfterGasUsdcRaw"),
        "solver net",
    )
    required = as_int(
        accounting.get("v14RequiredTreasuryUsdcRaw"),
        "V14 required revenue",
    )

    gross_computed = treasury + solver
    aggregate_net_computed = max(gross_computed - gas, 0)
    solver_net_computed = max(solver - solver_gas, 0)
    edge_ppm_computed = gross_computed * 1_000_000 // principal if principal else 0

    checks.update({
        "discovery_matches_replayed_transaction": (
            selected.get("transactionHash") == victim.get("transactionHash")
            and selected.get("blockNumber") == victim.get("originalBlockNumber")
        ),
        "fork_is_immediately_before_victim": (
            report.get("forkBlock") == victim.get("originalBlockNumber", 0) - 1
        ),
        "same_block_ordering": (
            victim.get("sameBlock") is True
            and victim.get("victimBeforeBackrun") is True
            and int(victim.get("replayTransactionIndex", -1))
            < int(victim.get("backrunTransactionIndex", -1))
        ),
        "real_multidex_route": (
            report.get("venues", {}).get("distinctDexFamilies") is True
            and bool(report.get("venues", {}).get("uniswapV3Pool"))
            and bool(report.get("venues", {}).get("quickswapV2Pair"))
        ),
        "gross_profit_recomputed": gross_reported == gross_computed,
        "aggregate_net_recomputed": aggregate_net_reported == aggregate_net_computed,
        "solver_net_recomputed": solver_net_reported == solver_net_computed,
        "edge_ppm_recomputed": int(accounting.get("realizedEdgePpm", -1)) == edge_ppm_computed,
        "edge_clears_269_ppm": edge_ppm_computed >= MIN_EDGE_PPM,
        "treasury_share_covers_v14_gap": treasury >= required >= V14_REQUIRED_RAW,
        "aggregate_net_covers_v14_gap": aggregate_net_computed >= required,
        "winning_solver_is_rational_after_gas": solver_net_computed > 0,
        "fixture_capital_excluded": fixture.get("countedAsRevenue") is False,
        "solver_bond_excluded": (
            auction.get("bondCountedAsRevenue") is False
            and invariants.get("solverBondCountedAsRevenue") is False
        ),
        "simulated_rfq_excluded": invariants.get("simulatedRfqRevenueCounted") is False,
        "solution_single_use": auction.get("solutionConsumed") is True,
        "supply_unchanged": (
            invariants.get("usdcTotalSupplyBefore")
            == invariants.get("usdcTotalSupplyAfter")
        ),
        "engine_has_no_settlement_residue": as_int(
            invariants.get("engineSettlementBalanceAfter"),
            "engine settlement balance",
        ) == 0,
        "no_synthetic_mint_burn": invariants.get("syntheticMintBurnInterfaceUsed") is False,
    })

    computed_pass = all(
        checks[name]
        for name in (
            "discovery_matches_replayed_transaction",
            "fork_is_immediately_before_victim",
            "same_block_ordering",
            "real_multidex_route",
            "gross_profit_recomputed",
            "aggregate_net_recomputed",
            "solver_net_recomputed",
            "edge_ppm_recomputed",
            "edge_clears_269_ppm",
            "treasury_share_covers_v14_gap",
            "aggregate_net_covers_v14_gap",
            "winning_solver_is_rational_after_gas",
            "fixture_capital_excluded",
            "solver_bond_excluded",
            "simulated_rfq_excluded",
            "solution_single_use",
            "supply_unchanged",
            "engine_has_no_settlement_residue",
            "no_synthetic_mint_burn",
        )
    )
    checks["reported_pass_matches_recomputed_pass"] = (
        report.get("evidenceStatus") == "HISTORICAL_EDGE_PASS"
    ) == computed_pass
    return "HISTORICAL_EDGE_PASS" if computed_pass else "HISTORICAL_EVIDENCE_REJECTED"


def main() -> None:
    discovery = load_json(DISCOVERY)
    report = load_json(REPORT)
    checks = source_checks()

    if not discovery:
        checks["discovery_report_present"] = False
        edge_status = "MISSING_DISCOVERY_REPORT"
    else:
        checks["discovery_report_present"] = True
        if report.get("evidenceStatus") == "HISTORICAL_EDGE_PASS":
            edge_status = validate_historical_pass(discovery, report, checks)
        else:
            edge_status = validate_no_edge(discovery, report, checks)

    verdict = "PASS" if all(checks.values()) else "FAIL"
    result = {
        "verdict": verdict,
        "edgeStatus": edge_status,
        "checks": checks,
        "interpretation": (
            "PASS validates the V15.1 evidence pipeline and its fail-closed classification. "
            "Only edgeStatus=HISTORICAL_EDGE_PASS establishes a qualifying historical fork edge. "
            "A NO_HISTORICAL_* status is an honest negative result, not an economic PASS."
        ),
    }
    VERDICT.parent.mkdir(parents=True, exist_ok=True)
    VERDICT.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))
    if verdict != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
