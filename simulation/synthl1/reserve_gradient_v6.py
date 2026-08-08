#!/usr/bin/env python3
"""SynthL1 V6 / V13+V5 supply-neutral reserve-gradient model.

This model reproduces the V12 balance flow, then adds the V5 realized-profit tax:

  burn synthetic reserve in source
  -> mint exactly the same synthetic reserve in destination
  -> searcher supplies quote-B
  -> B -> synthetic (destination)
  -> synthetic -> A (source)
  -> external A -> B graph leg
  -> tax realized B profit
  -> supply-neutral restore of synthetic reserves
  -> physically reinvest captured B into a protocol pool
  -> exploit the initiated gradient again

The aligned-market scenario is intentionally a negative consolidated-value control.
It is used to prove mechanics, repeated exploitation, exact restoration and conservation,
not to claim that an aligned external pool is a free source of hard value.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional
import copy

FEE = 0.003


@dataclass
class Pool:
    token0: float
    token1: float
    fee: float = FEE

    @property
    def spot1_per_0(self) -> float:
        return self.token1 / self.token0

    def swap0_for_1(self, amount: float) -> float:
        if amount <= 0:
            raise ValueError("amount must be positive")
        effective = amount * (1.0 - self.fee)
        out = self.token1 * effective / (self.token0 + effective)
        self.token0 += amount
        self.token1 -= out
        return out

    def swap1_for_0(self, amount: float) -> float:
        if amount <= 0:
            raise ValueError("amount must be positive")
        effective = amount * (1.0 - self.fee)
        out = self.token0 * effective / (self.token1 + effective)
        self.token1 += amount
        self.token0 -= out
        return out


@dataclass
class Candidate:
    principal_b: float
    synthetic: float
    liquid_a: float
    returned_b: float
    gross_profit_b: float
    protocol_tax_b: float
    solver_reward_b: float


@dataclass
class Cycle:
    number: int
    principal_b: float
    synthetic_restored: float
    gross_profit_b: float
    protocol_tax_b: float
    solver_reward_b: float
    protocol_real_delta_b: float
    external_lp_delta_b: float
    solver_cumulative_b: float
    conservation_error_b: float


def create_supply_neutral_gradient(source: Pool, destination: Pool, shift: float) -> None:
    if shift <= 0 or shift >= source.token0:
        raise ValueError("invalid gradient shift")
    # Equivalent to source burn + destination mint. Total synthetic supply is unchanged.
    source.token0 -= shift
    destination.token0 += shift


def restore_supply_neutral_gradient(
    source: Pool,
    destination: Pool,
    target_source: float,
    target_destination: float,
    dust: float = 1e-8,
) -> float:
    source_excess = source.token0 - target_source
    destination_deficit = target_destination - destination.token0
    if source_excess <= 0 or destination_deficit <= 0:
        raise ValueError("invalid post-arbitrage gradient state")
    if abs(source_excess - destination_deficit) > dust:
        raise ValueError("synthetic restoration mismatch")
    restored = min(source_excess, destination_deficit)
    source.token0 -= restored
    destination.token0 += restored
    return restored


def best_searcher_cycle(
    source: Pool,
    destination: Pool,
    external_a_b: Pool,
    profit_tax_share: float = 0.99,
    reward_floor_b: float = 0.001,
    max_principal_b: float = 100.0,
    steps: int = 12_000,
) -> Optional[Candidate]:
    """B -> SYN(destination) -> A(source) -> B(external)."""
    best: Optional[Candidate] = None
    for i in range(1, steps + 1):
        principal = max_principal_b * i / steps
        d = copy.deepcopy(destination)
        s = copy.deepcopy(source)
        e = copy.deepcopy(external_a_b)

        synthetic = d.swap1_for_0(principal)
        liquid_a = s.swap0_for_1(synthetic)
        returned = e.swap0_for_1(liquid_a)
        gross = returned - principal
        if gross <= reward_floor_b:
            continue

        tax = min(profit_tax_share * gross, gross - reward_floor_b)
        reward = gross - tax
        candidate = Candidate(principal, synthetic, liquid_a, returned, gross, tax, reward)
        if best is None or candidate.gross_profit_b > best.gross_profit_b:
            best = candidate
    return best


def run_aligned_control(
    shift: float = 40.0,
    internal_reserve: float = 100.0,
    external_reserve: float = 10_000.0,
    cycles: int = 50,
    profit_tax_share: float = 0.99,
    reward_floor_b: float = 0.001,
    reinvest_tax_to_destination: bool = True,
) -> List[Cycle]:
    """Stateful repeated exploitation of one self-created gradient.

    A and B start at the same external reference value. This is deliberately an
    aligned negative control: any searcher profit must be paid by the protocol
    and/or external LP, and the conservation identity must close.
    """
    source = Pool(internal_reserve, internal_reserve)
    destination = Pool(internal_reserve, internal_reserve)
    external = Pool(external_reserve, external_reserve)

    create_supply_neutral_gradient(source, destination, shift)
    target_source = source.token0
    target_destination = destination.token0

    protocol_real_start = source.token1 + destination.token1
    external_real_start = external.token0 + external.token1
    capture = 0.0
    solver_cumulative = 0.0
    rows: List[Cycle] = []

    for n in range(1, cycles + 1):
        max_principal = min(100.0, destination.token1 * 0.70)
        candidate = best_searcher_cycle(
            source,
            destination,
            external,
            profit_tax_share=profit_tax_share,
            reward_floor_b=reward_floor_b,
            max_principal_b=max_principal,
        )
        if candidate is None:
            break

        synthetic = destination.swap1_for_0(candidate.principal_b)
        liquid_a = source.swap0_for_1(synthetic)
        returned_b = external.swap0_for_1(liquid_a)
        gross = returned_b - candidate.principal_b
        tax = min(profit_tax_share * gross, gross - reward_floor_b)
        reward = gross - tax

        capture += tax
        solver_cumulative += reward
        restored = restore_supply_neutral_gradient(
            source, destination, target_source, target_destination
        )

        # Physical MEV-tax feedback: tax is moved from capture into destination B reserve.
        if reinvest_tax_to_destination and capture > 0:
            destination.token1 += capture
            capture = 0.0

        protocol_real = source.token1 + destination.token1 + capture
        external_real = external.token0 + external.token1
        protocol_delta = protocol_real - protocol_real_start
        external_delta = external_real - external_real_start
        conservation = protocol_delta + external_delta + solver_cumulative

        rows.append(Cycle(
            number=n,
            principal_b=candidate.principal_b,
            synthetic_restored=restored,
            gross_profit_b=gross,
            protocol_tax_b=tax,
            solver_reward_b=reward,
            protocol_real_delta_b=protocol_delta,
            external_lp_delta_b=external_delta,
            solver_cumulative_b=solver_cumulative,
            conservation_error_b=conservation,
        ))

        if abs(source.token0 - target_source) > 1e-8:
            raise AssertionError("source synthetic target not restored")
        if abs(destination.token0 - target_destination) > 1e-8:
            raise AssertionError("destination synthetic target not restored")
        if abs(conservation) > 1e-7:
            raise AssertionError(f"conservation error {conservation}")

    return rows


def gradient_price_ratio(shift: float, reserve: float = 100.0) -> float:
    if shift <= 0 or shift >= reserve:
        raise ValueError("invalid shift")
    source_spot = reserve / (reserve - shift)
    destination_spot = reserve / (reserve + shift)
    return source_spot / destination_spot


def sweep() -> List[dict]:
    output = []
    for shift in (10, 20, 30, 40, 50, 60, 70, 80, 90):
        rows = run_aligned_control(shift=float(shift))
        if not rows:
            continue
        output.append({
            "shift_pct_of_synthetic_reserve": shift,
            "initial_price_ratio_x": gradient_price_ratio(float(shift)),
            "initial_wedge_pct": (gradient_price_ratio(float(shift)) - 1.0) * 100.0,
            "exploitations": len(rows),
            "captured_tax_b": sum(x.protocol_tax_b for x in rows),
            "solver_reward_b": sum(x.solver_reward_b for x in rows),
            "protocol_real_delta_b": rows[-1].protocol_real_delta_b,
            "external_lp_delta_b": rows[-1].external_lp_delta_b,
            "max_conservation_error": max(abs(x.conservation_error_b) for x in rows),
        })
    return output


def main() -> None:
    rows = run_aligned_control(shift=40.0)
    print("V6 supply-neutral gradient / repeated exploitation control")
    print(f"initial price ratio: {gradient_price_ratio(40.0):.6f}x")
    print(f"completed exploitations: {len(rows)}")
    print(f"captured realized-profit tax: {sum(x.protocol_tax_b for x in rows):.6f} B")
    print(f"solver retained reward: {sum(x.solver_reward_b for x in rows):.6f} B")
    print(f"protocol real-side delta: {rows[-1].protocol_real_delta_b:+.6f} B")
    print(f"external LP delta: {rows[-1].external_lp_delta_b:+.6f} B")
    print(f"max conservation error: {max(abs(x.conservation_error_b) for x in rows):.12f}")
    print("\nGradient sweep")
    for row in sweep():
        print(row)


if __name__ == "__main__":
    main()
