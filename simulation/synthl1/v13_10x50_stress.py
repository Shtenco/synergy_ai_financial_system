#!/usr/bin/env python3
"""Fast V13.1 10-internal / 50-external direct-leg stress model.

Geometry:
- 2 controlled synthetic families: SYNA-like and SYNR-like;
- 5 internal quote assets per family => 10 managed internal pools;
- 5 external venue layers;
- 10 quote-asset pairs per venue => 50 external pools;
- every external venue layer is generated from one cycle-consistent price vector;
- venue layers are close enough to each other that external<->external marginal
  round trips stay below the two-swap fee hurdle;
- the maximum true-mark pair basis in the default fixture is 0.8%, below the
  three-leg no-gradient fee hurdle of ~0.9054% for 0.30% fee per leg.

The optimizer creates a supply-neutral gradient, chooses family/source/destination/
venue/shift/principal, accepts only positive protocol HardNAV delta, closes the
synthetic gradient, carries quote/external state forward and repeats.

This stress model uses one direct external leg.  The full multi-hop stateful graph
model lives in stateful_gradient_graph_v13.py.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Tuple

TOKENS = ("USDT", "USDC", "DAI", "WPOL", "WETH")
FAMILIES = ("SYNA", "SYNR")
VENUES = ("V1", "V2", "V3", "V4", "V5")
MARK = {"USDT": 1.0, "USDC": 1.0, "DAI": 1.0, "WPOL": 0.15, "WETH": 3000.0}
FEE = 0.003


@dataclass
class Candidate:
    family: str
    venue: str
    source: str
    destination: str
    shift: float
    principal_destination: float
    protocol_delta_usd: float
    solver_reward_usd: float
    source_quote_after: float
    destination_quote_after: float
    source_quote_to_external: float
    conservation_error_usd: float


@dataclass
class Cycle:
    number: int
    family: str
    venue: str
    source: str
    destination: str
    shift: float
    principal_destination: float
    protocol_increment_usd: float
    protocol_cumulative_usd: float
    solver_cumulative_usd: float
    conservation_error_usd: float


def pair_key(a: str, b: str) -> Tuple[str, str]:
    return tuple(sorted((a, b)))


def pattern(d: float) -> Dict[str, float]:
    return {
        "USDT": 1.0,
        "USDC": 1.0 - 0.67 * d,
        "DAI": 1.0 + 0.67 * d,
        "WPOL": 1.0 + d,
        "WETH": 1.0 - d,
    }


def default_layers() -> Dict[str, Dict[str, float]]:
    # Max true-mark pair displacement = about 2 * 0.004 = 0.8%.
    amplitudes = (0.0030, 0.00325, 0.00350, 0.00375, 0.00400)
    return {venue: pattern(d) for venue, d in zip(VENUES, amplitudes)}


def init_state(
    layers: Dict[str, Dict[str, float]],
    internal_quote_value_usd: float = 100.0,
    synthetic_reserve: float = 100.0,
    external_side_value_usd: float = 100_000.0,
):
    internal = {
        family: {
            token: [synthetic_reserve, internal_quote_value_usd / MARK[token]]
            for token in TOKENS
        }
        for family in FAMILIES
    }
    external = {}
    for venue, multiplier in layers.items():
        venue_price = {token: MARK[token] * multiplier[token] for token in TOKENS}
        for i, a in enumerate(TOKENS):
            for b in TOKENS[i + 1:]:
                key = pair_key(a, b)
                token0, token1 = key
                external[(venue, key)] = [
                    external_side_value_usd / venue_price[token0],
                    external_side_value_usd / venue_price[token1],
                ]
    return internal, external


def external_out(external, venue: str, source: str, destination: str, amount: float) -> float:
    key = pair_key(source, destination)
    token0, _ = key
    reserve0, reserve1 = external[(venue, key)]
    effective = amount * (1.0 - FEE)
    if source == token0:
        return reserve1 * effective / (reserve0 + effective)
    return reserve0 * effective / (reserve1 + effective)


def evaluate(
    internal,
    external,
    family: str,
    venue: str,
    source: str,
    destination: str,
    shift: float,
    principal_destination: float,
    profit_tax_share: float = 0.99,
    solver_reward_floor_usd: float = 0.001,
) -> Optional[Candidate]:
    source_syn, source_quote = internal[family][source]
    dest_syn, dest_quote = internal[family][destination]
    if source == destination or shift <= 0 or shift >= source_syn or principal_destination <= 0:
        return None

    # Supply-neutral synthetic gradient.
    source_syn -= shift
    dest_syn += shift

    # destination quote -> synthetic
    effective = principal_destination * (1.0 - FEE)
    synthetic = dest_syn * effective / (dest_quote + effective)
    destination_quote_after_trade = dest_quote + principal_destination

    # synthetic -> source quote
    effective = synthetic * (1.0 - FEE)
    source_quote_out = source_quote * effective / (source_syn + effective)
    source_quote_after = source_quote - source_quote_out

    # one external source-quote -> destination-quote leg
    returned_destination = external_out(
        external, venue, source, destination, source_quote_out
    )
    gross_destination = returned_destination - principal_destination
    gross_usd = gross_destination * MARK[destination]
    if gross_usd <= solver_reward_floor_usd:
        return None

    floor_destination = solver_reward_floor_usd / MARK[destination]
    protocol_tax_destination = min(
        profit_tax_share * gross_destination,
        gross_destination - floor_destination,
    )
    solver_reward_destination = gross_destination - protocol_tax_destination

    destination_quote_after = destination_quote_after_trade + protocol_tax_destination
    protocol_delta = (
        (source_quote_after - source_quote) * MARK[source]
        + (destination_quote_after - dest_quote) * MARK[destination]
    )
    solver_reward = solver_reward_destination * MARK[destination]

    key = pair_key(source, destination)
    token0, _ = key
    reserve0, reserve1 = external[(venue, key)]
    effective = source_quote_out * (1.0 - FEE)
    if source == token0:
        external_received = reserve1 * effective / (reserve0 + effective)
    else:
        external_received = reserve0 * effective / (reserve1 + effective)
    external_delta = (
        source_quote_out * MARK[source]
        - external_received * MARK[destination]
    )
    conservation = protocol_delta + external_delta + solver_reward

    return Candidate(
        family=family,
        venue=venue,
        source=source,
        destination=destination,
        shift=shift,
        principal_destination=principal_destination,
        protocol_delta_usd=protocol_delta,
        solver_reward_usd=solver_reward,
        source_quote_after=source_quote_after,
        destination_quote_after=destination_quote_after,
        source_quote_to_external=source_quote_out,
        conservation_error_usd=conservation,
    )


def apply_candidate(internal, external, c: Candidate) -> None:
    internal[c.family][c.source][1] = c.source_quote_after
    internal[c.family][c.destination][1] = c.destination_quote_after

    key = pair_key(c.source, c.destination)
    token0, _ = key
    reserve0, reserve1 = external[(c.venue, key)]
    amount = c.source_quote_to_external
    effective = amount * (1.0 - FEE)
    if c.source == token0:
        out = reserve1 * effective / (reserve0 + effective)
        external[(c.venue, key)] = [reserve0 + amount, reserve1 - out]
    else:
        out = reserve0 * effective / (reserve1 + effective)
        external[(c.venue, key)] = [reserve0 - out, reserve1 + amount]


def best_candidate(
    internal,
    external,
    shifts: Iterable[float] = (5, 10, 15, 20, 25, 30, 40, 50),
    principal_steps: int = 60,
    profit_tax_share: float = 0.99,
    solver_reward_floor_usd: float = 0.001,
) -> Optional[Candidate]:
    best: Optional[Candidate] = None
    for family in FAMILIES:
        for venue in VENUES:
            for source in TOKENS:
                for destination in TOKENS:
                    if source == destination:
                        continue
                    max_principal = internal[family][destination][1] * 0.70
                    for shift in shifts:
                        for step in range(1, principal_steps + 1):
                            principal = max_principal * step / principal_steps
                            c = evaluate(
                                internal,
                                external,
                                family,
                                venue,
                                source,
                                destination,
                                shift,
                                principal,
                                profit_tax_share,
                                solver_reward_floor_usd,
                            )
                            if c is None or c.protocol_delta_usd <= 0:
                                continue
                            if best is None or c.protocol_delta_usd > best.protocol_delta_usd:
                                best = c
    return best


def three_leg_break_even_basis_pct() -> float:
    return (1.0 / ((1.0 - FEE) ** 3) - 1.0) * 100.0


def max_external_crossvenue_roundtrip(layers: Dict[str, Dict[str, float]]) -> float:
    best = 0.0
    for source in TOKENS:
        for destination in TOKENS:
            if source == destination:
                continue
            for ma in layers.values():
                first = (MARK[source] * ma[source]) / (MARK[destination] * ma[destination])
                for mb in layers.values():
                    second = (MARK[destination] * mb[destination]) / (MARK[source] * mb[source])
                    best = max(best, first * second * ((1.0 - FEE) ** 2))
    return best


def run(
    principal_steps: int = 60,
    max_cycles: int = 25,
    profit_tax_share: float = 0.99,
    solver_reward_floor_usd: float = 0.001,
) -> List[Cycle]:
    layers = default_layers()
    internal, external = init_state(layers)
    rows: List[Cycle] = []
    protocol_cumulative = 0.0
    solver_cumulative = 0.0

    for number in range(1, max_cycles + 1):
        c = best_candidate(
            internal,
            external,
            principal_steps=principal_steps,
            profit_tax_share=profit_tax_share,
            solver_reward_floor_usd=solver_reward_floor_usd,
        )
        if c is None:
            break
        apply_candidate(internal, external, c)
        protocol_cumulative += c.protocol_delta_usd
        solver_cumulative += c.solver_reward_usd
        rows.append(Cycle(
            number=number,
            family=c.family,
            venue=c.venue,
            source=c.source,
            destination=c.destination,
            shift=c.shift,
            principal_destination=c.principal_destination,
            protocol_increment_usd=c.protocol_delta_usd,
            protocol_cumulative_usd=protocol_cumulative,
            solver_cumulative_usd=solver_cumulative,
            conservation_error_usd=c.conservation_error_usd,
        ))
    return rows


def main() -> None:
    layers = default_layers()
    print("V13.1 10-internal / 50-external stress")
    print(f"three-leg break-even basis: {three_leg_break_even_basis_pct():.6f}%")
    print("fixture max true-mark pair basis: 0.800000%")
    print(f"max external-only cross-venue marginal roundtrip: {max_external_crossvenue_roundtrip(layers):.9f}x")

    for steps in (40, 60, 80):
        rows = run(principal_steps=steps)
        final = rows[-1] if rows else None
        max_error = max((abs(r.conservation_error_usd) for r in rows), default=0.0)
        print(
            f"steps={steps:2d} rotations={len(rows):2d} "
            f"HardNAV={final.protocol_cumulative_usd if final else 0:+.9f} "
            f"solver={final.solver_cumulative_usd if final else 0:.9f} "
            f"maxConservationError={max_error:.3e}"
        )


if __name__ == "__main__":
    main()
