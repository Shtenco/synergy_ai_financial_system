#!/usr/bin/env python3
"""V15 retained-hard-surplus reserve allocator.

Retained profit should not follow a fixed cosmetic basket. The allocator asks:
which next hard-asset dollar most improves the weakest balance-sheet/stress
headroom while respecting risk-group concentration?

This is a discrete max-min reference optimizer. Production weights, group taxonomy
and scenario coefficients require empirical calibration and on-chain/fork checks.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Mapping, Sequence


@dataclass(frozen=True)
class ReserveAsset:
    name: str
    base_risk_factor: float
    scenario_factors: Mapping[str, float]
    risk_group: str

    def __post_init__(self):
        if not (0 < self.base_risk_factor <= 1):
            raise ValueError("bad base risk factor")
        if any(v < 0 or v > 1 for v in self.scenario_factors.values()):
            raise ValueError("bad scenario factor")
        if not self.risk_group:
            raise ValueError("missing risk group")


def _group_value(
    group: str,
    existing_group_values: Mapping[str, float],
    allocations: Mapping[str, float],
    assets: Mapping[str, ReserveAsset],
) -> float:
    return existing_group_values.get(group, 0.0) + sum(
        amount for name, amount in allocations.items() if assets[name].risk_group == group
    )


def _candidate_group_feasible(
    name: str,
    step: float,
    existing_total: float,
    existing_group_values: Mapping[str, float],
    allocations: Mapping[str, float],
    assets: Mapping[str, ReserveAsset],
    group_limits: Mapping[str, float],
) -> bool:
    asset = assets[name]
    limit = group_limits.get(asset.risk_group, 1.0)
    if not (0 < limit <= 1):
        raise ValueError("bad group limit")
    new_total = existing_total + sum(allocations.values()) + step
    new_group = _group_value(asset.risk_group, existing_group_values, allocations, assets) + step
    return new_total > 0 and new_group / new_total <= limit + 1e-12


def _headrooms_after(
    current_headrooms: Mapping[str, float],
    asset: ReserveAsset,
    step: float,
) -> Dict[str, float]:
    out = dict(current_headrooms)
    out["base"] = out.get("base", 0.0) + asset.base_risk_factor * step
    for scenario, factor in asset.scenario_factors.items():
        out[scenario] = out.get(scenario, 0.0) + factor * step
    return out


def allocate_retained_surplus(
    budget: float,
    assets: Sequence[ReserveAsset],
    current_headrooms: Mapping[str, float],
    existing_total: float,
    existing_group_values: Mapping[str, float],
    group_limits: Mapping[str, float],
    step: float = 1.0,
) -> tuple[Dict[str, float], Dict[str, float], float]:
    """Discrete max-min allocation of retained hard capital.

    Primary objective for each marginal step: maximize the minimum headroom across
    base and all modeled stress constraints. Tie break: maximize total headroom.
    Returns `(allocations, final_headrooms, unallocated_budget)`.
    """
    if budget < 0 or existing_total < 0 or step <= 0:
        raise ValueError("bad allocation input")
    if not assets:
        return {}, dict(current_headrooms), budget

    by_name = {a.name: a for a in assets}
    if len(by_name) != len(assets):
        raise ValueError("duplicate asset name")
    allocations = {a.name: 0.0 for a in assets}
    headrooms = dict(current_headrooms)
    remaining = budget

    while remaining + 1e-12 >= step:
        candidates = []
        for a in assets:
            if not _candidate_group_feasible(
                a.name, step, existing_total, existing_group_values,
                allocations, by_name, group_limits
            ):
                continue
            after = _headrooms_after(headrooms, a, step)
            primary = min(after.values()) if after else float("-inf")
            secondary = sum(after.values())
            candidates.append((primary, secondary, a.name, after))

        if not candidates:
            break
        _, _, chosen, after = max(candidates)
        allocations[chosen] += step
        headrooms = after
        remaining -= step

    return allocations, headrooms, max(0.0, remaining)


def main() -> None:
    assets = [
        ReserveAsset("USDC", .98, {"depeg": .70, "crypto": .98}, "stable"),
        ReserveAsset("DAI", .92, {"depeg": .75, "crypto": .90}, "stable"),
        ReserveAsset("WETH", .85, {"depeg": .85, "crypto": .55}, "crypto"),
    ]
    alloc, heads, rem = allocate_retained_surplus(
        budget=20,
        assets=assets,
        current_headrooms={"base": 5, "depeg": 0, "crypto": 10},
        existing_total=100,
        existing_group_values={"stable": 70, "crypto": 30},
        group_limits={"stable": .70, "crypto": .60},
        step=1,
    )
    print("allocation", alloc)
    print("headrooms", heads)
    print("unallocated", rem)


if __name__ == "__main__":
    main()
