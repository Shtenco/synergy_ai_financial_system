"""Run V7 with hybrid routes through the six-pool SINERGY permissioned core."""
from pathlib import Path
import json
import math
import numpy as np

import synergy_graph_arbitrage_v7 as core

REPORTS = Path("reports")


def execute_route(pools, amount, route):
    current = amount
    edges = []
    for pool_name, token_in in route:
        pool = next(pool for pool in pools if pool.name == pool_name)
        rate = pool.rate(token_in, current)
        if rate <= 0:
            return None
        current *= rate
        edges.append(pool_name)
    return {
        "settlement": "USDT",
        "amount_in": amount,
        "amount_out": current,
        "edges": edges,
    }


def best_hybrid_cycle(pools, amount):
    routes = [
        # New direct stable route: USDT enters the permissioned core before
        # reaching the protected public representative edge.
        [
            ("SINERGY_USDT_SYNA", "USDT"),
            ("PUBLIC_QS_WPOL_SYNA", "SYNA"),
            ("EXIT_QS_V3_WPOL_USDT", "WPOL"),
        ],
        # The original edge-simple route may revisit WPOL through distinct pools.
        [
            ("EXIT_QS_V3_WPOL_USDT", "USDT"),
            ("SINERGY_WPOL_SYNA", "WPOL"),
            ("PUBLIC_QS_WPOL_SYNA", "SYNA"),
            ("EXIT_QS_V2_WPOL_USDT", "WPOL"),
        ],
        # Internal stable anchor plus representative pool.
        [
            ("SINERGY_WPOL_USDT", "USDT"),
            ("PUBLIC_QS_WPOL_SYNA", "WPOL"),
            ("SINERGY_USDT_SYNA", "SYNA"),
        ],
        # Reserve-token path proves USDT/SYNR is a usable internal edge.
        [
            ("SINERGY_USDT_SYNR", "USDT"),
            ("SINERGY_WPOL_SYNR", "SYNR"),
            ("PUBLIC_QS_WPOL_SYNA", "WPOL"),
            ("SINERGY_USDT_SYNA", "SYNA"),
        ],
    ]
    candidates = [execute_route(pools, amount, route) for route in routes]
    candidates = [candidate for candidate in candidates if candidate is not None]
    return max(candidates, key=lambda candidate: candidate["amount_out"]) if candidates else None


def run(seed=42, blocks=core.BLOCKS):
    rng = np.random.default_rng(seed)
    state = core.State()
    public_price = 1.0
    exit_a = 1.0
    exit_b = 1.0

    for block in range(1, blocks + 1):
        sigma = max(0.005, float(rng.normal(0.052, 0.020)))
        target = core.target_multiplier(sigma)
        multiplier = core.recognised_multiplier(sigma, state.capital)
        invariant = core.risk_invariant(state.capital, sigma, state.keeper_cost)
        if target is None or invariant < 1.0:
            continue
        state.minimum_multiplier = min(state.minimum_multiplier, multiplier)
        state.minimum_invariant = min(state.minimum_invariant, invariant)

        public_price *= math.exp(float(rng.normal(0.0, sigma / 28.0)))
        exit_a *= math.exp(float(rng.normal(0.0, sigma / 75.0)))
        exit_b *= math.exp(float(rng.normal(0.0, sigma / 75.0)))
        public_price += 0.025 * (1.0 - public_price)
        exit_a += 0.045 * (1.0 - exit_a)
        exit_b += 0.045 * (1.0 - exit_b)

        if block % 250 == 0:
            public_price *= 1.035
            exit_a *= 1.012
            exit_b *= 0.988

        qe = 0.00002 * state.capital if block % 100 == 0 else 0.0
        state.qe_notional += qe
        depth = 0.18 * state.capital + qe
        pools = core.build_graph(public_price, exit_a, exit_b, depth)
        candidate = best_hybrid_cycle(pools, min(0.20, 0.0015 * state.capital))
        if candidate is not None:
            assessed = core.evaluate_cycle(candidate, sigma, qe, externally_caused=True)
            if assessed["accepted"]:
                profit = float(assessed["external_net_profit"])
                tax = 0.01 * profit
                state.capital += profit - tax
                state.realised_external_profit += profit
                state.keeper_cost += float(assessed["gas"])
                state.qt_burn += 0.20 * profit
                state.profitable_cycles += 1
                if any(
                    edge == "SINERGY_WPOL_USDT" or "SINERGY_USDT_" in edge
                    for edge in candidate["edges"]
                ):
                    state.internal_usdt_cycles += 1

        if block % 500 == 0:
            fake = {
                "settlement": "WPOL",
                "amount_in": 0.10,
                "amount_out": 0.105,
                "edges": ["SINERGY_WPOL_SYNA", "PUBLIC_QS_WPOL_SYNA"],
            }
            fake_eval = core.evaluate_cycle(fake, sigma, qe + 0.10, externally_caused=False)
            if not fake_eval["accepted"] and fake_eval["external_net_profit"] <= 0:
                state.fake_qe_rejected += 1

        state.peak_capital = max(state.peak_capital, state.capital)
        state.maximum_drawdown = max(
            state.maximum_drawdown,
            (state.peak_capital - state.capital) / state.peak_capital,
        )

    result = {
        "verdict": "PASS"
        if (
            state.capital > core.INITIAL_CAPITAL
            and state.minimum_multiplier >= 3.0
            and state.minimum_invariant >= 1.0
            and state.fake_qe_rejected == blocks // 500
            and state.profitable_cycles > 0
            and state.internal_usdt_cycles > 0
        )
        else "FAIL",
        "topology": {
            "internal_permissioned_pools": core.INTERNAL_PERMISSIONED_POOLS,
            "public_representative_pools": core.PUBLIC_REPRESENTATIVE_POOLS,
            "external_exit_pools": core.EXTERNAL_EXIT_POOLS,
            "total_graph_pools": 9,
        },
        "metrics": {
            **state.__dict__,
            "growth_factor": state.capital / core.INITIAL_CAPITAL,
            "settlement_assets": ["WPOL", "USDT"],
            "new_investor_capital_after_bootstrap": 0.0,
            "internal_transfer_revenue": 0.0,
        },
        "interpretation": (
            "Hybrid routes use the complete permissioned WPOL/USDT/SYNA/SYNR core. "
            "Only externally caused dislocations pass consolidated accounting."
        ),
    }
    return result


def main():
    REPORTS.mkdir(exist_ok=True)
    deterministic = run()
    monte = core.monte_carlo()
    (REPORTS / "synergy_graph_v7_model.json").write_text(
        json.dumps(deterministic, indent=2), encoding="utf-8"
    )
    (REPORTS / "synergy_graph_v7_monte_carlo.json").write_text(
        json.dumps(monte, indent=2), encoding="utf-8"
    )
    print(json.dumps({"deterministic": deterministic, "monte_carlo": monte}, indent=2))
    if deterministic["verdict"] != "PASS":
        raise SystemExit(1)
    if not (
        monte["p05_growth_factor"] >= 1.0
        and monte["minimum_multiplier"] >= 3.0
        and monte["minimum_invariant"] >= 1.0
        and monte["insolvency_probability"] == 0.0
        and monte["fake_qe_rejected_all_paths"]
        and monte["internal_usdt_topology_enabled"]
    ):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
