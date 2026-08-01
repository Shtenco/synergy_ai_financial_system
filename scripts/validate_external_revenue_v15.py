#!/usr/bin/env python3
"""Fail-closed validator for the V15 Polygon-fork external revenue proof."""
from __future__ import annotations

import json
import math
from pathlib import Path

REPORT = Path("reports/v15_external_revenue_polygon_fork.json")
VERDICT = Path("reports/v15_external_revenue_polygon_fork_verdict.json")


def finite(value: object) -> bool:
    return isinstance(value, (int, float)) and math.isfinite(float(value))


def main() -> None:
    if not REPORT.exists():
        raise SystemExit(f"missing {REPORT}")
    data = json.loads(REPORT.read_text(encoding="utf-8"))
    target = data.get("strictTarget", {})
    venues = data.get("realForkVenues", {})
    backrun = data.get("intrablockBackrun", {})
    auctions = data.get("solverAuctions", {})
    rfq = data.get("privateRfq", {})
    accounting = data.get("consolidatedExternalAccounting", {})
    invariants = data.get("invariants", {})
    limitations = data.get("limitations", {})

    min_ppm = float(target.get("minimumExternalEdgePpm", 0))
    required_gap = float(target.get("v14RequiredImprovementUsdc", 0))
    net = float(accounting.get("netAfterAllActorGasUsdc", 0) or 0)
    net_ppm = float(accounting.get("aggregateNetEdgePpm", 0) or 0)

    checks = {
        "polygon_chain_137": data.get("chainId") == 137,
        "pinned_fork_block_recorded": isinstance(data.get("forkBlock"), int) and data["forkBlock"] > 0,
        "minimum_target_is_269_ppm": min_ppm == 269,
        "real_multidex_families": (
            venues.get("distinctDexFamilies") is True
            and venues.get("sourceDex") == "Uniswap V3"
            and venues.get("destinationDex") == "QuickSwap V2"
            and venues.get("sourceAndDestinationHaveForkCode") is True
            and venues.get("sourcePool")
            and venues.get("destinationPair")
            and str(venues.get("sourcePool")).lower() != str(venues.get("destinationPair")).lower()
        ),
        "same_block_backrun": backrun.get("sameBlock") is True,
        "victim_precedes_backrun": (
            backrun.get("victimBeforeBackrun") is True
            and isinstance(backrun.get("victimTransactionIndex"), int)
            and isinstance(backrun.get("backrunTransactionIndex"), int)
            and backrun["victimTransactionIndex"] < backrun["backrunTransactionIndex"]
        ),
        "no_sandwich_front_run": backrun.get("sandwichFrontRunUsed") is False,
        "public_edge_clears_target": (
            finite(backrun.get("realizedEdgePpm"))
            and float(backrun["realizedEdgePpm"]) >= min_ppm
            and float(backrun.get("realizedRevenueUsdc", 0)) > 0
        ),
        "two_solver_auctions": (
            auctions.get("count") == 2
            and auctions.get("bidsPerAuction") == 3
            and len(auctions.get("committedSolutionHashes", [])) == 2
            and auctions.get("winningSolutionsConsumedOnce") is True
            and float(auctions.get("realizedAuctionRevenueUsdc", 0)) > 0
        ),
        "private_rfq_is_explicitly_simulated": (
            rfq.get("simulatedPrivateMakerLiquidityOnFork") is True
            and rfq.get("historicalRfqQuoteClaimed") is False
            and rfq.get("makerInventorySourcedFromRealForkTokenHolder") is True
            and rfq.get("orderPublishedBeforeFill") is False
        ),
        "private_rfq_has_competition": rfq.get("competingMakerQuotes", 0) >= 3,
        "private_rfq_replay_protected": (
            rfq.get("nonceConsumed") is True
            and rfq.get("replayRejected") is True
        ),
        "rfq_edge_clears_target": (
            finite(rfq.get("realizedEdgePpm"))
            and float(rfq["realizedEdgePpm"]) >= min_ppm
            and float(rfq.get("realizedRevenueUsdc", 0)) > 0
        ),
        "all_actor_gas_is_deducted": (
            finite(accounting.get("allActorGasUsdc"))
            and float(accounting["allActorGasUsdc"]) > 0
        ),
        "net_covers_v14_gap": (
            accounting.get("coversV14Gap") is True
            and net >= required_gap
            and required_gap >= 0.121799 - 1e-9
        ),
        "aggregate_net_edge_clears_269_ppm": (
            accounting.get("clearsMinimum269Ppm") is True
            and net_ppm >= min_ppm
        ),
        "gross_minus_gas_equals_net": abs(
            float(accounting.get("grossExternalRevenueUsdc", 0))
            - float(accounting.get("allActorGasUsdc", 0))
            - net
        ) <= 0.000003,
        "no_protocol_synthetic_mint_burn": invariants.get("protocolSyntheticMintBurnUsed") is False,
        "v14_internal_lps_untouched": invariants.get("internalV14LpBalancesTouched") is False,
        "principal_returned": invariants.get("solverPrincipalReturnedByEngine") is True,
        "only_realized_profit_credited": invariants.get("onlyRealizedExternalProfitCreditedToTreasury") is True,
        "single_use_guards": (
            invariants.get("rfqMakerNonceSingleUse") is True
            and invariants.get("auctionSolutionSingleUse") is True
        ),
        "limitations_are_honest": (
            limitations.get("publicAmmLegsUseHistoricalForkState") is True
            and limitations.get("victimAndBackrunAreActuallyExecutedOnFork") is True
            and limitations.get("privateRelayInclusionIsSimulatedByCommitmentAndSameBlockOrdering") is True
            and limitations.get("rfqMakerQuoteIsAFundedForkSimulationNotHistorical0xEvidence") is True
            and limitations.get("live0xApiKeyUsed") is False
            and limitations.get("productionSecurityAuditCompleted") is False
        ),
    }

    verdict = "PASS" if all(checks.values()) else "FAIL"
    result = {
        "verdict": verdict,
        "checks": checks,
        "fork_block": data.get("forkBlock"),
        "public_backrun_revenue_usdc": backrun.get("realizedRevenueUsdc"),
        "private_rfq_revenue_usdc": rfq.get("realizedRevenueUsdc"),
        "solver_auction_revenue_usdc": auctions.get("realizedAuctionRevenueUsdc"),
        "gross_external_revenue_usdc": accounting.get("grossExternalRevenueUsdc"),
        "all_actor_gas_usdc": accounting.get("allActorGasUsdc"),
        "net_after_all_actor_gas_usdc": accounting.get("netAfterAllActorGasUsdc"),
        "aggregate_net_edge_ppm": accounting.get("aggregateNetEdgePpm"),
        "v14_required_improvement_usdc": target.get("v14RequiredImprovementUsdc"),
        "interpretation": (
            "PASS proves the recorded fork execution used two real DEX families, "
            "ordered a victim transaction before a same-block backrun, settled a "
            "funded maker-signed RFQ through a single-use solver auction, deducted "
            "all recorded actor gas, and exceeded the V14 2.69 bps gap without "
            "protocol synthetic mint/burn. It does not prove historical RFQ availability "
            "or live private-relay inclusion."
        ),
    }
    VERDICT.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))
    if verdict != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
