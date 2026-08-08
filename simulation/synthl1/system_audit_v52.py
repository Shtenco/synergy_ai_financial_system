#!/usr/bin/env python3
"""SynthL1 V5.2 system-level economic audit.

This model adds two accounting views that must not be mixed:

1. Hard CNAV
   real hard assets - externally held USDx liabilities.

2. Liquid economic NAV delta
   hard-CNAV delta - haircut * external executable CORE price * CORE burned.

The second metric is intentionally conservative: it treats burned protocol-owned
CORE as lost liquid inventory at an external executable price. It does not assume
that supply reduction automatically raises the price of remaining CORE.

The recursive pulse remains strict:
  initial internal USDx QE -> buy CORE -> burn -> wedge -> searcher arb ->
  adaptive realized-profit tax -> captured USDx -> next pulse.

Independent external revenue is accounted separately from self-wedge recycling.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Tuple
import copy
import math

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


def pulse_wedge_pct(seed: float, reserve: float) -> float:
    s = seed / reserve
    return ((1.0 + s) * (1.0 + (1.0 - FEE) * s) - 1.0) * 100.0


def first_pulse_core_burn_fraction(seed: float, reserve: float) -> float:
    s = seed / reserve
    return ((1.0 - FEE) * s) / (1.0 + (1.0 - FEE) * s)


@dataclass
class ArbQuote:
    buy_pool: int
    sell_pool: int
    principal: float
    gross_profit: float


def best_gross_arb(pools: List[Pool], external_principal_cap: float = math.inf, steps: int = 4000) -> ArbQuote:
    prices = [price(p) for p in pools]
    buy = min(range(len(pools)), key=lambda i: prices[i])
    sell = max(range(len(pools)), key=lambda i: prices[i])
    max_usdx = min(pools[buy][1] * 0.70, external_principal_cap)
    best = ArbQuote(buy, sell, 0.0, 0.0)
    if max_usdx <= 0:
        return best

    for i in range(1, steps + 1):
        q = max_usdx * i / steps
        _, core = usdx_to_core(pools[buy], q)
        _, out = core_to_usdx(pools[sell], core)
        gross = out - q
        if gross > best.gross_profit:
            best = ArbQuote(buy, sell, q, gross)
    return best


@dataclass
class Cycle:
    number: int
    pulse_usdx: float
    pre_wedge_pct: float
    searcher_principal_usdx: float
    gross_arb_profit_usdx: float
    protocol_tax_usdx: float
    searcher_reward_usdx: float
    core_burned: float
    cumulative_core_burned: float
    hard_assets_usd: float
    external_usdx_liability: float
    hard_cnav_delta_usd: float
    liquid_economic_nav_delta_usd: float
    coverage_ratio: float


def run_system(
    seed: float = 80.0,
    reserve: float = 100.0,
    pools_n: int = 15,
    max_profit_tax_share: float = 0.99,
    solver_reward_floor_usdx: float = 0.01,
    external_principal_cap_usdx: float = math.inf,
    hard_assets_start_usd: float = 5.0,
    external_hard_revenue_per_cycle_usd: float = 0.0,
    system_cost_per_cycle_usd: float = 0.0,
    external_core_price_usd: float = 1.0,
    core_nav_haircut: float = 0.0,
    cycles: int = 50,
) -> List[Cycle]:
    if not (0.0 <= max_profit_tax_share < 1.0):
        raise ValueError("max_profit_tax_share must be in [0,1)")
    if not (0.0 <= core_nav_haircut <= 1.0):
        raise ValueError("core_nav_haircut must be in [0,1]")
    if hard_assets_start_usd < 0:
        raise ValueError("hard_assets_start_usd must be non-negative")

    pools: List[Pool] = [(reserve, reserve) for _ in range(pools_n)]
    pulse_amount = seed
    hard_assets = hard_assets_start_usd
    external_liability = 0.0
    cumulative_core_burned = 0.0
    rows: List[Cycle] = []

    for n in range(cycles):
        if pulse_amount <= 1e-12:
            break

        pulse_index = n % pools_n
        pools[pulse_index], core_burned = usdx_to_core(pools[pulse_index], pulse_amount)
        cumulative_core_burned += core_burned

        prices = [price(p) for p in pools]
        wedge = (max(prices) / min(prices) - 1.0) * 100.0

        quote = best_gross_arb(pools, external_principal_cap_usdx)

        # External hard revenue and system-paid costs are independent of self-wedge tax.
        hard_assets += external_hard_revenue_per_cycle_usd - system_cost_per_cycle_usd

        protocol_tax = 0.0
        searcher_reward = 0.0
        if quote.gross_profit > solver_reward_floor_usdx and quote.principal > 0:
            max_tax = max_profit_tax_share * quote.gross_profit
            tax_leaving_floor = quote.gross_profit - solver_reward_floor_usdx
            protocol_tax = min(max_tax, tax_leaving_floor)
            searcher_reward = quote.gross_profit - protocol_tax

            pools[quote.buy_pool], core = usdx_to_core(pools[quote.buy_pool], quote.principal)
            pools[quote.sell_pool], _ = core_to_usdx(pools[quote.sell_pool], core)

            # The retained searcher reward is newly externalized USDx liability.
            external_liability += searcher_reward

        hard_cnav = hard_assets - external_liability
        hard_cnav_delta = hard_cnav - hard_assets_start_usd

        # Conservative liquid-inventory view: no assumed price appreciation from burn.
        liquid_economic_delta = hard_cnav_delta - (
            cumulative_core_burned * external_core_price_usd * core_nav_haircut
        )

        coverage = math.inf if external_liability <= 0 else hard_assets / external_liability

        rows.append(Cycle(
            number=n + 1,
            pulse_usdx=pulse_amount,
            pre_wedge_pct=wedge,
            searcher_principal_usdx=quote.principal,
            gross_arb_profit_usdx=quote.gross_profit,
            protocol_tax_usdx=protocol_tax,
            searcher_reward_usdx=searcher_reward,
            core_burned=core_burned,
            cumulative_core_burned=cumulative_core_burned,
            hard_assets_usd=hard_assets,
            external_usdx_liability=external_liability,
            hard_cnav_delta_usd=hard_cnav_delta,
            liquid_economic_nav_delta_usd=liquid_economic_delta,
            coverage_ratio=coverage,
        ))

        if protocol_tax <= 0:
            break
        pulse_amount = protocol_tax

    return rows


def required_external_revenue_for_target(
    rows: List[Cycle],
    starting_hard_capital: float,
    target_return: float = 0.10,
    include_core_opportunity_cost: bool = False,
) -> float:
    if not rows:
        return starting_hard_capital * target_return
    leakage = rows[-1].external_usdx_liability
    target_gain = starting_hard_capital * target_return
    required = target_gain + leakage
    if include_core_opportunity_cost:
        required += max(0.0, -rows[-1].liquid_economic_nav_delta_usd - leakage)
    return required


def main() -> None:
    print("SynthL1 V5.2 dual-NAV economic audit")
    print(f"80/100 initial wedge: {pulse_wedge_pct(80,100):.3f}%")
    print(f"80/100 first-pulse CORE burn: {first_pulse_core_burn_fraction(80,100)*100:.3f}% of target pool")
    print(f"500/100 first-pulse CORE burn: {first_pulse_core_burn_fraction(500,100)*100:.3f}% of target pool")

    for haircut in (0.0, 0.25, 0.50, 1.0):
        rows = run_system(core_nav_haircut=haircut)
        final = rows[-1]
        print(
            f"haircut={haircut:>4.0%} cycles={len(rows):2d} "
            f"tax={sum(r.protocol_tax_usdx for r in rows):.6f} "
            f"searcherLeak={final.external_usdx_liability:.6f} "
            f"COREburn={final.cumulative_core_burned:.6f} "
            f"hardDelta={final.hard_cnav_delta_usd:+.6f} "
            f"liquidDelta={final.liquid_economic_nav_delta_usd:+.6f}"
        )

    scaled = run_system(
        seed=5.0,
        reserve=6.25,
        hard_assets_start_usd=5.0,
        solver_reward_floor_usdx=0.001,
        core_nav_haircut=0.0,
    )
    needed = required_external_revenue_for_target(scaled, 5.0, 0.10)
    print(f"scaled $5 reference: independent external value needed for $5->$5.5 = {needed:.6f} USD + system costs")


if __name__ == "__main__":
    main()
