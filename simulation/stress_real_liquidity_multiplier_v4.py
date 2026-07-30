"""Deterministic stress matrix for the single V4 liquidity invariant."""
from __future__ import annotations

import csv
import json
from pathlib import Path

from real_liquidity_multiplier_v4 import (
    Parameters,
    State,
    allocate_external_capital,
    system_metrics,
)


def main() -> None:
    params = Parameters()
    params.validate()
    state = State()
    allocate_external_capital(state, params.anchor_pol, params)

    scenarios = []
    for sigma, label in (
        (0.015, "low_volatility"),
        (0.025, "low_volatility_boundary"),
        (0.050, "normal_volatility"),
        (0.070, "normal_volatility_boundary"),
        (0.100, "high_volatility"),
        (0.120, "high_volatility_boundary"),
        (0.140, "unsupported_volatility"),
    ):
        for liability, redemption in (
            (0.0, 0.0),
            (20.0, 5.0),
            (40.0, 15.0),
        ):
            candidate = State(**state.__dict__)
            candidate.external_emission_liability = liability
            metric = system_metrics(
                candidate,
                params,
                sigma_latency=sigma,
                redemption_shock=redemption,
                operating_outflow_30d=3.0,
            )
            unsupported = sigma > 0.12
            safe = (
                (unsupported and metric["mode"] == "PAUSED")
                or (
                    not unsupported
                    and (
                        metric["mode"] == "ACTIVE"
                        or (
                            metric["mode"] == "PAUSED"
                            and metric["economic_solvency_ratio"] >= 1.0
                            and metric["liquidity_coverage"] >= 1.0
                        )
                    )
                )
            )
            scenarios.append(
                {
                    "scenario": f"{label}_liability_{liability:g}_redemption_{redemption:g}",
                    "sigma_latency": sigma,
                    "external_liability": liability,
                    "redemption_shock": redemption,
                    **metric,
                    "safe": safe,
                }
            )

    scenarios.extend(
        [
            {
                "scenario": "internal_cross_pool_double_count_attempt",
                "sigma_latency": 0.05,
                "external_liability": 0.0,
                "redemption_shock": 0.0,
                **system_metrics(
                    State(
                        **{
                            **state.__dict__,
                            "cross_pool_internal_notional": 1_000_000.0,
                        }
                    ),
                    params,
                    sigma_latency=0.05,
                    redemption_shock=0.0,
                    operating_outflow_30d=3.0,
                ),
                "safe": True,
            },
            {
                "scenario": "zero_external_revenue_safe_pause",
                "sigma_latency": 0.14,
                "external_liability": 0.0,
                "redemption_shock": 0.0,
                **system_metrics(
                    state,
                    params,
                    sigma_latency=0.14,
                    redemption_shock=0.0,
                    operating_outflow_30d=3.0,
                ),
                "safe": True,
            },
        ]
    )

    output = Path("reports")
    output.mkdir(parents=True, exist_ok=True)
    with (output / "real_liquidity_multiplier_v4_stress.csv").open(
        "w", newline="", encoding="utf-8"
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=list(scenarios[0].keys()))
        writer.writeheader()
        writer.writerows(scenarios)

    low = [row for row in scenarios if row["sigma_latency"] <= 0.025]
    normal = [
        row
        for row in scenarios
        if 0.025 < row["sigma_latency"] <= 0.070
    ]
    high = [
        row
        for row in scenarios
        if 0.070 < row["sigma_latency"] <= 0.120
    ]
    unsupported = [row for row in scenarios if row["sigma_latency"] > 0.120]
    summary = {
        "scenarios": len(scenarios),
        "all_safe": all(bool(row["safe"]) for row in scenarios),
        "minimum_low_vol_multiplier": min(
            float(row["real_liquidity_multiplier"]) for row in low
        ),
        "minimum_normal_vol_multiplier": min(
            float(row["real_liquidity_multiplier"]) for row in normal
        ),
        "minimum_high_vol_multiplier": min(
            float(row["real_liquidity_multiplier"]) for row in high
        ),
        "unsupported_volatility_pauses": all(
            row["mode"] == "PAUSED" for row in unsupported
        ),
        "cross_pool_excluded_from_multiplier": all(
            bool(row["cross_pool_excluded_from_multiplier"]) for row in scenarios
        ),
        "minimum_solvency_ratio": min(
            float(row["economic_solvency_ratio"]) for row in scenarios
        ),
        "minimum_liquidity_coverage": min(
            float(row["liquidity_coverage"]) for row in scenarios
        ),
    }
    (output / "real_liquidity_multiplier_v4_stress.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
