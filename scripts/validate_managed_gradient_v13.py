#!/usr/bin/env python3
"""Fail-closed validator for the V13 managed QE/QT reserve-gradient scan."""
from __future__ import annotations

import json
import math
from pathlib import Path

REPORTS = Path("reports")
SOURCE = REPORTS / "managed_gradient_v13_scan.json"
OUTPUT = REPORTS / "managed_gradient_v13_verdict.json"


def finite(value: object) -> bool:
    return isinstance(value, (int, float)) and math.isfinite(float(value))


def main() -> None:
    if not SOURCE.exists():
        raise SystemExit(f"missing {SOURCE}")
    data = json.loads(SOURCE.read_text(encoding="utf-8"))
    blocks = data.get("blocks", [])
    topology = data.get("internalTopology", {})
    summary = data.get("summary", {})
    assumptions = data.get("assumptions", {})

    accepted_rows = [row for row in blocks if row.get("accepted")]
    wallet_rows = [
        row for row in blocks
        if isinstance(row.get("bestWallet"), dict)
        and row["bestWallet"].get("walletProfitUsd", 0)
        >= assumptions.get("minimumWalletProfitUsd", 0)
    ]
    exact_records = []
    for row in blocks:
        for key in ("bestWallet", "bestAccepted"):
            record = row.get(key)
            if isinstance(record, dict):
                exact_records.append(record)

    pools = topology.get("pools", [])
    expected_pools = {
        f"{synthetic}/{liquid}"
        for synthetic in ("SYNA", "SYNR")
        for liquid in ("WPOL", "USDT", "USDC", "DAI", "WETH")
    }
    min_consolidated = assumptions.get("minimumConsolidatedProfitAfterGasUsd", 0)

    checks = {
        "chain_id_polygon": data.get("chainId") == 137,
        "exactly_100_real_blocks": data.get("blockCount") == 100 and len(blocks) == 100,
        "consecutive_blocks": (
            len(blocks) == 100
            and all(blocks[i]["block"] + 1 == blocks[i + 1]["block"] for i in range(99))
        ),
        "exactly_50_external_pools": (
            data.get("selectedExternalPools") == 50
            and len(data.get("selectedPools", [])) == 50
        ),
        "exact_ten_internal_pool_topology": (
            topology.get("poolCount") == 10
            and len(pools) == 10
            and set(pools) == expected_pools
        ),
        "two_managed_synthetics": topology.get("synthetics") == ["SYNA", "SYNR"],
        "five_liquid_currencies": topology.get("liquidCurrencies") == [
            "WPOL", "USDT", "USDC", "DAI", "WETH"
        ],
        "managed_burn_mint_sync_declared": all(
            token in topology.get("mechanism", "")
            for token in ("burn synthetic reserve", "mint equal synthetic reserve", "sync")
        ),
        "all_blocks_read_external_states": all(
            row.get("externalPoolStatesRead", 0) >= 40 for row in blocks
        ),
        "all_blocks_use_ten_internal_pools": all(
            row.get("internalPoolCount") == 10 for row in blocks
        ),
        "all_blocks_enumerated_external_paths": all(
            row.get("externalPathCount", 0) > 0 for row in blocks
        ),
        "all_blocks_evaluated_internal_configurations": all(
            row.get("evaluatedInternalConfigurations", 0) > 0 for row in blocks
        ),
        "all_blocks_evaluated_path_configurations": all(
            row.get("evaluatedPathConfigurations", 0) > 0 for row in blocks
        ),
        "internal_fee_not_double_counted": "not deducted a second time" in assumptions.get(
            "internalFeeTreatment", ""
        ),
        "no_flash_premium_assumed": assumptions.get("flashPremiumBps") == 0,
        "summary_accepted_matches_rows": (
            summary.get("acceptedConsolidatedProfitBlocks") == len(accepted_rows)
        ),
        "summary_wallet_matches_rows": summary.get("walletPositiveBlocks") == len(wallet_rows),
        "accepted_rows_are_actually_profitable": all(
            row["bestAccepted"].get("walletCloses") is True
            and row["bestAccepted"].get("temporarySupplyAfter") == 0
            and row["bestAccepted"].get("syntheticSupplyDelta") == 0
            and row["bestAccepted"].get("targetGradientRestored") is True
            and row["bestAccepted"].get("consolidatedAfterGasUsd", float("-inf"))
            >= min_consolidated
            for row in accepted_rows
        ),
        "exact_records_close_accounting_identity": all(
            finite(record.get("accountingIdentityErrorUsd"))
            and abs(float(record["accountingIdentityErrorUsd"])) <= 1e-6
            for record in exact_records
        ),
        "exact_records_preserve_supply": all(
            record.get("temporarySupplyAfter") == 0
            and record.get("syntheticSupplyDelta") == 0
            and record.get("targetGradientRestored") is True
            for record in exact_records
        ),
        "source_and_destination_lp_deltas_exposed": all(
            finite(record.get("sourceLpDeltaUsd"))
            and finite(record.get("destinationLpDeltaUsd"))
            and finite(record.get("treasuryDeltaUsd"))
            for record in exact_records
        ),
        "all_positive_consolidated_upper_bounds_exactly_attempted": all(
            row.get("positiveConsolidatedUpperBounds", 0)
            <= row.get("exactQuotes", 0) + row.get("exactFailures", 0)
            for row in blocks
        ),
        "scanner_does_not_require_external_shock": "shock" not in json.dumps(
            data.get("assumptions", {})
        ).lower(),
    }

    verdict = "PASS" if all(checks.values()) else "FAIL"
    edge_status = (
        "CONSOLIDATED_MANAGED_GRADIENT_EDGE_FOUND"
        if accepted_rows
        else "WALLET_EDGE_ONLY_NO_CONSOLIDATED_GAIN"
        if wallet_rows
        else "NO_MANAGED_GRADIENT_WALLET_EDGE_IN_RANGE"
    )
    result = {
        "verdict": verdict,
        "edge_status": edge_status,
        "checks": checks,
        "start_block": data.get("startBlock"),
        "end_block": data.get("endBlock"),
        "internal_pools": topology.get("poolCount"),
        "external_pools": data.get("selectedExternalPools"),
        "accepted_consolidated_profit_blocks": len(accepted_rows),
        "wallet_positive_blocks": len(wallet_rows),
        "total_best_consolidated_profit_after_gas_usd": summary.get(
            "totalBestConsolidatedProfitAfterGasUsd", 0
        ),
        "total_best_wallet_profit_usd": summary.get("totalBestWalletProfitUsd", 0),
        "maximum_best_wallet_profit_usd": summary.get("maximumBestWalletProfitUsd", 0),
        "maximum_accepted_consolidated_profit_after_gas_usd": summary.get(
            "maximumAcceptedConsolidatedProfitAfterGasUsd", 0
        ),
        "evaluated_path_configurations": summary.get(
            "totalEvaluatedPathConfigurations", 0
        ),
        "exact_quotes": summary.get("totalExactQuotes", 0),
        "interpretation": (
            "Wallet profit and consolidated protocol NAV are intentionally separate. "
            "The managed synthetic burn/mint gradient may close the executor wallet while "
            "source and destination protocol-owned LP changes are still included in NAV."
        ),
    }
    OUTPUT.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))
    if verdict != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
