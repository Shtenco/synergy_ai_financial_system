"""Mandatory acceptance gate for SYNERGY V7 graph topology and accounting."""
from pathlib import Path
import json

REPORTS = Path("reports")
EXPECTED_INTERNAL = [
    "WPOL/SYNA",
    "WPOL/SYNR",
    "SYNA/SYNR",
    "WPOL/USDT",
    "USDT/SYNA",
    "USDT/SYNR",
]
POLYGON_USDT = "0xc2132d05d31c914a87c6611c10748aeb04b58e8f"


def load(name: str):
    return json.loads((REPORTS / name).read_text(encoding="utf-8"))


def main() -> None:
    model = load("synergy_graph_v7_model.json")
    monte = load("synergy_graph_v7_monte_carlo.json")
    fork = load("synergy_graph_v7_polygon_fork.json")

    topology = model["topology"]
    metrics = model["metrics"]
    internal = fork["internalSinergyPools"]
    public = fork["publicRepresentativeQuickSwap"]
    graph = fork["graph"]

    checks = {
        "model_pass": model["verdict"] == "PASS",
        "exact_six_internal_pools": topology["internal_permissioned_pools"] == EXPECTED_INTERNAL,
        "complete_four_asset_internal_graph": len(topology["internal_permissioned_pools"]) == 6,
        "only_public_representative_pool": topology["public_representative_pools"] == ["QuickSwap V3 WPOL/SYNA"],
        "two_external_pol_usdt_exits": topology["external_exit_pools"] == [
            "QuickSwap V2 WPOL/USDT",
            "QuickSwap V3 WPOL/USDT",
        ],
        "exact_total_graph_size": topology["total_graph_pools"] == 9,
        "model_growth": metrics["growth_factor"] > 1.0,
        "model_multiplier": metrics["minimum_multiplier"] >= 3.0,
        "model_invariant": metrics["minimum_invariant"] >= 1.0,
        "model_fake_qe_rejected": metrics["fake_qe_rejected"] >= 40,
        "model_internal_usdt_routes_used": metrics["internal_usdt_cycles"] > 0,
        "model_external_profit_only": (
            metrics["realised_external_profit"] > 0
            and metrics["internal_transfer_revenue"] == 0
        ),
        "model_no_new_investor_capital": (
            metrics["new_investor_capital_after_bootstrap"] == 0
        ),
        "monte_p05_nonnegative": monte["p05_growth_factor"] >= 1.0,
        "monte_multiplier": monte["minimum_multiplier"] >= 3.0,
        "monte_invariant": monte["minimum_invariant"] >= 1.0,
        "monte_zero_insolvency": monte["insolvency_probability"] == 0.0,
        "monte_fake_qe_rejected": monte["fake_qe_rejected_all_paths"],
        "monte_internal_usdt_topology": monte["internal_usdt_topology_enabled"],
        "fork_pass": fork["pass"],
        "fork_six_internal": internal["count"] == 6,
        "fork_all_internal_liquid": internal["allLiquid"],
        "fork_usdt_strict_access": internal["outsiderRejectedOnUsdtSyna"],
        "fork_lp_transfer_restricted": internal["lpTransferToOutsiderRejected"],
        "fork_internal_addresses_unique": len(
            {
                internal["polSyna"].lower(),
                internal["polSynr"].lower(),
                internal["synaSynr"].lower(),
                internal["polUsdt"].lower(),
                internal["usdtSyna"].lower(),
                internal["usdtSynr"].lower(),
            }
        ) == 6,
        "fork_one_public_representative": public["count"] == 1,
        "fork_no_unauthorised_public_local_pairs": (
            public["publicPolSynrAbsent"]
            and public["publicSynaSynrAbsent"]
            and public["publicUsdtSynaAbsent"]
            and public["publicUsdtSynrAbsent"]
        ),
        "fork_public_quote_nonzero": public["quoteForPointOnePol"] > 0,
        "fork_commit_owner_binding": public["duplicateCommitRejected"],
        "fork_front_run_controls": public["commitRevealPassed"],
        "fork_zero_router_quote_rejected": public["zeroQuoteRejected"],
        "fork_hard_deviation_caps": public["hardDeviationCapsEnabled"],
        "fork_sandwich_bound": public["sandwichLossBoundPassed"],
        "fork_two_external_exits": fork["externalExitPools"]["count"] == 2,
        "fork_exact_total_pool_count": graph["totalPoolCount"] == 9,
        "fork_graph_hybrid": graph["includesInternalAndExternalEdges"],
        "fork_internal_usdt_edge": graph["internalUsdtEdgeUsed"],
        "fork_external_profit_positive": graph["validExternalNetProfitUsdt"] > 0,
        "fork_fake_qe_rejected": graph["fakeQeRevenueRejected"],
        "fork_settlement_asset_usdt": graph["settlementAsset"].lower() == POLYGON_USDT,
    }

    failed = [name for name, ok in checks.items() if not ok]
    result = {
        "verdict": (
            "SYNERGY V7 GRAPH ARBITRAGE: PASS"
            if not failed
            else "SYNERGY V7 GRAPH ARBITRAGE: FAIL"
        ),
        "checks": checks,
        "failed_invariants": failed,
        "metrics": {
            "model_growth_factor": metrics["growth_factor"],
            "model_minimum_multiplier": metrics["minimum_multiplier"],
            "model_external_profit": metrics["realised_external_profit"],
            "model_internal_usdt_cycles": metrics["internal_usdt_cycles"],
            "monte_p05_growth_factor": monte["p05_growth_factor"],
            "monte_minimum_multiplier": monte["minimum_multiplier"],
            "fork_external_net_profit_usdt": graph["validExternalNetProfitUsdt"],
            "fork_public_quote_point_one_pol": public["quoteForPointOnePol"],
            "internal_pool_count": internal["count"],
            "total_graph_pool_count": graph["totalPoolCount"],
        },
        "limitations": [
            (
                "The fork proves the six-pool permissioned core, strict access, "
                "real external pool discovery, quote protection and consolidated "
                "profit gating; it does not guarantee a profitable live cycle at every block."
            ),
            (
                "Owner-bound commit-reveal, non-zero quote/minOut, hard deviation "
                "caps and sandwich-loss caps materially reduce public execution "
                "risk but cannot guarantee absolute protection from validators or all MEV."
            ),
            (
                "QE creates or reallocates internal depth only. A QE-created price "
                "gap is charged as internal LP value loss and cannot be recognised as revenue."
            ),
        ],
    }

    (REPORTS / "synergy_graph_v7_verdict.json").write_text(
        json.dumps(result, indent=2), encoding="utf-8"
    )
    print(json.dumps(result, indent=2))
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
