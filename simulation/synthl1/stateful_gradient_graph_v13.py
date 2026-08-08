#!/usr/bin/env python3
"""V13.1 stateful reserve-gradient / multi-asset HardNAV audit.

This is the corrected continuation of the V12/V13 line.

Important accounting rule
-------------------------
The same USD mark vector is used for:
- protocol hard-asset valuation;
- external LP valuation;
- searcher retained-profit valuation.

The external venue vector is separate.  If venue prices equal oracle/market marks,
a self-created reserve gradient can create a searcher edge but cannot create hard
value: the protocol pays the edge and/or the external LP earns fee/slippage.

The useful case is subtler and stronger than simply "wait for an external arb":
a small, cycle-consistent cross-venue basis can be below the standalone fee hurdle.
A supply-neutral gradient can make that latent basis executable.  With realized-
profit capture and a post-trade HardNAV guard, only routes that actually increase
protocol hard NAV survive.  The gradient is then closed/rotated and the search is
repeated on the updated graph state.

Cycle:
  supply-neutral synthetic shift
  -> B -> SYN(destination) -> A(source)
  -> external A -> ... -> B
  -> realized-profit tax
  -> exact synthetic target restore
  -> physical tax reinvestment
  -> close/rotate gradient
  -> re-optimize on updated state

No positive HardNAV is attributed to synthetic reserve marks or market cap.
"""
from __future__ import annotations

from dataclasses import dataclass
from itertools import permutations
from typing import Dict, Iterable, List, Optional, Tuple
import copy

