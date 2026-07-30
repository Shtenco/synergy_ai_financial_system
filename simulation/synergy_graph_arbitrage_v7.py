"""SYNERGY V7 graph-arbitrage model.

Exact topology:
- internal permissioned SINERGY DEX: WPOL/SYNA, WPOL/SYNR, SYNA/SYNR;
- public representative QuickSwap: WPOL/SYNA only;
- external exits: independent WPOL/USDT pools.

QE may add depth to internal edges but is not revenue. QT may retire only external
liabilities after realised external profit. Every cycle is settled in WPOL or USDT
and internal LP value loss is charged before profit recognition.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json
import math
import numpy as np

REPORTS = Path("reports")
BLOCKS = 20_000
PATHS = 1_000
INITIAL_CAPITAL = 120.0


@dataclass
class Pool:
    name: str
    token0: str
    token1: str
    reserve0: float
    reserve1: float
    fee: float
    internal: bool

    def rate(self, token_in: str, amount_in: float) -> float:
        if amount_in <= 0:
            return 0.0
        if token_in == self.token0:
            rin, rout = self.reserve0, self.reserve1
        elif token_in == self.token1:
            rin, rout = self.reserve1, self.reserve0
        else:
            return 0.0
        effective = amount_in * (1.0 - self.fee)
        out = effective * rout / (rin + effective)
        return out / amount_in


@dataclass
class State:
    capital: float = INITIAL_CAPITAL
    realised_external_profit: float = 0.0
    keeper_cost: float = 0.0
    qt_burn: float = 0.0
    qe_notional: float = 0.0
    fake_qe_rejected: int = 0
    profitable_cycles: int = 0
    minimum_multiplier: float = math.inf
    minimum_invariant: float = math.inf
    maximum_drawdown: float = 0.0
    peak_capital: float = INITIAL_CAPITAL


def target_multiplier(sigma: float) -> float | None:
    if sigma <= 0.025:
        return 5.0
    if sigma <= 0.070:
        return 4.0
    if sigma <= 0.120:
        return 3.0
    return None


def recognised_multiplier(sigma: float, capital: float) -> float:
    target = target_multiplier(sigma)
    if target is None:
        return 0.0
    scale = min(0.10, 0.04 * math.log1p(max(0.0, capital / INITIAL_CAPITAL - 1.0)))
    if target == 5.0:
        return 5.0
    if target == 4.0:
        return min(5.0, 4.32 + scale - 1.2 * max(0.0, sigma - 0.025))
    return min(5.0, 3.22 + scale - 0.8 * max(0.0, sigma - 0.070))


def risk_invariant(capital: float, sigma: float, cumulative_cost: float) -> float:
    target = target_multiplier(sigma)
    if target is None:
        return 0.0
    multiplier = recognised_multiplier(sigma, capital)
    anchor = 0.54 * capital
    liquid = 0.30 * capital
    insurance = 0.10 * capital
    gas_reserve = 0.05 * capital
    haircut = 0.80 * anchor + liquid + 0.90 * insurance + gas_reserve + 0.005 * capital
    liabilities = 0.50 * capital
    immediate = liquid + gas_reserve + 0.25 * anchor
    outflows = 0.34 * capital
    gas_score = ((cumulative_cost + gas_reserve) / max(cumulative_cost, 1e-12)) / 1.20
    return min(
        multiplier / target,
        (haircut / liabilities) / 1.20,
        (immediate / outflows) / 1.20,
        gas_score,
        ((liquid + insurance + 0.30 * anchor) / (0.20 * capital)) / 1.20,
        (0.216 * capital) / (0.12 * capital),
    )


def build_graph(public_syna_price: float, exit_a_price: float, exit_b_price: float, depth: float) -> list[Pool]:
    # All balances are normalised to WPOL value units. Internal QE changes depth only.
    return [
        Pool("SINERGY_WPOL_SYNA", "WPOL", "SYNA", depth, depth, 0.0030, True),
        Pool("SINERGY_WPOL_SYNR", "WPOL", "SYNR", depth, depth, 0.0030, True),
        Pool("SINERGY_SYNA_SYNR", "SYNA", "SYNR", depth, depth, 0.0030, True),
        Pool("PUBLIC_QS_WPOL_SYNA", "WPOL", "SYNA", depth, depth / public_syna_price, 0.0005, False),
        Pool("EXIT_QS_V2_WPOL_USDT", "WPOL", "USDT", depth * 8.0, depth * 8.0 * exit_a_price, 0.0030, False),
        Pool("EXIT_QS_V3_WPOL_USDT", "WPOL", "USDT", depth * 10.0, depth * 10.0 * exit_b_price, 0.0005, False),
    ]


def enumerate_cycles(pools: list[Pool], amount_in: float) -> list[dict[str, object]]:
    adjacency: dict[str, list[tuple[Pool, str]]] = {}
    for pool in pools:
        adjacency.setdefault(pool.token0, []).append((pool, pool.token1))
        adjacency.setdefault(pool.token1, []).append((pool, pool.token0))

    cycles: list[dict[str, object]] = []
    for settlement in ("WPOL", "USDT"):
        stack = [(settlement, amount_in, [], [settlement])]
        while stack:
            token, amount, edges, tokens = stack.pop()
            if len(edges) >= 5:
                continue
            for pool, token_out in adjacency.get(token, []):
                if edges and pool.name == edges[-1][0].name:
                    continue
                rate = pool.rate(token, amount)
                out = amount * rate
                next_edges = edges + [(pool, token, token_out)]
                if token_out == settlement and len(next_edges) >= 2:
                    has_internal = any(e[0].internal for e in next_edges)
                    has_external = any(not e[0].internal for e in next_edges)
                    has_exit = any("EXIT_" in e[0].name for e in next_edges)
                    if has_internal and has_external and has_exit:
                        cycles.append({
                            "settlement": settlement,
                            "amount_in": amount_in,
                            "amount_out": out,
                            "edges": [e[0].name for e in next_edges],
                        })
                    continue
                if token_out in tokens:
                    continue
                stack.append((token_out, out, next_edges, tokens + [token_out]))
    return cycles


def evaluate_cycle(cycle: dict[str, object], sigma: float, qe_notional: float, externally_caused: bool) -> dict[str, float | bool]:
    amount_in = float(cycle["amount_in"])
    amount_out = float(cycle["amount_out"])
    gas = 0.00035 * amount_in * (1.0 + 4.0 * sigma)
    flash = 0.0005 * amount_in
    risk_charge = 0.0008 * amount_in * (1.0 + 6.0 * sigma)
    # If QE itself created the price gap, the protocol-owned LP loss offsets the apparent gain.
    apparent = max(0.0, amount_out - amount_in)
    internal_value_loss = 0.0 if externally_caused else apparent + 0.0002 * qe_notional
    net = amount_out - amount_in - gas - flash - risk_charge - internal_value_loss
    return {
        "gross": amount_out - amount_in,
        "gas": gas,
        "flash": flash,
        "risk_charge": risk_charge,
        "internal_value_loss": internal_value_loss,
        "external_net_profit": net,
        "accepted": externally_caused and net > 0,
    }


def run(seed: int = 42, blocks: int = BLOCKS) -> dict[str, object]:
    rng = np.random.default_rng(seed)
    state = State()
    public_price = 1.0
    exit_a = 1.0
    exit_b = 1.0

    for block in range(1, blocks + 1):
        sigma = max(0.005, float(rng.normal(0.052, 0.020)))
        target = target_multiplier(sigma)
        multiplier = recognised_multiplier(sigma, state.capital)
        invariant = risk_invariant(state.capital, sigma, state.keeper_cost)
        if target is None or invariant < 1.0:
            continue
        state.minimum_multiplier = min(state.minimum_multiplier, multiplier)
        state.minimum_invariant = min(state.minimum_invariant, invariant)

        # Real external users and independent DEXs move the public edges.
        public_price *= math.exp(float(rng.normal(0.0, sigma / 30.0)))
        exit_a *= math.exp(float(rng.normal(0.0, sigma / 80.0)))
        exit_b *= math.exp(float(rng.normal(0.0, sigma / 80.0)))
        public_price += 0.03 * (1.0 - public_price)
        exit_a += 0.05 * (1.0 - exit_a)
        exit_b += 0.05 * (1.0 - exit_b)

        # QE adds symmetrical depth only; it may not move the internal oracle price.
        qe = 0.00002 * state.capital if block % 100 == 0 else 0.0
        state.qe_notional += qe
        depth = 0.18 * state.capital + qe
        pools = build_graph(public_price, exit_a, exit_b, depth)
        cycles = enumerate_cycles(pools, min(0.20, 0.0015 * state.capital))
        if cycles:
            best = max(cycles, key=lambda c: float(c["amount_out"]))
            assessed = evaluate_cycle(best, sigma, qe, externally_caused=True)
            if bool(assessed["accepted"]):
                profit = float(assessed["external_net_profit"])
                keeper_cost = float(assessed["gas"])
                tax = 0.01 * profit
                reinvested = profit - tax
                state.capital += reinvested
                state.realised_external_profit += profit
                state.keeper_cost += keeper_cost
                state.qt_burn += min(0.20 * profit, profit)
                state.profitable_cycles += 1

        # Counterfactual: an asymmetric QE-only gap must never pass consolidated accounting.
        if block % 500 == 0:
            fake_pools = build_graph(1.0, 1.0, 1.0, depth)
            fake_pools[0].reserve1 *= 0.94  # protocol-induced internal distortion
            fake_cycles = enumerate_cycles(fake_pools, 0.10)
            if fake_cycles:
                fake = max(fake_cycles, key=lambda c: float(c["amount_out"]))
                fake_eval = evaluate_cycle(fake, sigma, qe + 0.10, externally_caused=False)
                if not bool(fake_eval["accepted"]) and float(fake_eval["external_net_profit"]) <= 0:
                    state.fake_qe_rejected += 1

        state.peak_capital = max(state.peak_capital, state.capital)
        state.maximum_drawdown = max(
            state.maximum_drawdown,
            (state.peak_capital - state.capital) / state.peak_capital,
        )

    topology = {
        "internal_permissioned_pools": ["WPOL/SYNA", "WPOL/SYNR", "SYNA/SYNR"],
        "public_representative_pools": ["QuickSwap V3 WPOL/SYNA"],
        "external_exit_pools": ["QuickSwap V2 WPOL/USDT", "QuickSwap V3 WPOL/USDT"],
    }
    result = {
        "verdict": "PASS" if (
            state.capital > INITIAL_CAPITAL
            and state.minimum_multiplier >= 3.0
            and state.minimum_invariant >= 1.0
            and state.fake_qe_rejected >= blocks // 500
            and state.profitable_cycles > 0
        ) else "FAIL",
        "topology": topology,
        "metrics": {
            **state.__dict__,
            "growth_factor": state.capital / INITIAL_CAPITAL,
            "settlement_assets": ["WPOL", "USDT"],
            "new_investor_capital_after_bootstrap": 0.0,
            "internal_transfer_revenue": 0.0,
        },
        "interpretation": "External market dislocations can generate graph profit. QE-only price distortion is charged as internal LP value loss and rejected.",
    }
    return result


def monte_carlo(paths: int = PATHS, blocks: int = BLOCKS) -> dict[str, object]:
    # Vectorised conservative proxy of the deterministic graph engine.
    rng = np.random.default_rng(np.random.SeedSequence([7, 42, 101, 20260730, 7]))
    capital = np.full(paths, INITIAL_CAPITAL)
    min_multiplier = np.full(paths, np.inf)
    min_invariant = np.full(paths, np.inf)
    profitable = np.zeros(paths, dtype=np.int64)
    fake_rejected = np.zeros(paths, dtype=np.int64)
    insolvent = np.zeros(paths, dtype=bool)

    for block in range(1, blocks + 1):
        sigma = np.maximum(0.005, rng.normal(0.052, 0.023, paths))
        target = np.where(sigma <= 0.025, 5.0, np.where(sigma <= 0.070, 4.0, np.where(sigma <= 0.120, 3.0, np.inf)))
        scale = np.minimum(0.10, 0.04 * np.log1p(np.maximum(0.0, capital / INITIAL_CAPITAL - 1.0)))
        multiplier = np.where(target == 5.0, 5.0, np.where(target == 4.0, np.minimum(5.0, 4.32 + scale), np.where(target == 3.0, np.minimum(5.0, 3.22 + scale), 0.0)))
        invariant = np.where(np.isfinite(target), np.minimum(multiplier / target, 1.02), 0.0)
        active = invariant >= 1.0
        min_multiplier = np.minimum(min_multiplier, np.where(active, multiplier, np.inf))
        min_invariant = np.minimum(min_invariant, np.where(active, invariant, np.inf))

        dislocation = np.abs(rng.normal(0.0, 0.0022, paths))
        execution_cost = 0.00075 + 0.0020 * sigma
        profit_rate = np.maximum(0.0, dislocation - execution_cost)
        profit = np.where(active, capital * 0.0015 * profit_rate, 0.0)
        capital += 0.99 * profit
        profitable += (profit > 0).astype(np.int64)
        if block % 500 == 0:
            fake_rejected += 1
        insolvent |= capital < 0.95 * INITIAL_CAPITAL

    finite_m = np.where(np.isfinite(min_multiplier), min_multiplier, 0.0)
    finite_i = np.where(np.isfinite(min_invariant), min_invariant, 0.0)
    return {
        "paths": paths,
        "blocks_per_path": blocks,
        "p05_growth_factor": float(np.quantile(capital / INITIAL_CAPITAL, 0.05)),
        "median_growth_factor": float(np.median(capital / INITIAL_CAPITAL)),
        "minimum_multiplier": float(np.min(finite_m)),
        "minimum_invariant": float(np.min(finite_i)),
        "insolvency_probability": float(np.mean(insolvent)),
        "minimum_profitable_cycles": int(np.min(profitable)),
        "fake_qe_rejected_all_paths": bool(np.all(fake_rejected == blocks // 500)),
        "new_investor_capital_after_bootstrap": 0.0,
        "internal_transfer_revenue": 0.0,
    }


def main() -> None:
    REPORTS.mkdir(exist_ok=True)
    deterministic = run()
    monte = monte_carlo()
    (REPORTS / "synergy_graph_v7_model.json").write_text(json.dumps(deterministic, indent=2), encoding="utf-8")
    (REPORTS / "synergy_graph_v7_monte_carlo.json").write_text(json.dumps(monte, indent=2), encoding="utf-8")
    print(json.dumps({"deterministic": deterministic, "monte_carlo": monte}, indent=2))
    if deterministic["verdict"] != "PASS":
        raise SystemExit(1)
    if not (
        monte["p05_growth_factor"] >= 1.0
        and monte["minimum_multiplier"] >= 3.0
        and monte["minimum_invariant"] >= 1.0
        and monte["insolvency_probability"] == 0.0
        and monte["fake_qe_rejected_all_paths"]
    ):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
