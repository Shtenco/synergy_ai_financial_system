#!/usr/bin/env python3
"""V13-style stateful multi-asset audit for SynthL1 V6.

The external graph is complete over five liquid assets. Its pair prices are built
from one internally consistent vector of market multipliers, so the external graph
has no standalone cyclic arbitrage at marginal prices after fees.

The protocol then creates a supply-neutral synthetic reserve gradient between two
managed internal pools. A searcher route is:

    quote_B -> synthetic(destination) -> quote_A(source)
    -> external A -> ... -> B -> realized-profit tax

After each route the synthetic reserve is restored exactly to the same target
using a supply-neutral source burn / destination mint. Captured B is physically
reinvested into the destination quote reserve. State is carried forward.
"""
from __future__ import annotations

from dataclasses import dataclass
from itertools import permutations
from typing import Dict, List, Optional, Tuple
import copy
import math

TOKENS = ("USDT", "USDC", "DAI", "WPOL", "WETH")
FAIR_USD = {
    "USDT": 1.0,
    "USDC": 1.0,
    "DAI": 1.0,
    "WPOL": 0.15,
    "WETH": 3000.0,
}
INTERNAL_FEE = 0.003
EXTERNAL_FEE = 0.003


@dataclass
class ExternalPool:
    a: str
    b: str
    reserve_a: float
    reserve_b: float
    fee: float = EXTERNAL_FEE

    def spot_out_per_in(self, token_in: str) -> float:
        if token_in == self.a:
            return self.reserve_b / self.reserve_a
        if token_in == self.b:
            return self.reserve_a / self.reserve_b
        raise ValueError("token not in pool")

    def swap(self, token_in: str, amount: float) -> Tuple[str, float]:
        if token_in == self.a:
            effective = amount * (1.0 - self.fee)
            out = self.reserve_b * effective / (self.reserve_a + effective)
            self.reserve_a += amount
            self.reserve_b -= out
            return self.b, out
        if token_in == self.b:
            effective = amount * (1.0 - self.fee)
            out = self.reserve_a * effective / (self.reserve_b + effective)
            self.reserve_b += amount
            self.reserve_a -= out
            return self.a, out
        raise ValueError("token not in pool")


@dataclass
class Candidate:
    source: str
    destination: str
    path: Tuple[str, ...]
    principal_destination: float
    synthetic: float
    source_quote: float
    returned_destination: float
    gross_profit_usd: float


@dataclass
class Cycle:
    number: int
    source: str
    destination: str
    path: Tuple[str, ...]
    gross_profit_usd: float
    protocol_tax_usd: float
    solver_reward_usd: float
    protocol_real_delta_usd: float
    external_lp_delta_usd: float
    solver_cumulative_usd: float
    conservation_error_usd: float


def make_internal() -> Dict[str, List[float]]:
    # [synthetic reserve, quote-token amount], $100 quote value in every pool.
    return {token: [100.0, 100.0 / FAIR_USD[token]] for token in TOKENS}


def make_external(
    market_multiplier: Dict[str, float],
    fair_side_value_usd: float = 10_000.0,
) -> Dict[Tuple[str, str], ExternalPool]:
    """Build a cycle-consistent complete graph.

    External marginal price of token t is FAIR_USD[t] * market_multiplier[t].
    Because every pair derives from the same vector, products around any cycle
    are exactly one before fees and below one after fees.
    """
    pools: Dict[Tuple[str, str], ExternalPool] = {}
    for i, a in enumerate(TOKENS):
        for b in TOKENS[i + 1:]:
            tilt = market_multiplier[a] / market_multiplier[b]
            value_a = fair_side_value_usd / math.sqrt(tilt)
            value_b = fair_side_value_usd * math.sqrt(tilt)
            reserve_a = value_a / FAIR_USD[a]
            reserve_b = value_b / FAIR_USD[b]
            pools[tuple(sorted((a, b)))] = ExternalPool(a, b, reserve_a, reserve_b)
    return pools


def internal_swap_quote_for_synthetic(pool: List[float], amount: float) -> float:
    x, y = pool
    effective = amount * (1.0 - INTERNAL_FEE)
    out = x * effective / (y + effective)
    pool[1] += amount
    pool[0] -= out
    return out


def internal_swap_synthetic_for_quote(pool: List[float], amount: float) -> float:
    x, y = pool
    effective = amount * (1.0 - INTERNAL_FEE)
    out = y * effective / (x + effective)
    pool[0] += amount
    pool[1] -= out
    return out


