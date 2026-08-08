#!/usr/bin/env python3
"""V15 correlated risk-cluster reference model.

Single-asset concentration is necessary but insufficient. Several different
assets may share the same depeg, issuer, bridge, chain, custody or beta risk.
This reference layer assigns an asset to one or more explicit risk groups and
checks aggregate group exposure after base haircuts.

It is a policy/model layer; group taxonomy and limits require governance plus
empirical stress calibration.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, Mapping, Sequence, Tuple


@dataclass(frozen=True)
class AssetExposure:
    name: str
    risk_value: float
    groups: Tuple[str, ...]

    def __post_init__(self):
        if self.risk_value < 0:
            raise ValueError("negative risk value")
        if not self.groups:
            raise ValueError("every asset needs at least one risk group")


def total_risk_value(assets: Sequence[AssetExposure]) -> float:
    return sum(a.risk_value for a in assets)


def group_values(assets: Sequence[AssetExposure]) -> Dict[str, float]:
    out: Dict[str, float] = {}
    for a in assets:
        for group in set(a.groups):
            out[group] = out.get(group, 0.0) + a.risk_value
    return out


def group_concentrations(assets: Sequence[AssetExposure]) -> Dict[str, float]:
    total = total_risk_value(assets)
    if total <= 0:
        return {g: 0.0 for g in group_values(assets)}
    return {g: v / total for g, v in group_values(assets).items()}


def group_limit_violations(
    assets: Sequence[AssetExposure],
    limits: Mapping[str, float],
) -> Dict[str, tuple[float, float]]:
    if any(limit <= 0 or limit > 1 for limit in limits.values()):
        raise ValueError("group limits must be in (0,1]")
    concentrations = group_concentrations(assets)
    return {
        group: (concentrations[group], limit)
        for group, limit in limits.items()
        if concentrations.get(group, 0.0) > limit
    }


def correlated_group_stress_loss(
    assets: Sequence[AssetExposure],
    group_shocks: Mapping[str, float],
) -> float:
    """Conservative non-double-counting group shock.

    Each asset receives the largest loss shock among its groups. This avoids
    multiplying overlapping categorical shocks while still capturing shared-risk
    concentration. For joint-tail studies, V15 STS scenarios can define explicit
    combined scenarios separately.
    """
    if any(shock < 0 or shock > 1 for shock in group_shocks.values()):
        raise ValueError("shock must be in [0,1]")
    loss = 0.0
    for a in assets:
        shock = max((group_shocks.get(g, 0.0) for g in a.groups), default=0.0)
        loss += a.risk_value * shock
    return loss


def post_stress_risk_value(
    assets: Sequence[AssetExposure],
    group_shocks: Mapping[str, float],
) -> float:
    return total_risk_value(assets) - correlated_group_stress_loss(assets, group_shocks)


def capacity_to_group_limit(
    assets: Sequence[AssetExposure],
    new_asset_groups: Iterable[str],
    group_limits: Mapping[str, float],
) -> float:
    """Maximum additional risk value before any relevant group limit is hit.

    If new capital joins group g, solve `(G_g+x)/(T+x) <= limit_g`.
    If a relevant limit is already breached, capacity is zero.
    """
    total = total_risk_value(assets)
    values = group_values(assets)
    groups = set(new_asset_groups)
    if not groups:
        raise ValueError("new asset needs risk groups")

    capacity = float("inf")
    for g in groups:
        if g not in group_limits:
            continue
        limit = group_limits[g]
        if not (0 < limit < 1):
            if limit == 1:
                continue
            raise ValueError("bad group limit")
        current = values.get(g, 0.0)
        if total > 0 and current / total >= limit:
            return 0.0
        # current + x <= limit*(total+x)
        # x*(1-limit) <= limit*total-current
        cap = (limit * total - current) / (1.0 - limit)
        capacity = min(capacity, max(0.0, cap))
    return capacity


def main() -> None:
    assets = [
        AssetExposure("USDT", 25, ("stablecoin", "centralized-stable")),
        AssetExposure("USDC", 25, ("stablecoin", "centralized-stable")),
        AssetExposure("DAI", 20, ("stablecoin", "crypto-stable")),
        AssetExposure("WETH", 20, ("crypto", "ethereum-beta")),
        AssetExposure("WPOL", 10, ("crypto", "polygon-beta")),
    ]
    limits = {"stablecoin": 0.60, "centralized-stable": 0.50, "crypto": 0.50}
    print("group concentrations", group_concentrations(assets))
    print("violations", group_limit_violations(assets, limits))
    print("stablecoin 20% group-shock loss", correlated_group_stress_loss(assets, {"stablecoin": .20}))


if __name__ == "__main__":
    main()
