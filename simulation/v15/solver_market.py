#!/usr/bin/env python3
"""V15 solver-market reference economics.

The protocol should maximize EXPECTED realized hard capture, not the headline tax
percentage. Frozen V13.1 already implements the useful primitive:

  protocolTax = min(tau_max * G, G - absoluteSolverFloor)

so an absolute floor can dominate a 99% ceiling when the opportunity is small.
This module calibrates that floor against an empirical distribution of solver
reservation costs (gas + failure/reorg/inventory/risk premium).

It is a reference model, not a claim about live Polygon solver costs.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence, Optional


@dataclass(frozen=True)
class SolverPolicyResult:
    gross_edge: float
    solver_reward: float
    protocol_capture_if_executed: float
    single_solver_participation: float
    any_solver_participation: float
    expected_protocol_capture: float
    effective_capture_rate: float


def empirical_cdf(samples: Sequence[float], x: float) -> float:
    if not samples:
        raise ValueError("reservation-cost sample required")
    if any(v < 0 for v in samples):
        raise ValueError("negative reservation cost")
    return sum(v <= x for v in samples) / len(samples)


def participation_probability(
    reservation_costs: Sequence[float],
    offered_reward: float,
    solver_count: int,
) -> tuple[float, float]:
    if offered_reward < 0 or solver_count <= 0:
        raise ValueError("bad solver-market input")
    p_one = empirical_cdf(reservation_costs, offered_reward)
    p_any = 1.0 - (1.0 - p_one) ** solver_count
    return p_one, p_any


def policy_result(
    gross_edge: float,
    absolute_reward_floor: float,
    reservation_costs: Sequence[float],
    solver_count: int,
    tax_ceiling: float = 0.99,
) -> SolverPolicyResult:
    if gross_edge <= 0 or absolute_reward_floor < 0 or not (0 <= tax_ceiling < 1):
        raise ValueError("bad edge/tax input")

    percentage_reward = (1.0 - tax_ceiling) * gross_edge
    reward = max(percentage_reward, absolute_reward_floor)
    if reward >= gross_edge:
        capture = 0.0
        reward = gross_edge
    else:
        capture = gross_edge - reward

    p_one, p_any = participation_probability(reservation_costs, reward, solver_count)
    expected = capture * p_any
    rate = 0.0 if gross_edge == 0 else expected / gross_edge
    return SolverPolicyResult(
        gross_edge=gross_edge,
        solver_reward=reward,
        protocol_capture_if_executed=capture,
        single_solver_participation=p_one,
        any_solver_participation=p_any,
        expected_protocol_capture=expected,
        effective_capture_rate=rate,
    )


def optimize_reward_floor(
    gross_edge: float,
    reservation_costs: Sequence[float],
    solver_count: int,
    tax_ceiling: float = 0.99,
    candidate_floors: Optional[Iterable[float]] = None,
) -> SolverPolicyResult:
    if candidate_floors is None:
        # Empirical reservation points are sufficient to locate changes in the CDF.
        candidate_floors = sorted(set([0.0, *reservation_costs, gross_edge]))

    rows = [
        policy_result(gross_edge, f, reservation_costs, solver_count, tax_ceiling)
        for f in candidate_floors
        if 0 <= f <= gross_edge
    ]
    if not rows:
        raise ValueError("no candidate solver floor")

    # Primary objective: expected hard capture. Tie break: higher participation,
    # then lower reward paid to solver.
    return max(rows, key=lambda r: (
        r.expected_protocol_capture,
        r.any_solver_participation,
        -r.solver_reward,
    ))


def realized_tax(gross_edge: float, reward_floor: float, tax_ceiling: float = 0.99) -> tuple[float, float]:
    """Mirror the frozen executor's economic tax/reward split."""
    if gross_edge <= reward_floor or gross_edge <= 0:
        return 0.0, gross_edge
    tax = min(tax_ceiling * gross_edge, gross_edge - reward_floor)
    return tax, gross_edge - tax


def main() -> None:
    # Illustrative empirical reservation-cost sample, not live market data.
    costs = [0.004, 0.006, 0.008, 0.010, 0.012, 0.018, 0.025]
    for gross in (0.02, 0.05, 0.10, 0.25):
        best = optimize_reward_floor(gross, costs, solver_count=4)
        print(
            f"G={gross:.3f} reward={best.solver_reward:.4f} "
            f"pAny={best.any_solver_participation:.3f} "
            f"expectedCapture={best.expected_protocol_capture:.4f} "
            f"rate={best.effective_capture_rate:.1%}"
        )


if __name__ == "__main__":
    main()
