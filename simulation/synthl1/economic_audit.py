#!/usr/bin/env python3
"""Contract-realistic economic audit for SynthL1 V5.

This model is deliberately stricter than recursive_qe_mev.py:
- models GraphPool-style output toll, not an abstract 99% surplus capture;
- lets the searcher choose the trade size maximizing its own profit;
- separates protocol-owned LP scope from public LP scope;
- treats recycled USDx toll as recycled inventory, not hard profit;
- computes the external revenue required to make consolidated NAV non-negative.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Tuple
import copy

FEE = 0.003
Pool = Tuple[float, float]  # CORE, USDx


def price(pool: Pool) -> float:
    return pool[1] / pool[0]


def usdx_to_core(pool: Pool, amount: float) -> Tuple[Pool, float]:
    core_r, usd_r = pool
    effective = amount * (1.0 - FEE)
    core_out = core_r * effective / (usd_r + effective)
    return (core_r - core_out, usd_r + amount), core_out


def core_to_usdx(pool: Pool, amount: float) -> Tuple[Pool, float]:
    core_r, usd_r = pool
    effective = amount * (1.0 - FEE)
    usd_out = usd_r * effective / (core_r + effective)
    return (core_r + amount, usd_r - usd_out), usd_out


def analytic_pulse_wedge_pct(seed: float, reserve: float) -> float:
    """Exact spot wedge created by USDx->CORE on an initially 1:1 CPMM."""
    s = seed / reserve
    ratio = (1.0 + s) * (1.0 + (1.0 - FEE) * s)
    return (ratio - 1.0) * 100.0


def no_arb_ratio(output_toll: float) -> float:
    """Infinitesimal high/low price ratio required for a two-leg arb to be profitable."""
    return 1.0 / (((1.0 - FEE) ** 2) * (1.0 - output_toll))


@dataclass
class Arb:
    buy_pool: int
    sell_pool: int
    input_usdx: float
    gross_output_usdx: float
    toll_usdx: float
    bot_profit_usdx: float


def best_static_toll_arb(pools: List[Pool], output_toll: float, steps: int = 8000) -> Arb:
    prices = [price(p) for p in pools]
    buy = min(range(len(pools)), key=lambda i: prices[i])
    sell = max(range(len(pools)), key=lambda i: prices[i])
    max_usdx = pools[buy][1] * 0.70
    best = Arb(buy, sell, 0.0, 0.0, 0.0, 0.0)

    for i in range(1, steps + 1):
        q = max_usdx * i / steps
        _, core = usdx_to_core(pools[buy], q)
        _, gross = core_to_usdx(pools[sell], core)
        toll = gross * output_toll
        bot = gross - toll - q
        if bot > best.bot_profit_usdx:
            best = Arb(buy, sell, q, gross, toll, bot)
    return best


def execute_arb(pools: List[Pool], arb: Arb) -> List[Pool]:
    if arb.input_usdx == 0.0:
        return pools
    nxt = copy.deepcopy(pools)
    nxt[arb.buy_pool], core = usdx_to_core(nxt[arb.buy_pool], arb.input_usdx)
    nxt[arb.sell_pool], _ = core_to_usdx(nxt[arb.sell_pool], core)
    return nxt


@dataclass
class Row:
    cycle: int
    pulse: float
    wedge_pct: float
    toll: float
    bot_profit: float
    ecosystem_cnav_delta: float


def run_static_recursive(seed: float = 80.0, reserve: float = 100.0, pools_n: int = 15,
                         output_toll: float = 0.30, cycles: int = 30) -> List[Row]:
    """All internal pools are assumed 100% protocol-owned.

    Under that scope, the initial QE remains protocol-held treasury stock and does
    not by itself create an external USDx liability. External liability increases
    by the searcher's net USDx profit. Therefore closed-loop CNAV delta is the
    negative cumulative searcher profit (before gas/ops costs).
    """
    pools: List[Pool] = [(reserve, reserve) for _ in range(pools_n)]
    amount = seed
    bot_cumulative = 0.0
    rows: List[Row] = []

    for n in range(cycles):
        if amount <= 1e-9:
            break
        idx = n % pools_n
        pools[idx], _ = usdx_to_core(pools[idx], amount)
        prices = [price(p) for p in pools]
        wedge = (max(prices) / min(prices) - 1.0) * 100.0

        arb = best_static_toll_arb(pools, output_toll)
        pools = execute_arb(pools, arb)
        bot_cumulative += arb.bot_profit_usdx
        rows.append(Row(n + 1, amount, wedge, arb.toll_usdx, arb.bot_profit_usdx, -bot_cumulative))
        amount = arb.toll_usdx

        if arb.input_usdx == 0.0:
            break
    return rows


def initial_qe_external_liability(seed: float, protocol_lp_share: float) -> float:
    """Economic liability created when a QE pulse is placed into a partially public pool.

    For a 100% protocol-owned pulse pool this is zero treasury-stock leakage.
    For partial/public ownership, the public LP claim on newly minted USDx is external.
    """
    if not (0.0 <= protocol_lp_share <= 1.0):
        raise ValueError("protocol_lp_share must be in [0,1]")
    return seed * (1.0 - protocol_lp_share)


def required_external_revenue_for_break_even(rows: List[Row], ops_cost: float = 0.0) -> float:
    if not rows:
        return ops_cost
    return -rows[-1].ecosystem_cnav_delta + ops_cost


def main() -> None:
    rows = run_static_recursive()
    print(f"30% output toll no-arb band: {(no_arb_ratio(0.30)-1)*100:.4f}%")
    print(f"80/100 initializer wedge: {analytic_pulse_wedge_pct(80,100):.4f}%")
    print(f"cycles: {len(rows)}")
    print(f"cumulative recycled toll: {sum(r.toll for r in rows):.6f} USDx")
    print(f"cumulative searcher leakage: {sum(r.bot_profit for r in rows):.6f} USDx")
    print(f"closed-loop CNAV delta: {rows[-1].ecosystem_cnav_delta:+.6f} USD")
    print(f"external revenue needed for break-even: {required_external_revenue_for_break_even(rows):.6f} USD")
    print("partial LP initial-liability examples:")
    for share in (1.0, 0.5, 0.0):
        print(f"  protocol LP={share:>4.0%}: {initial_qe_external_liability(80,share):.2f} USDx external liability")


if __name__ == "__main__":
    main()
