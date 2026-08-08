#!/usr/bin/env python3
"""SynthL1 V5.2 recursive QE/MEV reference model.

Exact loop:
  initial QE USDx -> CORE buyback+burn -> graph wedge -> taxed searcher arb ->
  protocol USDx realized-profit tax -> tax reinvested into next buyback+burn -> repeat.

The protocol tax is adaptive: `capture_share` is a ceiling, while the model leaves
an explicit solver compensation floor equal to gas + requested risk/reward. This
matches GraphArbExecutor V5.2, where a 99% maximum tax is reduced automatically
when needed to preserve a configured solver reward floor.

The model intentionally separates recycled tax turnover from hard economic profit
and explicitly caps the external USDx principal available to the searcher.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Tuple
import copy
import math

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


def best_profit_tax_arb(
    pools: List[Pool],
    max_profit_tax_share: float,
    searcher_gas_usdx: float = 0.0,
    min_searcher_reward_usdx: float = 0.0,
    external_principal_cap_usdx: float = math.inf,
):
    """Searcher-optimal route under an adaptive proportional tax on REALIZED profit.

    The gross-profit-maximizing route is found first. The protocol then captures
    at most `max_profit_tax_share` of gross profit, but reduces the tax if needed
    to leave `searcher_gas_usdx + min_searcher_reward_usdx` to the solver.

    This is a model of a protocol-configured reward floor. A searcher cannot lower
    the tax merely by asking for a larger reward; the floor is policy input.
    """
    if not (0.0 <= max_profit_tax_share < 1.0):
        raise ValueError("max_profit_tax_share must be in [0,1)")
    if external_principal_cap_usdx < 0:
        raise ValueError("external_principal_cap_usdx must be non-negative")

    prices = [price(p) for p in pools]
    buy = min(range(len(pools)), key=lambda i: prices[i])
    sell = max(range(len(pools)), key=lambda i: prices[i])
    max_usdx = min(pools[buy][1] * 0.70, external_principal_cap_usdx)
    if max_usdx <= 0:
        return pools, 0.0, 0.0, 0.0, 0.0, 0.0

    best = None
    for i in range(1, 4001):
        q = max_usdx * i / 4000
        _, core = usdx_to_core(pools[buy], q)
        _, out = core_to_usdx(pools[sell], core)
        gross = out - q
        if gross <= 0:
            continue
        if best is None or gross > best[0]:
            best = (gross, q)

    if best is None:
        return pools, 0.0, 0.0, 0.0, 0.0, 0.0

    gross, q = best
    compensation_floor = searcher_gas_usdx + min_searcher_reward_usdx
    if gross <= compensation_floor:
        return pools, 0.0, 0.0, gross, gross - searcher_gas_usdx, q

    max_tax = max_profit_tax_share * gross
    tax_leaving_floor = gross - compensation_floor
    protocol_tax = min(max_tax, tax_leaving_floor)
    searcher_reward = gross - protocol_tax
    searcher_net_after_gas = searcher_reward - searcher_gas_usdx

    if searcher_net_after_gas < min_searcher_reward_usdx or searcher_net_after_gas <= 0:
        return pools, 0.0, 0.0, gross, searcher_net_after_gas, q

    next_pools = copy.deepcopy(pools)
    next_pools[buy], core = usdx_to_core(next_pools[buy], q)
    next_pools[sell], out = core_to_usdx(next_pools[sell], core)
    gross = out - q

    max_tax = max_profit_tax_share * gross
    tax_leaving_floor = max(0.0, gross - compensation_floor)
    protocol_tax = min(max_tax, tax_leaving_floor)
    searcher_reward = gross - protocol_tax
    searcher_net_after_gas = searcher_reward - searcher_gas_usdx
    return next_pools, protocol_tax, searcher_reward, gross, searcher_net_after_gas, q


@dataclass
class Cycle:
    number: int
    pulse_usdx: float
    pre_wedge_pct: float
    searcher_principal_usdx: float
    tax_usdx: float
    searcher_reward_usdx: float
    searcher_net_after_gas_usdx: float
    gross_arb_surplus_usdx: float
    core_burned: float
    hard_nav_delta_usd: float


def run(
    seed: float = 80.0,
    reserve: float = 100.0,
    pools_n: int = 15,
    capture_share: float = 0.99,
    cycles: int = 30,
    external_topup: float = 0.0,
    searcher_gas_usdx: float = 0.0,
    min_searcher_reward_usdx: float = 0.0,
    external_principal_cap_usdx: float = math.inf,
) -> List[Cycle]:
    pools: List[Pool] = [(reserve, reserve) for _ in range(pools_n)]
    amount = seed
    searcher_cumulative = 0.0
    rows: List[Cycle] = []

    for n in range(cycles):
        if amount <= 1e-9:
            break
        pools, core_burned = pulse(pools, n % pools_n, amount)
        prices = [price(p) for p in pools]
        wedge = (max(prices) / min(prices) - 1.0) * 100.0
        pools, tax, reward, gross, net_after_gas, principal = best_profit_tax_arb(
            pools,
            capture_share,
            searcher_gas_usdx=searcher_gas_usdx,
            min_searcher_reward_usdx=min_searcher_reward_usdx,
            external_principal_cap_usdx=external_principal_cap_usdx,
        )
        searcher_cumulative += reward
        rows.append(Cycle(
            number=n + 1,
            pulse_usdx=amount,
            pre_wedge_pct=wedge,
            searcher_principal_usdx=principal,
            tax_usdx=tax,
            searcher_reward_usdx=reward,
            searcher_net_after_gas_usdx=net_after_gas,
            gross_arb_surplus_usdx=gross,
            core_burned=core_burned,
            hard_nav_delta_usd=-searcher_cumulative,
        ))
        if tax <= 0:
            break
        # Strict recursion: no fresh mint after the initializer.
        amount = tax + external_topup

    return rows


def summary(rows: List[Cycle], seed: float) -> dict:
    if not rows:
        return {}
    return {
        "seed": seed,
        "cycles": len(rows),
        "initial_wedge_pct": rows[0].pre_wedge_pct,
        "first_searcher_principal": rows[0].searcher_principal_usdx,
        "max_searcher_principal": max(r.searcher_principal_usdx for r in rows),
        "first_tax": rows[0].tax_usdx,
        "first_recycle_efficiency_pct": rows[0].tax_usdx / seed * 100.0,
        "cumulative_recycled_tax": sum(r.tax_usdx for r in rows),
        "cumulative_searcher_reward": sum(r.searcher_reward_usdx for r in rows),
        "cumulative_core_burned": sum(r.core_burned for r in rows),
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
            f"firstPrincipal={s['first_searcher_principal']:10.6f}  "
            f"firstTax={s['first_tax']:10.6f}  "
            f"recycled={s['cumulative_recycled_tax']:10.6f}  "
            f"burned={s['cumulative_core_burned']:10.6f}  "
            f"hardNAV={s['final_hard_nav_delta']:+.6f}"
        )


if __name__ == "__main__":
    main()
