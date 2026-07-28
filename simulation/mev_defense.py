"""Compare public-mempool sandwich extraction with sealed route execution."""

from simulation.graph_arbitrage import Pool


def sandwich_profit(pool: Pool, victim_token_in: str, victim_amount: int, front_amount: int) -> int:
    """Return attacker profit in victim input token for a three-swap sandwich."""
    after_front, attacker_asset = pool.swap(victim_token_in, front_amount)
    after_victim, _ = after_front.swap(victim_token_in, victim_amount)
    token_out = pool.token1 if victim_token_in == pool.token0 else pool.token0
    _, attacker_back = after_victim.swap(token_out, attacker_asset)
    return attacker_back - front_amount


def best_sandwich(pool: Pool, victim_token_in: str, victim_amount: int) -> dict[str, int]:
    sizes = (victim_amount // 100, victim_amount // 50, victim_amount // 20,
             victim_amount // 10, victim_amount // 5, victim_amount // 2)
    profits = [(size, sandwich_profit(pool, victim_token_in, victim_amount, size)) for size in sizes]
    size, profit = max(profits, key=lambda item: item[1])
    return {"front_amount": size, "attacker_profit": max(0, profit)}


def sealed_batch_result(expired_solver_bond: int = 0) -> dict[str, int]:
    """No route leakage means no modeled sandwich; expired voluntary bonds accrue."""
    return {"sandwich_profit": 0, "treasury_slash_revenue": expired_solver_bond}


def taxed_round_trip_retention(amount: int, tax_bps: int = 2_000) -> int:
    """Two uniformly taxed transfers, before AMM fees and price impact."""
    after_entry = amount * (10_000 - tax_bps) // 10_000
    return after_entry * (10_000 - tax_bps) // 10_000
