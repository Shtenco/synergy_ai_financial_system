#!/usr/bin/env python3
"""SynthL1 V5 recursive QE/MEV reference model.

Exact loop:
  initial QE USDx -> CORE buyback+burn -> graph wedge -> searcher arb ->
  protocol USDx toll -> toll reinvested into next buyback+burn -> repeat.

The model intentionally separates recycled toll turnover from hard economic profit.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Tuple
import copy

FEE = 0.003
Pool = Tuple[float, float]  # CORE, USDx


def price(pool: Pool) -> float:
    core, usdx = pool
    return usdx / core


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


def pulse(pools: List[Pool], index: int, usdx: float) -> Tuple[List[Pool], float]:
    next_pools = copy.deepcopy(pools)
    next_pools[index], core_burned = usdx_to_core(next_pools[index], usdx)
    return next_pools, core_burned


def best_managed_arb(pools: List[Pool], capture_share: float):
    """Idealized managed-fee/auction upper bound.

    The protocol captures `capture_share` of gross arbitrage surplus while the
    searcher keeps the remainder. This is not a claim that a static on-chain
    percentage can perfectly extract that amount.
    """
    prices = [price(p) for p in pools]
    buy = min(range(len(pools)), key=lambda i: prices[i])
    sell = max(range(len(pools)), key=lambda i: prices[i])
    max_usdx = pools[buy][1] * 0.70
    best = None

    for i in range(1, 4001):
        q = max_usdx * i / 4000
        _, core = usdx_to_core(pools[buy], q)
        _, out = core_to_usdx(pools[sell], core)
        gross = out - q
        if gross <= 0:
            continue
        bot = (1.0 - capture_share) * gross
        if best is None or bot > best[0]:
            best = (bot, q, core, gross)

    if best is None:
        return pools, 0.0, 0.0, 0.0

    bot, q, _, _ = best
    next_pools = copy.deepcopy(pools)
    next_pools[buy], core = usdx_to_core(next_pools[buy], q)
    next_pools[sell], out = core_to_usdx(next_pools[sell], core)
    gross = out - q
    toll = capture_share * gross
    bot = (1.0 - capture_share) * gross
    return next_pools, toll, bot, gross


@dataclass
class Cycle:
    number: int
    pulse_usdx: float
    pre_wedge_pct: float
    toll_usdx: float
    bot_profit_usdx: float
    gross_arb_surplus_usdx: float
    hard_nav_delta_usd: float


def run(seed: float = 80.0, reserve: float = 100.0, pools_n: int = 15,
        capture_share: float = 0.99, cycles: int = 30,
        external_topup: float = 0.0) -> List[Cycle]:
    pools: List[Pool] = [(reserve, reserve) for _ in range(pools_n)]
    amount = seed
    bot_cumulative = 0.0
    rows: List[Cycle] = []

    for n in range(cycles):
        if amount <= 1e-9:
            break
        pools, _ = pulse(pools, n % pools_n, amount)
        prices = [price(p) for p in pools]
        wedge = (max(prices) / min(prices) - 1.0) * 100.0
        pools, toll, bot, gross = best_managed_arb(pools, capture_share)
        bot_cumulative += bot
        rows.append(Cycle(
            number=n + 1,
            pulse_usdx=amount,
            pre_wedge_pct=wedge,
            toll_usdx=toll,
            bot_profit_usdx=bot,
            gross_arb_surplus_usdx=gross,
            hard_nav_delta_usd=-bot_cumulative,
        ))
        # Strict recursion: no fresh mint after the initializer.
        amount = toll + external_topup

    return rows


def summary(rows: List[Cycle], seed: float) -> dict:
    if not rows:
        return {}
    return {
        "seed": seed,
        "cycles": len(rows),
        "initial_wedge_pct": rows[0].pre_wedge_pct,
        "first_toll": rows[0].toll_usdx,
        "first_recycle_efficiency_pct": rows[0].toll_usdx / seed * 100.0,
        "cumulative_recycled_toll": sum(r.toll_usdx for r in rows),
        "cumulative_searcher_profit": sum(r.bot_profit_usdx for r in rows),
        "final_hard_nav_delta": rows[-1].hard_nav_delta_usd,
        "last_pulse": rows[-1].pulse_usdx,
    }


def main() -> None:
    for seed in (20.0, 80.0, 500.0):
        rows = run(seed=seed, capture_share=0.99)
        s = summary(rows, seed)
        print(
            f"seed={seed:7.2f}  cycles={s['cycles']:2d}  "
            f"wedge={s['initial_wedge_pct']:9.2f}%  "
            f"first_toll={s['first_toll']:10.6f}  "
            f"recycled={s['cumulative_recycled_toll']:10.6f}  "
            f"hardNAV={s['final_hard_nav_delta']:+.6f}"
        )


if __name__ == "__main__":
    main()
