"""Mandatory acceptance gate for SYNERGY Real Liquidity Multiplier V4."""
from __future__ import annotations

import json
from pathlib import Path


def read(name: str):
    return json.loads((Path("reports") / name).read_text(encoding="utf-8"))


def main() -> None:
    deterministic = read("real_liquidity_multiplier_v4_summary.json")
    monte_carlo = read("real_liquidity_multiplier_v4_monte_carlo.json")
    stress = read("real_liquidity_multiplier_v4_stress.json")
    fork = read("real_liquidity_multiplier_v4_polygon_fork.json")

    d = deterministic["metrics"]
    checks = {
        "deterministic_single_invariant": d["minimum_active_single_invariant"] >= 1.0 - 1e-9,
        "deterministic_multiplier_above_3x_in_all_active_regimes": d["minimum_active_multiplier"] >= 3.0 - 1e-9,
        "deterministic_solvency": d["final_economic_solvency_ratio"] >= 1.20,
        "deterministic_liquidity": d["final_liquidity_coverage"] >= 1.20,
        "deterministic_gas": d["final_gas_coverage"] >= 1.20,
        "deterministic_emission_coverage": d["final_external_emission_coverage"] >= 1.20,
        "deterministic_dividend_bound": bool(d["dividend_bound"]),
        "internal_transfer_revenue_zero": d["internal_transfer_revenue"] == 0.0,
        "cross_pool_not_double_counted": not bool(d["cross_pool_counted_in_multiplier"]),
        "monte_carlo_single_invariant": monte_carlo["minimum_active_single_invariant"] >= 1.0 - 1e-9,
        "monte_carlo_multiplier_above_3x_in_all_active_regimes": monte_carlo["minimum_active_multiplier"] >= 3.0 - 1e-9,
        "monte_carlo_zero_insolvency": monte_carlo["insolvency_probability"] == 0.0,
        "monte_carlo_dividend_bound": bool(monte_carlo["dividend_invariant_all_paths"]),
        "monte_carlo_multiplier_cap": bool(monte_carlo["recognized_multiplier_never_above_5x"]),
        "stress_all_safe": bool(stress["all_safe"]),
        "stress_low_vol_5x": stress["minimum_low_vol_multiplier"] >= 5.0 - 1e-9,
        "stress_normal_vol_4x": stress["minimum_normal_vol_multiplier"] >= 4.0 - 1e-9,
        "stress_high_vol_3x": stress["minimum_high_vol_multiplier"] >= 3.0 - 1e-9,
        "unsupported_volatility_pauses": bool(stress["unsupported_volatility_pauses"]),
        "fork_real_polygon_wpol": bool(fork["realPolygonWPOL"]),
        "fork_real_quickswap_factory": bool(fork["realQuickSwapV3Factory"]),
        "fork_real_quickswap_position_manager": bool(fork["realQuickSwapV3PositionManager"]),
        "fork_real_quickswap_quoter": bool(fork["realQuickSwapV3Quoter"]),
        "fork_single_invariant_pass": bool(fork["pass"]) and fork["singleInvariant"] >= 1.0,
        "fork_multiplier_at_least_4x": fork["recognisedMultiplier"] >= 4.0 - 1e-9,
        "fork_multiplier_capped_at_5x": fork["recognisedMultiplier"] <= 5.0 + 1e-9,
        "fork_internal_revenue_zero": fork["internalTransferRevenuePOL"] == 0,
        "fork_cross_pool_not_counted": not bool(fork["crossPoolCountedInMultiplier"]),
        "fork_internal_mint_has_no_external_liability": fork["externalEmissionLiabilityFromInternalMint"] == 0,
        "fork_triangle_executes": fork["triangularQuoteOutputPOL"] > 0,
    }
    failed = [name for name, passed in checks.items() if not passed]
    verdict = (
        "REAL LIQUIDITY MULTIPLIER V4: PASS"
        if not failed
        else "REAL LIQUIDITY MULTIPLIER V4: FAIL"
    )
    result = {
        "verdict": verdict,
        "checks": checks,
        "failed_invariants": failed,
        "core_metrics": {
            "deterministic_minimum_active_multiplier": d["minimum_active_multiplier"],
            "deterministic_minimum_active_single_invariant": d["minimum_active_single_invariant"],
            "monte_carlo_minimum_active_multiplier": monte_carlo["minimum_active_multiplier"],
            "monte_carlo_minimum_active_single_invariant": monte_carlo["minimum_active_single_invariant"],
            "monte_carlo_insolvency_probability": monte_carlo["insolvency_probability"],
            "stress_low_vol_multiplier": stress["minimum_low_vol_multiplier"],
            "stress_normal_vol_multiplier": stress["minimum_normal_vol_multiplier"],
            "stress_high_vol_multiplier": stress["minimum_high_vol_multiplier"],
            "fork_recognised_multiplier": fork["recognisedMultiplier"],
            "fork_single_invariant": fork["singleInvariant"],
            "fork_actual_anchor_pool_pol": fork["actualAnchorPoolPOL"],
            "fork_triangular_quote_output_pol": fork["triangularQuoteOutputPOL"],
        },
        "economic_interpretation": (
            "3-5x is stress V2-equivalent executable depth, not 3-5x "
            "withdrawable POL and not nominal TVL."
        ),
    }
    (Path("reports") / "real_liquidity_multiplier_v4_verdict.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
