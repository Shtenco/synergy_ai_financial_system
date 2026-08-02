#!/usr/bin/env python3
"""Fail-closed validator for the V14 strict stateful managed-gradient run."""
from __future__ import annotations

import json
import math
from pathlib import Path

REPORTS = Path("reports")
SOURCE = REPORTS / "managed_gradient_v14_stateful.json"
OUTPUT = REPORTS / "managed_gradient_v14_stateful_verdict.json"


def finite(value: object) -> bool:
    return isinstance(value, (int, float)) and math.isfinite(float(value))


def close(left: object, right: object, tolerance: float = 1e-8) -> bool:
    return finite(left) and finite(right) and abs(float(left) - float(right)) <= tolerance


def main() -> None:
    if not SOURCE.exists():
        raise SystemExit(f"missing {SOURCE}")

    data = json.loads(SOURCE.read_text(encoding="utf-8"))
    blocks = data.get("blocks", [])
    summary = data.get("summary", {})
    state_model = data.get("stateModel", {})
    topology = data.get("internalTopology", {})
    initial = data.get("initialState", {})
    final = data.get("finalState", {})
    accepted_rows = [row for row in blocks if row.get("accepted")]

    expected_pools = {
        f"{synthetic}/{liquid}"
        for synthetic in ("SYNA", "SYNR")
        for liquid in ("WPOL", "USDT", "USDC", "DAI", "WETH")
    }

    all_consumed: list[str] = []
    accepted_records: list[dict] = []
    for row in accepted_rows:
        record = row.get("bestAccepted")
        if isinstance(record, dict):
            accepted_records.append(record)
            all_consumed.extend(record.get("externalPoolsConsumed", []))

    cumulative = 0.0
    cumulative_rows_ok = True
    for row in blocks:
        delta = float(row.get("realizedDeltaUsd", 0) or 0)
        cumulative += delta
        if not close(row.get("cumulativeRealizedNavUsd"), cumulative, 2e-6):
            cumulative_rows_ok = False
            break

    initial_pool_map = {
        row.get("pair"): row for row in initial.get("internalPools", []) if isinstance(row, dict)
    }
    final_pool_map = {
        row.get("pair"): row for row in final.get("internalPools", []) if isinstance(row, dict)
    }

    accepted_invariants = all(
        record.get("forwardAndRestoreRoutesDisjoint") is True
        and record.get("noPreviouslyConsumedExternalPool") is True
        and record.get("syntheticTotalsPreserved") is True
        and record.get("managedGradientSupplyDelta") == 0
        and record.get("temporaryQeSupplyAfter") == 0
        and record.get("destinationRecycleSupplyAfter") == 0
        and finite(record.get("walletAfterBuybackDestination"))
        and float(record["walletAfterBuybackDestination"]) >= 0
        and close(
            record.get("sourceLiquidReserveBefore"),
            record.get("sourceLiquidReserveAfter"),
            1e-9,
        )
        and close(
            record.get("destinationLiquidReserveBefore"),
            record.get("destinationLiquidReserveAfter"),
            1e-9,
        )
        and finite(record.get("sourceKRatio"))
        and float(record["sourceKRatio"]) >= 1 - 1e-12
        and finite(record.get("destinationKRatio"))
        and float(record["destinationKRatio"]) >= 1 - 1e-12
        and finite(record.get("walletSurplusDestination"))
        and float(record["walletSurplusDestination"]) >= 0
        and finite(record.get("restorationOutputSource"))
        and finite(record.get("extractedSource"))
        and float(record["restorationOutputSource"]) + 1e-12
        >= float(record["extractedSource"])
        and close(
            record.get("exactBuybackDestination"),
            record.get("recycledBuybackDestination"),
            1e-9,
        )
        and finite(record.get("realizedNavDeltaUsd"))
        and float(record["realizedNavDeltaUsd"])
        >= float(data.get("assumptions", {}).get("minimumRealizedProfitUsd", 0))
        and finite(record.get("accountingIdentityErrorUsd"))
        and abs(float(record["accountingIdentityErrorUsd"])) <= 2e-5
        for record in accepted_records
    )

    pool_amounts_carried_and_restored = (
        set(initial_pool_map) == expected_pools
        and set(final_pool_map) == expected_pools
        and all(
            close(
                initial_pool_map[pair].get("liquidReserve"),
                final_pool_map[pair].get("liquidReserve"),
                1e-9,
            )
            for pair in expected_pools
        )
    )

    checks = {
        "polygon_chain": data.get("chainId") == 137,
        "exactly_100_consecutive_blocks": (
            data.get("blockCount") == 100
            and len(blocks) == 100
            and all(blocks[i].get("block", -1) + 1 == blocks[i + 1].get("block") for i in range(99))
        ),
        "exact_ten_internal_pool_topology": (
            topology.get("poolCount") == 10
            and set(topology.get("pools", [])) == expected_pools
        ),
        "exactly_50_external_pools": (
            data.get("selectedExternalPools") == 50
            and len(data.get("selectedPools", [])) == 50
        ),
        "internal_pools_carried_across_blocks": state_model.get("internalPoolsCarriedAcrossBlocks") is True,
        "treasury_carried_across_blocks": state_model.get("treasuryCarriedAcrossBlocks") is True,
        "source_restoration_uses_exact_reverse_quote": state_model.get(
            "sourcePoolRestoredByExactExternalReverseQuote"
        ) is True,
        "destination_buyback_recycled": state_model.get(
            "destinationBuybackValueRecycledByManagedSyntheticSwap"
        ) is True,
        "destination_pool_restored": state_model.get(
            "destinationPoolRestoredAfterEveryAcceptedCycle"
        ) is True,
        "external_pool_single_use_lock": state_model.get("externalPoolSingleUseLock") is True,
        "summary_cycle_count_matches_rows": summary.get("acceptedStatefulCycles") == len(accepted_rows),
        "accepted_rows_have_records": len(accepted_records) == len(accepted_rows),
        "accepted_cycle_invariants": accepted_invariants,
        "no_external_pool_reused": len(all_consumed) == len(set(all_consumed)),
        "summary_external_pool_count_matches": summary.get("externalPoolsConsumed") == len(set(all_consumed)),
        "cumulative_rows_are_sequential": cumulative_rows_ok,
        "summary_realized_nav_matches_rows": close(
            summary.get("cumulativeRealizedNavUsd"), cumulative, 2e-6
        ),
        "initial_and_final_synthetic_totals_match": initial.get("syntheticTotals") == final.get(
            "syntheticTotals"
        ),
        "all_internal_liquid_amounts_restored": pool_amounts_carried_and_restored,
        "no_independent_snapshot_profit_field": "totalBestConsolidatedProfitAfterGasUsd" not in summary,
        "limitation_declares_exogenous_external_states": (
            "historical exogenous snapshots" in str(data.get("limitation", "")).lower()
            and "locked after its first accepted use" in str(data.get("limitation", "")).lower()
        ),
    }

    verdict = "PASS" if all(checks.values()) else "FAIL"
    edge_status = (
        "STRICT_STATEFUL_REALIZED_EDGE_FOUND"
        if accepted_rows and cumulative > 0
        else "NO_STRICT_STATEFUL_REALIZED_EDGE_IN_RANGE"
    )
    result = {
        "verdict": verdict,
        "edge_status": edge_status,
        "checks": checks,
        "start_block": data.get("startBlock"),
        "end_block": data.get("endBlock"),
        "accepted_stateful_cycles": len(accepted_rows),
        "cumulative_realized_nav_usd": cumulative,
        "external_pools_consumed": len(set(all_consumed)),
        "evaluated_internal_configurations": summary.get("evaluatedInternalConfigurations", 0),
        "evaluated_route_pairs": summary.get("evaluatedRoutePairs", 0),
        "positive_screened_candidates": summary.get("positiveScreenedCandidates", 0),
        "exact_attempts": summary.get("exactAttempts", 0),
        "interpretation": (
            "PASS validates sequential internal state, exact external source restoration, "
            "atomic buyback funding, destination buyback-value recycling, zero-net synthetic "
            "supply, unique external pool use and realized NAV accounting. Edge status is "
            "independent of validator PASS."
        ),
    }
    OUTPUT.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))
    if verdict != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