TOKENS = ("USDT", "USDC", "DAI", "WPOL", "WETH")
BASE_USD = {
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
        if amount <= 0:
            raise ValueError("amount must be positive")
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
class Evaluation:
    source: str
    destination: str
    shift: float
    path: Tuple[str, ...]
    principal_destination: float
    synthetic_moved: float
    gross_profit_usd: float
    protocol_tax_usd: float
    solver_reward_usd: float
    protocol_hard_delta_usd: float
    external_lp_delta_usd: float
    conservation_error_usd: float
    internal_after: Dict[str, List[float]]
    external_after: Dict[Tuple[str, str], ExternalPool]


@dataclass
class Cycle:
    number: int
    source: str
    destination: str
    shift: float
    path: Tuple[str, ...]
    principal_destination: float
    gross_profit_usd: float
    protocol_tax_usd: float
    solver_reward_usd: float
    protocol_increment_usd: float
    protocol_cumulative_usd: float
    external_cumulative_usd: float
    solver_cumulative_usd: float
    conservation_error_usd: float


def price_vector(multiplier: Optional[Dict[str, float]] = None) -> Dict[str, float]:
    multiplier = multiplier or {t: 1.0 for t in TOKENS}
    return {t: BASE_USD[t] * multiplier[t] for t in TOKENS}


def make_internal(
    mark_usd: Dict[str, float],
    quote_side_value_usd: float = 100.0,
    synthetic_reserve: float = 100.0,
) -> Dict[str, List[float]]:
    """Each internal pool starts with equal true USD quote value.

    Synthetic reserve is deliberately NOT counted as hard NAV.
    """
    return {
        token: [synthetic_reserve, quote_side_value_usd / mark_usd[token]]
        for token in TOKENS
    }


def make_external(
    venue_usd: Dict[str, float],
    side_value_usd: float = 100_000.0,
) -> Dict[Tuple[str, str], ExternalPool]:
    """Build a complete cycle-consistent external graph from one venue vector.

    Every pair has equal *venue-marked* value on both sides, therefore pair ratios
    are mutually consistent and no standalone marginal external cycle exists after fees.
    `venue_usd` may nevertheless differ slightly from the independent oracle/mark
    vector used for consolidated HardNAV.
    """
    pools: Dict[Tuple[str, str], ExternalPool] = {}
    for i, a in enumerate(TOKENS):
        for b in TOKENS[i + 1:]:
            pools[tuple(sorted((a, b)))] = ExternalPool(
                a,
                b,
                side_value_usd / venue_usd[a],
                side_value_usd / venue_usd[b],
            )
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


def all_paths(source: str, destination: str, max_external_edges: int = 3) -> List[Tuple[str, ...]]:
    others = [t for t in TOKENS if t not in (source, destination)]
    paths: List[Tuple[str, ...]] = [(source, destination)]
    for intermediates_n in range(1, max_external_edges):
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


def protocol_hard_value_usd(internal: Dict[str, List[float]], mark_usd: Dict[str, float]) -> float:
    return sum(pool[1] * mark_usd[token] for token, pool in internal.items())


def external_value_usd(
    pools: Dict[Tuple[str, str], ExternalPool],
    mark_usd: Dict[str, float],
) -> float:
    total = 0.0
    for pool in pools.values():
        total += pool.reserve_a * mark_usd[pool.a]
        total += pool.reserve_b * mark_usd[pool.b]
    return total


def external_cycle_upper_bound(
    pools: Dict[Tuple[str, str], ExternalPool],
    max_cycle_len: int = 5,
) -> float:
    """Maximum infinitesimal return multiple of any simple external-only cycle."""
    best = 0.0
    start = TOKENS[0]
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


def evaluate_gradient_route(
    internal: Dict[str, List[float]],
    external: Dict[Tuple[str, str], ExternalPool],
    mark_usd: Dict[str, float],
    source: str,
    destination: str,
    shift: float,
    principal_destination: float,
    path: Tuple[str, ...],
    profit_tax_share: float = 0.99,
    reward_floor_usd: float = 0.001,
    close_gradient: bool = True,
) -> Optional[Evaluation]:
    if source == destination or principal_destination <= 0:
        return None
    if not (0.0 <= profit_tax_share < 1.0):
        raise ValueError("profit_tax_share must be in [0,1)")

    nxt_i = copy.deepcopy(internal)
    nxt_e = copy.deepcopy(external)

    source_baseline = nxt_i[source][0]
    destination_baseline = nxt_i[destination][0]
    total_synthetic_before = sum(p[0] for p in nxt_i.values())

    if shift < 0 or shift >= source_baseline:
        return None
    if shift > 0:
        nxt_i[source][0] -= shift
        nxt_i[destination][0] += shift

    target_source = nxt_i[source][0]
    target_destination = nxt_i[destination][0]

    protocol_before = protocol_hard_value_usd(nxt_i, mark_usd)
    external_before = external_value_usd(nxt_e, mark_usd)

    synthetic = internal_swap_quote_for_synthetic(
        nxt_i[destination], principal_destination
    )
    source_quote = internal_swap_synthetic_for_quote(nxt_i[source], synthetic)
    returned_destination = execute_external_path(nxt_e, path, source_quote)

    gross_destination = returned_destination - principal_destination
    gross_usd = gross_destination * mark_usd[destination]
    if gross_usd <= reward_floor_usd:
        return None

    reward_floor_destination = reward_floor_usd / mark_usd[destination]
    protocol_tax_destination = min(
        profit_tax_share * gross_destination,
        gross_destination - reward_floor_destination,
    )
    solver_reward_destination = gross_destination - protocol_tax_destination

    # Exact supply-neutral restoration of the configured gradient target.
    source_excess = nxt_i[source][0] - target_source
    destination_deficit = target_destination - nxt_i[destination][0]
    if source_excess <= 0 or destination_deficit <= 0:
        raise AssertionError("invalid synthetic restore state")
    if abs(source_excess - destination_deficit) > 1e-8:
        raise AssertionError("synthetic restore mismatch")
    nxt_i[source][0] -= source_excess
    nxt_i[destination][0] += destination_deficit

    # Physical realized-profit capture is reinvested into destination quote reserve.
    nxt_i[destination][1] += protocol_tax_destination

    # Rotation mode closes the gradient before the next optimizer pass.
    if close_gradient and shift > 0:
        nxt_i[destination][0] -= shift
        nxt_i[source][0] += shift
        if abs(nxt_i[source][0] - source_baseline) > 1e-8:
            raise AssertionError("source baseline not restored on close")
        if abs(nxt_i[destination][0] - destination_baseline) > 1e-8:
            raise AssertionError("destination baseline not restored on close")

    total_synthetic_after = sum(p[0] for p in nxt_i.values())
    if abs(total_synthetic_after - total_synthetic_before) > 1e-8:
        raise AssertionError("supply-neutral invariant failed")

    protocol_delta = protocol_hard_value_usd(nxt_i, mark_usd) - protocol_before
    external_delta = external_value_usd(nxt_e, mark_usd) - external_before
    tax_usd = protocol_tax_destination * mark_usd[destination]
    solver_usd = solver_reward_destination * mark_usd[destination]
    conservation = protocol_delta + external_delta + solver_usd

    return Evaluation(
        source=source,
        destination=destination,
        shift=shift,
        path=path,
        principal_destination=principal_destination,
        synthetic_moved=synthetic,
        gross_profit_usd=gross_usd,
        protocol_tax_usd=tax_usd,
        solver_reward_usd=solver_usd,
        protocol_hard_delta_usd=protocol_delta,
        external_lp_delta_usd=external_delta,
        conservation_error_usd=conservation,
        internal_after=nxt_i,
        external_after=nxt_e,
    )


def best_route_for_gradient(
    internal: Dict[str, List[float]],
    external: Dict[Tuple[str, str], ExternalPool],
    mark_usd: Dict[str, float],
    source: str,
    destination: str,
    shift: float,
    principal_steps: int = 80,
    profit_tax_share: float = 0.99,
    reward_floor_usd: float = 0.001,
    require_positive_hardnav: bool = True,
    objective: str = "protocol",
) -> Optional[Evaluation]:
    if principal_steps <= 0:
        raise ValueError("principal_steps must be positive")
    max_principal = internal[destination][1] * 0.70
    best: Optional[Evaluation] = None

    for i in range(1, principal_steps + 1):
        principal = max_principal * i / principal_steps
        for path in all_paths(source, destination):
            result = evaluate_gradient_route(
                internal,
                external,
                mark_usd,
                source,
                destination,
                shift,
                principal,
                path,
                profit_tax_share=profit_tax_share,
                reward_floor_usd=reward_floor_usd,
                close_gradient=True,
            )
            if result is None:
                continue
            if require_positive_hardnav and result.protocol_hard_delta_usd <= 0:
                continue

            score = (
                result.protocol_hard_delta_usd
                if objective == "protocol"
                else result.solver_reward_usd
            )
            if best is None:
                best = result
            else:
                best_score = (
                    best.protocol_hard_delta_usd
                    if objective == "protocol"
                    else best.solver_reward_usd
                )
                if score > best_score:
                    best = result
    return best


def best_no_gradient_route(
    internal: Dict[str, List[float]],
    external: Dict[Tuple[str, str], ExternalPool],
    mark_usd: Dict[str, float],
    principal_steps: int = 80,
    reward_floor_usd: float = 0.001,
) -> Optional[Evaluation]:
    """Best pre-gradient cross-market route. Used as the sub-threshold control."""
    best: Optional[Evaluation] = None
    for source in TOKENS:
        for destination in TOKENS:
            if source == destination:
                continue
            candidate = best_route_for_gradient(
                internal,
                external,
                mark_usd,
                source,
                destination,
                shift=0.0,
                principal_steps=principal_steps,
                reward_floor_usd=reward_floor_usd,
                require_positive_hardnav=False,
                objective="solver",
            )
            if candidate is None:
                continue
            if best is None or candidate.gross_profit_usd > best.gross_profit_usd:
                best = candidate
    return best


def best_rotation_candidate(
    internal: Dict[str, List[float]],
    external: Dict[Tuple[str, str], ExternalPool],
    mark_usd: Dict[str, float],
    shifts: Iterable[float] = (5, 10, 15, 20, 25, 30, 40, 50),
    principal_steps: int = 80,
    profit_tax_share: float = 0.99,
    reward_floor_usd: float = 0.001,
) -> Optional[Evaluation]:
    best: Optional[Evaluation] = None
    for source in TOKENS:
        for destination in TOKENS:
            if source == destination:
                continue
            for shift in shifts:
                if shift <= 0 or shift >= internal[source][0]:
                    continue
                candidate = best_route_for_gradient(
                    internal,
                    external,
                    mark_usd,
                    source,
                    destination,
                    shift,
                    principal_steps=principal_steps,
                    profit_tax_share=profit_tax_share,
                    reward_floor_usd=reward_floor_usd,
                    require_positive_hardnav=True,
                    objective="protocol",
                )
                if candidate is None:
                    continue
                if best is None or candidate.protocol_hard_delta_usd > best.protocol_hard_delta_usd:
                    best = candidate
    return best


def run_rotation(
    mark_multiplier: Optional[Dict[str, float]] = None,
    venue_multiplier: Optional[Dict[str, float]] = None,
    external_side_value_usd: float = 100_000.0,
    cycles: int = 10,
    shifts: Iterable[float] = (5, 10, 15, 20, 25, 30, 40, 50),
    principal_steps: int = 80,
    profit_tax_share: float = 0.99,
    reward_floor_usd: float = 0.001,
) -> Tuple[List[Cycle], float]:
    mark_usd = price_vector(mark_multiplier)
    venue_usd = price_vector(venue_multiplier or mark_multiplier)
    internal = make_internal(mark_usd)
    external = make_external(venue_usd, side_value_usd=external_side_value_usd)

    protocol_start = protocol_hard_value_usd(internal, mark_usd)
    external_start = external_value_usd(external, mark_usd)
    solver_cumulative = 0.0
    rows: List[Cycle] = []

    for n in range(1, cycles + 1):
        candidate = best_rotation_candidate(
            internal,
            external,
            mark_usd,
            shifts=shifts,
            principal_steps=principal_steps,
            profit_tax_share=profit_tax_share,
            reward_floor_usd=reward_floor_usd,
        )
        if candidate is None:
            break

        internal = candidate.internal_after
        external = candidate.external_after
        solver_cumulative += candidate.solver_reward_usd

        protocol_cumulative = protocol_hard_value_usd(internal, mark_usd) - protocol_start
        external_cumulative = external_value_usd(external, mark_usd) - external_start
        conservation = protocol_cumulative + external_cumulative + solver_cumulative
        if abs(conservation) > 1e-6:
            raise AssertionError(f"conservation error {conservation}")

        rows.append(Cycle(
            number=n,
            source=candidate.source,
            destination=candidate.destination,
            shift=candidate.shift,
            path=candidate.path,
            principal_destination=candidate.principal_destination,
            gross_profit_usd=candidate.gross_profit_usd,
            protocol_tax_usd=candidate.protocol_tax_usd,
            solver_reward_usd=candidate.solver_reward_usd,
            protocol_increment_usd=candidate.protocol_hard_delta_usd,
            protocol_cumulative_usd=protocol_cumulative,
            external_cumulative_usd=external_cumulative,
            solver_cumulative_usd=solver_cumulative,
            conservation_error_usd=conservation,
        ))

    return rows, external_cycle_upper_bound(external)


def main() -> None:
    aligned = {t: 1.0 for t in TOKENS}
    latent = {
        "USDT": 1.000,
        "USDC": 0.998,
        "DAI": 1.002,
        "WPOL": 1.003,
        "WETH": 0.997,
    }

    print("V13.1 corrected HardNAV audit")
    for name, venue in (("aligned", aligned), ("subthreshold_latent_basis", latent)):
        marks = aligned
        mark_usd = price_vector(marks)
        venue_usd = price_vector(venue)
        baseline = best_no_gradient_route(
            make_internal(mark_usd),
            make_external(venue_usd),
            mark_usd,
            principal_steps=80,
        )
        rows, cycle_bound = run_rotation(
            mark_multiplier=marks,
            venue_multiplier=venue,
            cycles=10,
            principal_steps=80,
        )
        print(f"\n{name}")
        print(f"external-only marginal cycle upper bound: {cycle_bound:.9f}x")
        print(f"profitable no-gradient route: {baseline is not None}")
        print(f"HardNAV-positive rotated cycles: {len(rows)}")
        if rows:
            final = rows[-1]
            print(f"protocol HardNAV delta: {final.protocol_cumulative_usd:+.6f} USD")
            print(f"external LP delta: {final.external_cumulative_usd:+.6f} USD")
            print(f"solver reward: {final.solver_cumulative_usd:.6f} USD")
            print(f"conservation error: {final.conservation_error_usd:+.12f} USD")
            for row in rows:
                print(
                    f"  #{row.number} {row.source}->{row.destination} shift={row.shift:.1f} "
                    f"path={'/'.join(row.path)} inc={row.protocol_increment_usd:+.6f} "
                    f"cum={row.protocol_cumulative_usd:+.6f}"
                )


if __name__ == "__main__":
    main()