def all_paths(source: str, destination: str, max_hops: int = 3) -> List[Tuple[str, ...]]:
    others = [t for t in TOKENS if t not in (source, destination)]
    paths: List[Tuple[str, ...]] = [(source, destination)]
    for intermediates_n in range(1, max_hops):
        for mids in permutations(others, intermediates_n):
            paths.append((source,) + mids + (destination,))
    return paths


def execute_external_path(
    pools: Dict[Tuple[str, str], ExternalPool],
    path: Tuple[str, ...],
    amount: float,
) -> float:
    token = path[0]
    current = amount
    for nxt in path[1:]:
        pool = pools[tuple(sorted((token, nxt)))]
        token, current = pool.swap(token, current)
        if token != nxt:
            raise AssertionError("external path token mismatch")
    return current


def external_value_usd(pools: Dict[Tuple[str, str], ExternalPool]) -> float:
    total = 0.0
    for pool in pools.values():
        total += pool.reserve_a * FAIR_USD[pool.a]
        total += pool.reserve_b * FAIR_USD[pool.b]
    return total


def protocol_real_value_usd(
    internal: Dict[str, List[float]],
    capture: Dict[str, float],
) -> float:
    return sum(pool[1] * FAIR_USD[token] for token, pool in internal.items()) + sum(
        capture[token] * FAIR_USD[token] for token in TOKENS
    )


def external_cycle_upper_bound(
    pools: Dict[Tuple[str, str], ExternalPool],
    max_cycle_len: int = 5,
) -> float:
    """Maximum infinitesimal return multiple of any simple external-only cycle."""
    best = 0.0
    start = TOKENS[0]
    # Rotational symmetry means pinning one start token still covers each simple cycle class.
    others = [t for t in TOKENS if t != start]
    for edges in range(2, max_cycle_len + 1):
        mids_n = edges - 1
        for mids in permutations(others, mids_n):
            path = (start,) + mids + (start,)
            multiple = 1.0
            token = start
            for nxt in path[1:]:
                pool = pools[tuple(sorted((token, nxt)))]
                multiple *= pool.spot_out_per_in(token) * (1.0 - pool.fee)
                token = nxt
            best = max(best, multiple)
    return best


def best_candidate(
    internal: Dict[str, List[float]],
    external: Dict[Tuple[str, str], ExternalPool],
    source: str,
    destination: str,
    principal_steps: int = 800,
) -> Optional[Candidate]:
    max_principal = internal[destination][1] * 0.70
    best: Optional[Candidate] = None
    for i in range(1, principal_steps + 1):
        principal = max_principal * i / principal_steps
        d = copy.deepcopy(internal[destination])
        s = copy.deepcopy(internal[source])
        synthetic = internal_swap_quote_for_synthetic(d, principal)
        source_quote = internal_swap_synthetic_for_quote(s, synthetic)
        for path in all_paths(source, destination, 3):
            ext = copy.deepcopy(external)
            returned = execute_external_path(ext, path, source_quote)
            gross_usd = (returned - principal) * FAIR_USD[destination]
            if gross_usd <= 0:
                continue
            c = Candidate(source, destination, path, principal, synthetic, source_quote, returned, gross_usd)
            if best is None or c.gross_profit_usd > best.gross_profit_usd:
                best = c
    return best


def choose_initial_gradient_pair(
    internal: Dict[str, List[float]],
    external: Dict[Tuple[str, str], ExternalPool],
    shift: float,
) -> Tuple[str, str]:
    best = None
    for source in TOKENS:
        for destination in TOKENS:
            if source == destination:
                continue
            trial = copy.deepcopy(internal)
            if shift >= trial[source][0]:
                continue
            trial[source][0] -= shift
            trial[destination][0] += shift
            candidate = best_candidate(trial, external, source, destination)
            if candidate is None:
                continue
            if best is None or candidate.gross_profit_usd > best[0]:
                best = (candidate.gross_profit_usd, source, destination)
    if best is None:
        raise RuntimeError("no gradient/searcher route")
    return best[1], best[2]


