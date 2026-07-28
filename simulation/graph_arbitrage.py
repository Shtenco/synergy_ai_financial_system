"""Deterministic constant-product graph arbitrage and QE accounting model.

All arithmetic is integer based. A route is accepted only when it starts and
ends in USDT and repays the simulated flash-loan fee. Token QE is accounted at
zero external reserve value; paired stablecoin/POL capital is charged to LNAV.
"""

from dataclasses import dataclass, replace
from itertools import permutations

BPS = 10_000


@dataclass(frozen=True)
class Pool:
    token0: str
    token1: str
    reserve0: int
    reserve1: int
    fee_bps: int = 30
    tax0_bps: int = 0
    tax1_bps: int = 0

    def swap(self, token_in: str, amount: int) -> tuple["Pool", int]:
        if token_in == self.token0:
            reserve_in, reserve_out = self.reserve0, self.reserve1
            tax = self.tax0_bps
            reverse = False
        elif token_in == self.token1:
            reserve_in, reserve_out = self.reserve1, self.reserve0
            tax = self.tax1_bps
            reverse = True
        else:
            raise ValueError("token is not in pool")
        received = amount * (BPS - tax) // BPS
        effective = received * (BPS - self.fee_bps)
        output_before_tax = effective * reserve_out // (reserve_in * BPS + effective)
        token_out_tax = self.tax0_bps if reverse else self.tax1_bps
        output = output_before_tax * (BPS - token_out_tax) // BPS
        if reverse:
            return replace(self, reserve1=reserve_in + received, reserve0=reserve_out - output_before_tax), output
        return replace(self, reserve0=reserve_in + received, reserve1=reserve_out - output_before_tax), output


@dataclass(frozen=True)
class Opportunity:
    route: tuple[str, ...]
    amount_in: int
    amount_out: int
    flash_fee: int

    @property
    def profit(self) -> int:
        return self.amount_out - self.amount_in - self.flash_fee


class MarketGraph:
    def __init__(self, pools: list[Pool]):
        self.pools = pools

    def _pool_index(self, a: str, b: str) -> int | None:
        for index, pool in enumerate(self.pools):
            if {a, b} == {pool.token0, pool.token1}:
                return index
        return None

    def execute(self, route: tuple[str, ...], amount: int) -> tuple["MarketGraph", int]:
        pools = list(self.pools)
        for token_in, token_out in zip(route, route[1:]):
            index = MarketGraph(pools)._pool_index(token_in, token_out)
            if index is None:
                raise ValueError(f"missing edge {token_in}/{token_out}")
            pools[index], amount = pools[index].swap(token_in, amount)
        return MarketGraph(pools), amount

    def best_usdt_cycle(self, amounts: tuple[int, ...], flash_fee_bps: int = 9) -> Opportunity | None:
        tokens = sorted({token for p in self.pools for token in (p.token0, p.token1)} - {"USDT"})
        best = None
        for hops in (2, 3, 4):
            for middle in permutations(tokens, hops - 1):
                route = ("USDT", *middle, "USDT")
                if any(self._pool_index(a, b) is None for a, b in zip(route, route[1:])):
                    continue
                for amount in amounts:
                    _, output = self.execute(route, amount)
                    candidate = Opportunity(route, amount, output, amount * flash_fee_bps // BPS)
                    if candidate.profit > 0 and (best is None or candidate.profit > best.profit):
                        best = candidate
        return best


def polygon_contour(syna_tax_bps: int = 4_000, synr_tax_bps: int = 4_000) -> MarketGraph:
    """Representative connected contour; units use six-decimal quote precision."""
    m = 10**6
    return MarketGraph([
        Pool("USDS", "USDT", 5_000_000*m, 5_000_000*m, fee_bps=5),
        Pool("WPOL", "USDT", 1_000_000*m, 400_000*m),
        Pool("SYNA", "WPOL", 350_000*m, 1_000*m, tax0_bps=syna_tax_bps),
        Pool("SYNR", "WPOL", 150_000*m, 2_000*m, tax0_bps=synr_tax_bps),
        Pool("SYNA", "SYNR", 300_000*m, 120_000*m, tax0_bps=syna_tax_bps, tax1_bps=synr_tax_bps),
        Pool("SYNA", "USDS", 400_000*m, 1_200*m, tax0_bps=syna_tax_bps),
        Pool("SYNR", "USDT", 100_000*m, 1_400*m, tax0_bps=synr_tax_bps),
    ])


def qe_external_cost(token: str, amount: int, paired_reserve: int) -> int:
    """External LNAV cost: self-issued tokens cost zero; reserve assets do not."""
    if token in {"SYNA", "SYNR"}:
        return paired_reserve
    return amount + paired_reserve
