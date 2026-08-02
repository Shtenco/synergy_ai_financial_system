#!/usr/bin/env python3
"""Audit whether V13 independent block snapshots prove a stateful 100-cycle run.

V13 intentionally evaluates each historical block against the same synthetic
internal starting balances. This audit prevents the sum of those independent
best rows from being presented as executable cumulative protocol profit.
"""
from __future__ import annotations

import json
import math
from collections import defaultdict
from pathlib import Path

REPORTS = Path("reports")
SOURCE = REPORTS / "managed_gradient_v13_scan.json"
OUTPUT = REPORTS / "managed_gradient_v13_statefulness.json"


def finite_number(value: object) -> bool:
    return isinstance(value, (int, float)) and math.isfinite(float(value))


def main() -> None:
    if not SOURCE.exists():
        raise SystemExit(f"missing {SOURCE}")

    data = json.loads(SOURCE.read_text(encoding="utf-8"))
    assumptions = data.get("assumptions", {})
    summary = data.get("summary", {})
    blocks = data.get("blocks", [])
    limitation = str(data.get("limitation", ""))
    nominal_depth = float(assumptions.get("internalLiquidDepthUsdPerPool", 0) or 0)

    accepted = [
        row["bestAccepted"]
        for row in blocks
        if row.get("accepted") and isinstance(row.get("bestAccepted"), dict)
    ]

    source_withdrawals: dict[str, float] = defaultdict(float)
    destination_inflows: dict[str, float] = defaultdict(float)
    route_counts: dict[str, int] = defaultdict(int)
    configuration_counts: dict[str, int] = defaultdict(int)

    for record in accepted:
        source_key = f"{record.get('synthetic')}/{record.get('source')}"
        destination_key = f"{record.get('synthetic')}/{record.get('destination')}"
        source_withdrawals[source_key] += float(record.get("sourceValueUsd", 0) or 0)
        destination_inflows[destination_key] += float(record.get("buybackValueUsd", 0) or 0)
        route_counts[str(record.get("route"))] += 1
        configuration_counts[
            f"{record.get('synthetic')}:{record.get('source')}->{record.get('destination')}"
        ] += 1

    summed_rows = sum(float(record.get("consolidatedAfterGasUsd", 0) or 0) for record in accepted)
    reported_total = float(summary.get("totalBestConsolidatedProfitAfterGasUsd", 0) or 0)
    max_source_withdrawal = max(source_withdrawals.values(), default=0.0)
    max_withdrawal_multiple = (
        max_source_withdrawal / nominal_depth if nominal_depth > 0 else math.inf
    )

    reused_fixed_starting_depth = bool(accepted) and all(
        abs(float(record.get("sourceLiquidReserveBeforeUsd", -1)) - nominal_depth) <= 1e-9
        and abs(float(record.get("destinationLiquidReserveBeforeUsd", -1)) - nominal_depth) <= 1e-9
        for record in accepted
    )
    source_reserve_declines = bool(accepted) and all(
        float(record.get("sourceLiquidReserveAfterUsd", 0))
        < float(record.get("sourceLiquidReserveBeforeUsd", 0))
        for record in accepted
    )
    source_final_k_declines = bool(accepted) and all(
        finite_number(record.get("sourceKRatio"))
        and float(record["sourceKRatio"]) < 1.0
        for record in accepted
    )
    limitation_admits_no_state_mutation = (
        "does not mutate all pool states across blocks" in limitation.lower()
    )
    sum_matches_independent_rows = abs(summed_rows - reported_total) <= 1e-6

    checks = {
        "independent_snapshot_quote_scan_completed": len(accepted) == len(blocks) == 100,
        "reported_total_is_sum_of_independent_best_rows": sum_matches_independent_rows,
        "scanner_reuses_fixed_internal_starting_depth": reused_fixed_starting_depth,
        "accepted_rows_reduce_source_liquid_reserve": source_reserve_declines,
        "accepted_rows_leave_source_final_k_below_start": source_final_k_declines,
        "report_explicitly_admits_no_cross_block_pool_mutation": limitation_admits_no_state_mutation,
        "same_pool_withdrawal_exceeds_nominal_depth": max_source_withdrawal > nominal_depth,
    }

    snapshot_verdict = "PASS" if checks["independent_snapshot_quote_scan_completed"] else "FAIL"
    stateful_verdict = "FAIL" if all(checks.values()) else "UNPROVEN"

    result = {
        "snapshot_verdict": snapshot_verdict,
        "stateful_100_cycle_verdict": stateful_verdict,
        "cumulative_profit_claim": "INVALID_AS_STATEFUL_TOTAL",
        "reason": (
            "Each block is an independent historical quote evaluated from the same internal "
            "starting reserves. The accepted rows are not applied sequentially to protocol-owned "
            "LP balances, so their summed profit is not an executable 100-cycle result."
        ),
        "checks": checks,
        "accepted_independent_snapshots": len(accepted),
        "reported_independent_snapshot_profit_sum_usd": reported_total,
        "nominal_internal_liquid_depth_per_pool_usd": nominal_depth,
        "source_withdrawals_if_rows_were_naively_chained_usd": dict(source_withdrawals),
        "destination_inflows_if_rows_were_naively_chained_usd": dict(destination_inflows),
        "maximum_same_pool_withdrawal_multiple_of_starting_depth": max_withdrawal_multiple,
        "configuration_counts": dict(configuration_counts),
        "route_counts": dict(route_counts),
        "required_next_proof": [
            "carry all ten internal liquid reserves from block to block",
            "apply every accepted source-LP, destination-LP and treasury delta before the next block",
            "exact-quote any external rebalance required to restore depleted source assets",
            "reject a cycle unless the post-cycle state remains executable for the next cycle",
            "report realized cumulative NAV rather than the sum of independent best snapshots",
        ],
    }

    OUTPUT.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))

    # This audit is intentionally fail-closed for the stateful claim. It exits
    # successfully so the evidence artifact is still uploaded and reviewable.
    if snapshot_verdict != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