def run_stateful(
    market_multiplier: Dict[str, float],
    shift: float = 40.0,
    cycles: int = 20,
    profit_tax_share: float = 0.99,
    reward_floor_usd: float = 0.001,
) -> Tuple[List[Cycle], str, str, float]:
    internal = make_internal()
    external = make_external(market_multiplier)
    capture = {t: 0.0 for t in TOKENS}

    external_cycle_bound = external_cycle_upper_bound(external)
    source, destination = choose_initial_gradient_pair(internal, external, shift)

    internal[source][0] -= shift
    internal[destination][0] += shift
    target_source = internal[source][0]
    target_destination = internal[destination][0]

    protocol_start = protocol_real_value_usd(internal, capture)
    external_start = external_value_usd(external)
    solver_cumulative = 0.0
    rows: List[Cycle] = []

    for n in range(1, cycles + 1):
        candidate = best_candidate(internal, external, source, destination)
        if candidate is None or candidate.gross_profit_usd <= reward_floor_usd:
            break

        synthetic = internal_swap_quote_for_synthetic(
            internal[destination], candidate.principal_destination
        )
        source_quote = internal_swap_synthetic_for_quote(internal[source], synthetic)
        returned = execute_external_path(external, candidate.path, source_quote)
        gross_destination = returned - candidate.principal_destination
        gross_usd = gross_destination * FAIR_USD[destination]
        if gross_usd <= reward_floor_usd:
            break

        reward_floor_destination = reward_floor_usd / FAIR_USD[destination]
        tax_destination = min(
            profit_tax_share * gross_destination,
            gross_destination - reward_floor_destination,
        )
        reward_destination = gross_destination - tax_destination
        capture[destination] += tax_destination
        solver_cumulative += reward_destination * FAIR_USD[destination]

        # Exact supply-neutral gradient restore after the searcher uses the same
        # synthetic output from destination as input into source.
        source_excess = internal[source][0] - target_source
        destination_deficit = target_destination - internal[destination][0]
        if abs(source_excess - destination_deficit) > 1e-7:
            raise AssertionError("synthetic restore mismatch")
        if source_excess <= 0:
            raise AssertionError("nothing to restore")
        internal[source][0] -= source_excess
        internal[destination][0] += source_excess

        # Physical tax feedback: move captured destination quote into destination LP.
        internal[destination][1] += capture[destination]
        capture[destination] = 0.0

        protocol_delta = protocol_real_value_usd(internal, capture) - protocol_start
        external_delta = external_value_usd(external) - external_start
        conservation = protocol_delta + external_delta + solver_cumulative
        if abs(conservation) > 1e-6:
            raise AssertionError(f"conservation error {conservation}")
        if abs(internal[source][0] - target_source) > 1e-8:
            raise AssertionError("source gradient target lost")
        if abs(internal[destination][0] - target_destination) > 1e-8:
            raise AssertionError("destination gradient target lost")

        rows.append(Cycle(
            n,
            source,
            destination,
            candidate.path,
            gross_usd,
            tax_destination * FAIR_USD[destination],
            reward_destination * FAIR_USD[destination],
            protocol_delta,
            external_delta,
            solver_cumulative,
            conservation,
        ))

    return rows, source, destination, external_cycle_bound


def main() -> None:
    scenarios = {
        "aligned": {t: 1.0 for t in TOKENS},
        "consistent_2pct_basis": {
            "USDT": 1.000,
            "USDC": 0.995,
            "DAI": 1.005,
            "WPOL": 1.020,
            "WETH": 0.980,
        },
        "consistent_5pct_basis": {
            "USDT": 1.000,
            "USDC": 0.990,
            "DAI": 1.010,
            "WPOL": 1.050,
            "WETH": 0.950,
        },
    }
    for name, multipliers in scenarios.items():
        rows, source, destination, cycle_bound = run_stateful(multipliers)
        final = rows[-1] if rows else None
        print(f"\n{name}")
        print(f"external-only marginal cycle upper bound: {cycle_bound:.9f}x")
        print(f"chosen initiated gradient: {source} -> {destination}")
        print(f"stateful exploitations: {len(rows)}")
        if final:
            print(f"captured tax: {sum(x.protocol_tax_usd for x in rows):.6f} USD")
            print(f"solver reward: {final.solver_cumulative_usd:.6f} USD")
            print(f"protocol real-side delta: {final.protocol_real_delta_usd:+.6f} USD")
            print(f"external LP delta: {final.external_lp_delta_usd:+.6f} USD")
            print(f"conservation error: {final.conservation_error_usd:+.12f} USD")


if __name__ == "__main__":
    main()
