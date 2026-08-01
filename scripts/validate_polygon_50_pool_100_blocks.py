#!/usr/bin/env python3
"""Fail-closed validator for the real Polygon 50-pool / 100-block scan."""
from __future__ import annotations

import json
from pathlib import Path

REPORTS = Path("reports")
SOURCE = REPORTS / "polygon_50_pool_100_block_scan.json"
OUTPUT = REPORTS / "polygon_50_pool_100_block_verdict.json"


def main() -> None:
    if not SOURCE.exists():
        raise SystemExit(f"missing {SOURCE}")
    data = json.loads(SOURCE.read_text(encoding="utf-8"))
    blocks = data.get("blocks", [])
    pools = data.get("selectedPools", [])
    summary = data.get("summary", {})
    profitable_blocks = sum(bool(b.get("accepted")) for b in blocks)
    upper_candidates = sum(int(b.get("upperBoundCandidates", 0)) for b in blocks)
    exact_candidates = sum(int(b.get("exactCandidates", 0)) for b in blocks)

    checks = {
        "chain_id_polygon": data.get("chainId") == 137,
        "exactly_100_real_blocks": data.get("blockCount") == 100 and len(blocks) == 100,
        "consecutive_block_range": (
            len(blocks) == 100
            and all(blocks[i]["block"] + 1 == blocks[i + 1]["block"] for i in range(99))
        ),
        "exactly_50_external_pools": data.get("selectedExternalPools") == 50 and len(pools) == 50,
        "unique_pool_kind_addresses": len({(p["kind"], p["address"].lower()) for p in pools}) == 50,
        "all_blocks_read_pool_state": all(b.get("poolStatesRead", 0) >= 40 for b in blocks),
        "all_blocks_enumerated_cycles": all(b.get("eligibleCycles", 0) > 0 for b in blocks),
        "real_price_methodology_declared": "Real QuickSwap" in data.get("methodology", {}).get("poolPrices", ""),
        "upper_bound_methodology_declared": "upper-bound" in data.get("methodology", {}).get("routeSearch", ""),
        "internal_roundtrip_costed": data.get("internalModel", {}).get("internalFeeBps") == 30,
        "flash_premium_costed": data.get("internalModel", {}).get("flashPremiumBps") is not None,
        "gas_costed": all((b.get("best") is None or b["best"].get("gasUsdt", -1) >= 0) for b in blocks),
        "summary_matches_blocks": summary.get("profitableBlocks") == profitable_blocks,
        "all_positive_upper_bounds_exactly_quoted": exact_candidates == upper_candidates,
        "zero_edge_has_no_positive_theoretical_candidate": (
            profitable_blocks > 0
            or all(b.get("maximumSpotUpperBoundNetUsdt", float("inf")) < data["internalModel"]["minimumNetProfitUsdt"] for b in blocks)
        ),
        "no_fake_internal_revenue_field": all("internalRevenue" not in b for b in blocks),
    }
    verdict = "PASS" if all(checks.values()) else "FAIL"
    edge_found = profitable_blocks > 0
    result = {
        "verdict": verdict,
        "edge_status": "REAL_EXECUTABLE_QUOTES_FOUND" if edge_found else "NO_FULLY_NET_PROFITABLE_QUOTE_IN_RANGE",
        "checks": checks,
        "start_block": data.get("startBlock"),
        "end_block": data.get("endBlock"),
        "external_pools": data.get("selectedExternalPools"),
        "eligible_route_cycles_min": min((b.get("eligibleCycles", 0) for b in blocks), default=0),
        "eligible_route_cycles_max": max((b.get("eligibleCycles", 0) for b in blocks), default=0),
        "positive_theoretical_candidates": upper_candidates,
        "exact_candidates": exact_candidates,
        "maximum_spot_upper_bound_net_usdt": max((b.get("maximumSpotUpperBoundNetUsdt", float("-inf")) for b in blocks), default=None),
        "profitable_blocks": summary.get("profitableBlocks", 0),
        "profitable_block_rate": summary.get("profitableBlockRate", 0),
        "independent_episodes": summary.get("independentEpisodes", 0),
        "total_best_net_profit_usdt": summary.get("totalBestNetProfitUsdt", 0),
        "average_best_net_profit_usdt": summary.get("averageBestNetProfitUsdt", 0),
        "maximum_best_net_profit_usdt": summary.get("maximumBestNetProfitUsdt", 0),
        "important_limitation": (
            "The scanner uses real historical DEX states. A marginal-price upper bound is exhaustive "
            "for monotone AMM execution at the sampled state, but public-RPC observation does not prove "
            "private-orderflow inclusion or MEV-resistant live fills."
        ),
    }
    OUTPUT.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))
    if verdict != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
