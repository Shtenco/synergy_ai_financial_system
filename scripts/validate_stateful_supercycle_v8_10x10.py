"""Independent acceptance validator for restored V8 10x10 evidence."""
from __future__ import annotations

import json
from pathlib import Path

REPORTS = Path("reports")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(f"V8_10X10_FAIL: {message}")


def main() -> None:
    shadow_path = REPORTS / "stateful_supercycle_v8_10x10_shadow.json"
    fork_path = REPORTS / "stateful_supercycle_v8_10x10_polygon_fork.json"
    require(shadow_path.exists(), "missing shadow evidence")
    require(fork_path.exists(), "missing Polygon fork evidence")

    shadow = json.loads(shadow_path.read_text(encoding="utf-8"))
    fork = json.loads(fork_path.read_text(encoding="utf-8"))

    require(shadow.get("pass") is True, "shadow did not pass")
    require(len(shadow.get("internal_edges", [])) == 10, "shadow internal edge count")
    require(len(shadow.get("external_edges", [])) == 10, "shadow external edge count")
    require(shadow.get("internal_transfer_revenue") == 0, "shadow internal revenue")
    require(shadow.get("supply_closed") is True, "shadow temporary supply open")
    require(shadow.get("profit_positive") is True, "shadow profit not positive")
    require(shadow.get("k_non_decreasing") is True, "shadow k decreased")

    require(fork.get("pass") is True, "fork test did not pass")
    require(fork.get("realPolygonContracts") is True, "not a real Polygon contract fork")
    require(fork.get("internalPermissionedPools") == 10, "fork internal edge count")
    require(fork.get("externalQuickSwapPools") == 10, "fork external edge count")
    require(len(set(map(str.lower, fork.get("internalPoolAddresses", [])))) == 10, "duplicate internal pools")
    external_addresses = [item["pool"].lower() for item in fork.get("externalPoolMetadata", [])]
    require(len(set(external_addresses)) == 10, "duplicate external pools")
    require(fork.get("successfulCycles", 0) >= 3, "insufficient stateful successful cycles")
    require(fork.get("internalTransferRevenue") == 0, "fork internal revenue")
    require(fork.get("syntheticSupplyRestored") is True, "synthetic supply not restored")
    require(fork.get("temporarySupplyClosed") is True, "temporary supply not closed")
    require(fork.get("mainPoolLiquidRestored") is True, "main LP liquid reserve not restored")
    require(fork.get("mainPoolSyntheticRestored") is True, "main LP synthetic reserve not restored")
    require(fork.get("mainPoolKNonDecreasing") is True, "main LP k decreased")
    require(fork.get("otherProtocolAssetsPreserved") is True, "other protocol assets changed")
    require(fork.get("profitAfterGasPositive") is True, "profit does not cover gas")
    require(float(fork.get("consolidatedUsdtGain", 0)) > 0, "consolidated USDT did not grow")
    require(float(fork.get("independentExternalShockUsdt", 0)) > 0, "no independent order flow")

    cycles = fork.get("cycles", [])
    require(len(cycles) == fork["successfulCycles"], "cycle row count mismatch")
    for row in cycles:
        require(row["externalUsdt"] > row["buybackUsdt"], f"cycle {row['cycle']} buyback uncovered")
        require(row["treasuryProfitUsdt"] > row["gasUsdt"], f"cycle {row['cycle']} gas not covered")
        require(int(row["kAfter"]) >= int(row["kBefore"]), f"cycle {row['cycle']} k decreased")

    verdict = {
        "verdict": "PASS",
        "shadow_cycles": shadow["cycles"],
        "shadow_accepted_cycles": shadow["state"]["accepted_cycles"],
        "fork_successful_cycles": fork["successfulCycles"],
        "internal_edges": fork["internalPermissionedPools"],
        "external_edges": fork["externalQuickSwapPools"],
        "consolidated_usdt_gain": fork["consolidatedUsdtGain"],
        "cumulative_treasury_profit_usdt": fork["cumulativeTreasuryProfitUsdt"],
        "cumulative_gas_usdt": fork["cumulativeGasUsdtAt274Gwei"],
        "source_of_external_edge": "independent Polygon fork order flow",
    }
    (REPORTS / "stateful_supercycle_v8_10x10_validator.json").write_text(
        json.dumps(verdict, indent=2), encoding="utf-8"
    )
    print(json.dumps(verdict, indent=2))


if __name__ == "__main__":
    main()
