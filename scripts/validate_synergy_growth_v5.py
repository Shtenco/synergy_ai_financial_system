"""Mandatory acceptance gate for SYNERGY V5."""
from __future__ import annotations

import json
from pathlib import Path

REPORTS = Path("reports")


def load(name: str):
    return json.loads((REPORTS / name).read_text(encoding="utf-8"))


def main() -> None:
    deterministic = load("synergy_growth_dividend_v5_deterministic.json")
    monte = load("synergy_growth_dividend_v5_monte_carlo.json")
    stress = load("synergy_growth_dividend_v5_stress.json")
    polygon = load("synergy_v5_polygon_fork.json")

    checks = {
        "deterministic_pass": deterministic["verdict"] == "PASS",
        "deterministic_growth": deterministic["growth"]["growth_factor"] > 1.0,
        "deterministic_dividend_bound": deterministic["identities"]["dividend_not_above_external_profit"],
        "deterministic_capital_reconciliation": deterministic["identities"]["capital_reconciliation"],
        "deterministic_zero_internal_revenue": deterministic["identities"]["internal_transfer_revenue"] == 0.0,
        "deterministic_no_cash_dividend": deterministic["identities"]["cash_dividend_paid"] == 0.0,
        "monte_carlo_zero_insolvency": monte["insolvency_probability"] == 0.0,
        "monte_carlo_invariant_floor": monte["minimum_single_invariant"] >= 1.0,
        "monte_carlo_multiplier_floor": monte["minimum_active_multiplier"] >= 3.0,
        "monte_carlo_growth": monte["p05_growth_factor"] > 1.0,
        "monte_carlo_dividend_bound": monte["dividend_bound_all_paths"],
        "monte_carlo_reinvestment_identity": monte["reinvestment_identity_all_paths"],
        "monte_carlo_zero_internal_revenue": monte["internal_transfer_revenue"] == 0.0,
        "stress_all_safe": all(row["safe"] for row in stress),
        "stress_unsupported_pauses": any(
            row["scenario"] == "unsupported_volatility_pause"
            and not row["active"]
            and row["gross_dividends"] == 0
            for row in stress
        ),
        "polygon_pass": polygon["pass"],
        "polygon_real_capital_growth": polygon["endingBackedCapitalPOL"]
        == polygon["originalExternalCapitalPOL"]
        + polygon["retainedProfitReinvestedPOL"]
        + polygon["ownerNetReinvestedPOL"]
        + polygon["keeperNetReinvestedPOL"],
        "polygon_dividend_bound": polygon["grossDividendPOL"] <= polygon["realisedExternalProfitPOL"],
        "polygon_zero_cash_dividend": polygon["cashDividendPaidPOL"] == 0,
        "polygon_tax_escrow": polygon["taxEscrowPOL"] > 0,
        "polygon_owner_reinvested": polygon["ownerNetReinvestedPOL"] > 0,
        "polygon_keeper_reinvested": polygon["keeperNetReinvestedPOL"] > 0,
        "polygon_quickswap_growth": int(polygon["quickSwapPositionGrowth"]["polSynaLiquidityAfter"])
        > int(polygon["quickSwapPositionGrowth"]["polSynaLiquidityBefore"])
        and int(polygon["quickSwapPositionGrowth"]["polSynrLiquidityAfter"])
        > int(polygon["quickSwapPositionGrowth"]["polSynrLiquidityBefore"]),
        "polygon_multiplier_3_to_5": 3.0 <= polygon["recognisedMultiplierAfter"] <= 5.0,
        "polygon_single_invariant": polygon["singleInvariantAfter"] >= 1.0,
        "polygon_permissioned_dex": polygon["registeredTradePass"] and polygon["unregisteredTradeRejected"],
        "polygon_public_representative_pool": bool(polygon["publicRepresentativeQuickSwapPool"]),
        "polygon_zero_internal_revenue": polygon["internalTransferRevenuePOL"] == 0,
    }

    failed = [name for name, passed in checks.items() if not passed]
    verdict = "SYNERGY V5 COMPOUNDING SYSTEM: PASS" if not failed else "SYNERGY V5 COMPOUNDING SYSTEM: FAIL"
    result = {
        "verdict": verdict,
        "checks": checks,
        "failed_invariants": failed,
        "metrics": {
            "deterministic_growth_factor": deterministic["growth"]["growth_factor"],
            "monte_carlo_median_growth_factor": monte["median_growth_factor"],
            "monte_carlo_p05_growth_factor": monte["p05_growth_factor"],
            "monte_carlo_minimum_multiplier": monte["minimum_active_multiplier"],
            "monte_carlo_minimum_single_invariant": monte["minimum_single_invariant"],
            "monte_carlo_insolvency_probability": monte["insolvency_probability"],
            "polygon_backed_capital_growth_factor": polygon["backedCapitalGrowthFactor"],
            "polygon_recognised_multiplier_after": polygon["recognisedMultiplierAfter"],
            "polygon_single_invariant_after": polygon["singleInvariantAfter"],
            "polygon_owner_net_reinvested_pol": polygon["ownerNetReinvestedPOL"],
            "polygon_keeper_net_reinvested_pol": polygon["keeperNetReinvestedPOL"],
            "polygon_tax_escrow_pol": polygon["taxEscrowPOL"],
        },
        "limitations": [
            "The representative SYNA and permissioned SINERGY DEX are local fork deployments; WPOL and QuickSwap infrastructure are real Polygon contracts.",
            "Standard DEX events make indexing technically possible, but no third-party screener listing or branding is guaranteed.",
            "Commit-reveal, venue restrictions, non-zero minOut and quote-deviation checks reduce MEV risk; no public blockchain design can honestly guarantee absolute 100% protection.",
            "Tax status and withholding are protocol attestations and configurable escrow policy, not jurisdiction-specific legal advice.",
            "Modelled revenue is not a guarantee of future market demand.",
        ],
    }
    (REPORTS / "synergy_v5_verdict.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
