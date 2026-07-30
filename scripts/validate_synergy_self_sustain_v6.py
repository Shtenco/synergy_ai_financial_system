"""Mandatory acceptance gate for the exact SYNERGY V6 claim."""
from __future__ import annotations

import json
from pathlib import Path

REPORTS = Path("reports")


def load(name: str):
    return json.loads((REPORTS / name).read_text(encoding="utf-8"))


def close(a: float, b: float, tolerance: float = 1e-8) -> bool:
    return abs(a - b) <= tolerance


def main() -> None:
    model = load("synergy_self_sustain_v6_model.json")
    polygon = load("synergy_self_sustain_v6_polygon_fork.json")
    modes = model["modes"]
    full = modes["full_profit_compounding"]
    dividend_only = modes["dividend_only_productive"]
    zero = modes["zero_external_profit"]
    recycling = modes["internal_recycling_only"]
    monte = model["monte_carlo"]

    checks = {
        "model_no_new_investor_capital": all(
            row["new_investor_capital_after_bootstrap"] == 0
            for row in modes.values()
        ),
        "model_full_compounding_grows": full["final_total_backed_capital"] > full["bootstrap_capital"],
        "model_full_multiplier_above_3": full["minimum_multiplier"] >= 3.0,
        "model_full_base_invariant": full["minimum_base_invariant"] >= 1.0,
        "model_full_self_sustain_invariant": full["self_sustain_invariant"] >= 1.0,
        "model_operating_revenue_covers_cost": full["gross_external_revenue"] > full["external_expense"],
        "model_dividend_only_productive_base_non_decreasing": dividend_only["final_productive_capital"] >= dividend_only["bootstrap_capital"],
        "model_dividend_only_multiplier_above_3": dividend_only["minimum_multiplier"] >= 3.0,
        "model_zero_external_profit_no_growth": close(zero["final_total_backed_capital"], zero["bootstrap_capital"]),
        "model_zero_external_profit_no_dividend": close(zero["owner_dividend_reinvested"], 0.0) and close(zero["keeper_dividend_reinvested"], 0.0),
        "model_internal_recycling_no_growth": close(recycling["final_total_backed_capital"], recycling["bootstrap_capital"]),
        "model_internal_recycling_no_revenue": close(recycling["gross_external_revenue"], 0.0),
        "model_rejects_dividend_money_creation": zero["self_sustain_invariant"] == 0.0 and recycling["self_sustain_invariant"] == 0.0,
        "model_growth_mostly_retained_profit": full["retained_profit"] > full["owner_dividend_reinvested"] + full["keeper_dividend_reinvested"],
        "monte_carlo_all_full_paths_grow": monte["all_full_paths_grow"],
        "monte_carlo_dividend_only_non_decreasing": monte["all_dividend_only_paths_non_decreasing"],
        "monte_carlo_multiplier_above_3": monte["minimum_multiplier"] >= 3.0,
        "monte_carlo_base_invariant": monte["minimum_base_invariant"] >= 1.0,
        "monte_carlo_self_sustain_invariant": monte["minimum_active_self_sustain_invariant"] >= 1.0,
        "monte_carlo_zero_insolvency": monte["insolvency_probability"] == 0.0,
        "polygon_pass": polygon["pass"],
        "polygon_no_new_investor_capital": polygon["newInvestorCapitalAfterBootstrapPOL"] == 0,
        "polygon_original_capital_fixed": polygon["bootstrapExternalCapitalPOL"] == 120,
        "polygon_capital_grows_from_external_profit": polygon["endingBackedCapitalPOL"] > polygon["bootstrapExternalCapitalPOL"],
        "polygon_capital_reconciliation": close(
            polygon["endingBackedCapitalPOL"],
            polygon["bootstrapExternalCapitalPOL"]
            + polygon["retainedProfitReinvestedPOL"]
            + polygon["ownerDividendReinvestedPOL"]
            + polygon["keeperDividendReinvestedPOL"],
        ),
        "polygon_expense_before_profit": close(
            polygon["netExternalProfitPOL"],
            polygon["grossExternalOperatingRevenuePOL"] - polygon["keeperExternalExpensePOL"],
        ),
        "polygon_multiplier_above_3": 3.0 <= polygon["recognisedLiquidityMultiplier"] <= 5.0,
        "polygon_base_invariant": polygon["baseSingleInvariant"] >= 1.0,
        "polygon_self_sustain_invariant": polygon["selfSustainInvariant"] >= 1.0,
        "polygon_zero_revenue_no_growth": polygon["zeroExternalRevenueGrowthPOL"] == 0,
        "polygon_internal_recycling_no_growth": polygon["internalRecyclingGrowthPOL"] == 0,
        "polygon_quickswap_positions_grow": int(polygon["quickSwapPositionGrowth"]["polSynaAfter"]) > int(polygon["quickSwapPositionGrowth"]["polSynaBefore"]) and int(polygon["quickSwapPositionGrowth"]["polSynrAfter"]) > int(polygon["quickSwapPositionGrowth"]["polSynrBefore"]),
        "polygon_nonzero_public_quote": int(polygon["publicQuoteForPointOnePOL"]) > 0,
    }

    failed = [name for name, passed in checks.items() if not passed]
    verdict = (
        "SYNERGY V6 ZERO-NEW-CAPITAL SELF-SUSTAIN: PASS"
        if not failed
        else "SYNERGY V6 ZERO-NEW-CAPITAL SELF-SUSTAIN: FAIL"
    )
    result = {
        "verdict": verdict,
        "checks": checks,
        "failed_invariants": failed,
        "economic_answer": {
            "zero_new_investor_capital": "PASS" if checks["polygon_no_new_investor_capital"] else "FAIL",
            "liquidity_multiplier_above_3": "PASS" if checks["polygon_multiplier_above_3"] else "FAIL",
            "self_support_from_operating_profit_compounding": "PASS" if checks["polygon_self_sustain_invariant"] else "FAIL",
            "dividends_create_profit_by_themselves": "REJECTED",
            "strict_interpretation": "The system can continue without new investors only while external operating revenue exceeds keeper/gas and other external costs. Reinvestment compounds that profit; it does not manufacture it.",
        },
        "metrics": {
            "model_full_growth_factor": full["final_total_backed_capital"] / full["bootstrap_capital"],
            "model_dividend_only_productive_growth_factor": dividend_only["final_productive_capital"] / dividend_only["bootstrap_capital"],
            "model_minimum_multiplier": min(full["minimum_multiplier"], dividend_only["minimum_multiplier"]),
            "model_self_sustain_invariant": full["self_sustain_invariant"],
            "monte_carlo_full_p05_growth_factor": monte["full_compounding_p05_total_growth_factor"],
            "monte_carlo_dividend_only_p05_growth_factor": monte["dividend_only_p05_productive_growth_factor"],
            "polygon_growth_factor": polygon["capitalGrowthFactor"],
            "polygon_multiplier": polygon["recognisedLiquidityMultiplier"],
            "polygon_self_sustain_invariant": polygon["selfSustainInvariant"],
        },
    }
    (REPORTS / "synergy_self_sustain_v6_verdict.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
