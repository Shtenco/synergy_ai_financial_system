"""Mandatory acceptance gate for SYNERGY V7 graph topology and accounting."""
from pathlib import Path
import json

REPORTS = Path("reports")


def load(name: str):
    return json.loads((REPORTS / name).read_text(encoding="utf-8"))


def main() -> None:
    model = load("synergy_graph_v7_model.json")
    monte = load("synergy_graph_v7_monte_carlo.json")
    fork = load("synergy_graph_v7_polygon_fork.json")

    topology = model["topology"]
    metrics = model["metrics"]
    checks = {
        "model_pass": model["verdict"] == "PASS",
        "exact_three_internal_pools": topology["internal_permissioned_pools"] == ["WPOL/SYNA", "WPOL/SYNR", "SYNA/SYNR"],
        "only_public_representative_pool": topology["public_representative_pools"] == ["QuickSwap V3 WPOL/SYNA"],
        "two_external_pol_usdt_exits": len(topology["external_exit_pools"]) == 2,
        "model_growth": metrics["growth_factor"] > 1.0,
        "model_multiplier": metrics["minimum_multiplier"] >= 3.0,
        "model_invariant": metrics["minimum_invariant"] >= 1.0,
        "model_fake_qe_rejected": metrics["fake_qe_rejected"] >= 40,
        "model_external_profit_only": metrics["realised_external_profit"] > 0 and metrics["internal_transfer_revenue"] == 0,
        "model_no_new_investor_capital": metrics["new_investor_capital_after_bootstrap"] == 0,
        "monte_p05_nonnegative": monte["p05_growth_factor"] >= 1.0,
        "monte_multiplier": monte["minimum_multiplier"] >= 3.0,
        "monte_invariant": monte["minimum_invariant"] >= 1.0,
        "monte_zero_insolvency": monte["insolvency_probability"] == 0.0,
        "monte_fake_qe_rejected": monte["fake_qe_rejected_all_paths"],
        "fork_pass": fork["pass"],
        "fork_three_internal": fork["internalSinergyPools"]["count"] == 3,
        "fork_strict_access": fork["internalSinergyPools"]["outsiderRejected"],
        "fork_one_public_representative": fork["publicRepresentativeQuickSwap"]["count"] == 1,
        "fork_no_public_synr_pairs": fork["publicRepresentativeQuickSwap"]["publicPolSynrAbsent"] and fork["publicRepresentativeQuickSwap"]["publicSynaSynrAbsent"],
        "fork_public_quote_nonzero": fork["publicRepresentativeQuickSwap"]["quoteForPointOnePol"] > 0,
        "fork_front_run_controls": fork["publicRepresentativeQuickSwap"]["commitRevealPassed"],
        "fork_zero_router_quote_rejected": fork["publicRepresentativeQuickSwap"]["zeroQuoteRejected"],
        "fork_sandwich_bound": fork["publicRepresentativeQuickSwap"]["sandwichLossBoundPassed"],
        "fork_two_external_exits": fork["externalExitPools"]["count"] == 2,
        "fork_graph_hybrid": fork["graph"]["includesInternalAndExternalEdges"],
        "fork_external_profit_positive": fork["graph"]["validExternalNetProfitPol"] > 0,
        "fork_fake_qe_rejected": fork["graph"]["fakeQeRevenueRejected"],
        "fork_settlement_asset": fork["graph"]["settlementAsset"].lower() == "0x0d500b1d8e8ef31e21c99d1db9a6444d3adf1270",
    }
    failed = [name for name, ok in checks.items() if not ok]
    result = {
        "verdict": "SYNERGY V7 GRAPH ARBITRAGE: PASS" if not failed else "SYNERGY V7 GRAPH ARBITRAGE: FAIL",
        "checks": checks,
        "failed_invariants": failed,
        "metrics": {
            "model_growth_factor": metrics["growth_factor"],
            "model_minimum_multiplier": metrics["minimum_multiplier"],
            "model_external_profit": metrics["realised_external_profit"],
            "monte_p05_growth_factor": monte["p05_growth_factor"],
            "monte_minimum_multiplier": monte["minimum_multiplier"],
            "fork_external_net_profit_pol": fork["graph"]["validExternalNetProfitPol"],
            "fork_public_quote_point_one_pol": fork["publicRepresentativeQuickSwap"]["quoteForPointOnePol"],
        },
        "limitations": [
            "The fork proves topology, strict access, real external pool discovery, quote protection and consolidated profit gating; it does not guarantee a profitable live cycle at every block.",
            "Commit-reveal, non-zero quote/minOut, deviation checks and sandwich-loss caps materially reduce public execution risk but cannot guarantee absolute protection from validators or all MEV.",
            "QE creates or reallocates internal depth only. A QE-created price gap is charged as internal LP value loss and cannot be recognised as revenue.",
        ],
    }
    (REPORTS / "synergy_graph_v7_verdict.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
