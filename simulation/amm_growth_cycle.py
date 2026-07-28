"""Integer-exact Uniswap V2-style model for the proposed LP recycling cycle.

This is deliberately accounting-conservative: minted governance tokens are not
booked as profit. A closed AMM loop cannot manufacture external reserve value.
"""

from dataclasses import dataclass

BPS = 10_000


@dataclass(frozen=True)
class State:
    base_reserve: int
    quote_reserve: int
    lp_supply: int
    treasury_lp: int
    treasury_base: int = 0
    treasury_quote: int = 0
    dead_lp: int = 0

    def reserve_lnav_quote(self) -> int:
        """External reserve NAV, excluding self-issued base tokens."""
        return self.quote_reserve + self.treasury_quote


def amount_out(amount_in: int, reserve_in: int, reserve_out: int, fee_bps: int = 30) -> int:
    if min(amount_in, reserve_in, reserve_out) <= 0:
        raise ValueError("amount and reserves must be positive")
    amount_in_with_fee = amount_in * (BPS - fee_bps)
    return amount_in_with_fee * reserve_out // (reserve_in * BPS + amount_in_with_fee)


def cycle(state: State, remove_bps: int = 1_500, burn_bps: int = 1_000) -> State:
    """Remove LP, lock LP at the dead address, buy back, mint, and add LP."""
    remove_lp = state.treasury_lp * remove_bps // BPS
    burn_lp = state.treasury_lp * burn_bps // BPS
    if remove_lp == 0 or burn_lp == 0:
        raise ValueError("cycle below executable precision: treasury LP is exhausted")
    if remove_lp + burn_lp > state.treasury_lp:
        raise ValueError("cycle exceeds treasury LP")

    removed_base = state.base_reserve * remove_lp // state.lp_supply
    removed_quote = state.quote_reserve * remove_lp // state.lp_supply
    base_r = state.base_reserve - removed_base
    quote_r = state.quote_reserve - removed_quote
    supply = state.lp_supply - remove_lp

    buy_quote = removed_quote // 2
    if buy_quote == 0:
        raise ValueError("cycle below executable precision: released quote is exhausted")
    bought_base = amount_out(buy_quote, quote_r, base_r)
    quote_r += buy_quote
    base_r -= bought_base

    available_base = removed_base + bought_base
    available_quote = removed_quote - buy_quote
    # A V2 router deposits at the existing ratio and returns unused excess.
    base_for_quote = available_quote * base_r // quote_r
    add_base = min(available_base * 2, base_for_quote)
    add_quote = min(available_quote, add_base * quote_r // base_r)
    minted_lp = min(add_base * supply // base_r, add_quote * supply // quote_r)

    return State(
        base_reserve=base_r + add_base,
        quote_reserve=quote_r + add_quote,
        lp_supply=supply + minted_lp,
        treasury_lp=state.treasury_lp - remove_lp - burn_lp + minted_lp,
        treasury_base=state.treasury_base + available_base * 2 - add_base,
        treasury_quote=state.treasury_quote + available_quote - add_quote,
        dead_lp=state.dead_lp + burn_lp,
    )
