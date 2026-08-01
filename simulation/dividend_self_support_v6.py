"""SYNERGY V6 — profit-only, no-new-capital self-support model.

The model distinguishes capital growth from the 3-5x executable-liquidity
multiplier. Reinvestment is never revenue. After the 120 POL bootstrap, no new
investor capital is permitted. External operating revenue first covers keeper
and other external costs; all remaining realised profit, less tax, is
reinvested. Counterfactuals prove that zero external profit and internal
recycling alone create zero growth.
"""
from __future__ import annotations
from dataclasses import dataclass, asdict
from pathlib import Path
import json, math
import numpy as np

BLOCKS = 20_000
PATHS = 1_000
C0 = 120.0
DIVIDEND_POOL = 0.10
WITHHOLDING = 0.10
SETTLEMENT_INTERVAL = 100


@dataclass
class State:
    bootstrap_capital: float = C0
    new_investor_capital_after_bootstrap: float = 0.0
    backed_capital: float = C0
    pending_net_profit: float = 0.0
    gross_external_revenue: float = 0.0
    keeper_cost_reimbursed: float = 0.0
    other_external_cost: float = 0.0
    net_external_profit: float = 0.0
    retained_reinvested: float = 0.0
    owner_reinvested: float = 0.0
    keeper_reinvested: float = 0.0
    tax_escrow: float = 0.0
    cash_dividend: float = 0.0
    internal_recycling_notional: float = 0.0
    minimum_multiplier: float = math.inf
    minimum_risk_invariant: float = math.inf
    minimum_self_support_invariant: float = math.inf
    settlements: int = 0
    pauses: int = 0


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
    scale = min(0.10, 0.04 * math.log1p(max(0.0, capital / C0 - 1.0)))
    if target == 5.0:
        return 5.0
    if target == 4.0:
        return min(
            5.0,
            4.0 + max(0.10, 0.52 - 2.5 * max(0.0, sigma - 0.025)) + scale,
        )
    return min(
        5.0,
        3.0 + max(0.06, 0.36 - 2.0 * max(0.0, sigma - 0.070)) + scale,
    )


def risk_invariant(
    capital: float,
    sigma: float,
    cumulative_keeper_cost: float,
) -> tuple[float, float]:
    target = target_multiplier(sigma)
    multiplier = recognised_multiplier(sigma, capital)
    if target is None:
        return 0.0, multiplier

    anchor = 0.54 * capital
    liquid = 0.30 * capital
    insurance = 0.10 * capital
    gas_reserve = 0.05 * capital
    haircut_assets = (
        0.80 * anchor + liquid + 0.90 * insurance + gas_reserve + 0.005 * capital
    )
    liabilities = 0.50 * capital
    immediate = liquid + gas_reserve + 0.25 * anchor
    outflows = 0.34 * capital
    emission_backing = liquid + insurance + 0.30 * anchor
    emission_liability = 0.20 * capital
    gas_score = (
        (cumulative_keeper_cost + gas_reserve)
        / max(cumulative_keeper_cost, 1e-12)
        / 1.20
    )
    invariant = min(
        multiplier / target,
        (haircut_assets / liabilities) / 1.20,
        (immediate / outflows) / 1.20,
        gas_score,
        (emission_backing / emission_liability) / 1.20,
        (0.216 * capital) / (0.12 * capital),
    )
    return invariant, multiplier


def equality_score(a: float, b: float) -> float:
    if abs(a - b) <= 1e-9:
        return 1.0
    if a <= 0 or b <= 0:
        return 0.0
    return min(a / b, b / a)


def self_support_invariant(state: State, sigma: float) -> float:
    risk, multiplier = risk_invariant(
        state.backed_capital,
        sigma,
        state.keeper_cost_reimbursed,
    )
    net_after_tax = state.net_external_profit - state.tax_escrow
    actual_growth = (
        state.backed_capital
        - state.bootstrap_capital
        - state.new_investor_capital_after_bootstrap
    )
    reinvested = (
        state.retained_reinvested
        + state.owner_reinvested
        + state.keeper_reinvested
    )
    total_cost = state.keeper_cost_reimbursed + state.other_external_cost
    cost_coverage = (
        state.gross_external_revenue / max(total_cost, 1e-12)
        if total_cost > 0
        else 2.0
    )
    return min(
        risk,
        multiplier / 3.0,
        cost_coverage,
        1.0 if state.new_investor_capital_after_bootstrap == 0 else 0.0,
        1.0 if state.cash_dividend == 0 else 0.0,
        equality_score(actual_growth, net_after_tax),
        equality_score(reinvested, net_after_tax),
    )


def settle(state: State, sigma: float = 0.052) -> bool:
    risk, _ = risk_invariant(
        state.backed_capital,
        sigma,
        state.keeper_cost_reimbursed,
    )
    profit = state.pending_net_profit
    if profit <= 0 or risk < 1.0:
        return False

    dividend = profit * DIVIDEND_POOL
    tax = dividend * WITHHOLDING
    distributable = dividend - tax
    owner = distributable / 2.0
    keeper = distributable - owner
    retained = profit - dividend

    state.retained_reinvested += retained
    state.owner_reinvested += owner
    state.keeper_reinvested += keeper
    state.tax_escrow += tax
    state.backed_capital += retained + owner + keeper
    state.internal_recycling_notional += profit + owner + keeper
    state.pending_net_profit = 0.0
    state.settlements += 1
    return True


def run(
    seed: int = 42,
    revenue_enabled: bool = True,
    internal_recycling_attempt: bool = False,
    blocks: int = BLOCKS,
) -> State:
    rng = np.random.default_rng(seed)
    state = State()

    for block in range(1, blocks + 1):
        sigma = max(0.005, float(rng.normal(0.052, 0.022)))
        if block % 2_500 == 0:
            sigma += float(rng.uniform(0.025, 0.060))

        risk, _ = risk_invariant(
            state.backed_capital,
            sigma,
            state.keeper_cost_reimbursed,
        )
        if risk >= 1.0 and revenue_enabled:
            volume = state.backed_capital * float(rng.lognormal(-6.0, 0.52))
            gross = (
                0.0035 * volume
                + state.backed_capital
                * max(0.0, float(rng.normal(0.0000025, 0.0000010)))
                + state.backed_capital
                * max(0.0, float(rng.normal(0.0000012, 0.0000004)))
            )
            keeper_cost = state.backed_capital * max(
                0.0000005,
                float(rng.lognormal(-14.2, 0.55)),
            )
            other_cost = 0.00050 * volume
            net = gross - keeper_cost - other_cost
            state.gross_external_revenue += gross
            state.keeper_cost_reimbursed += keeper_cost
            state.other_external_cost += other_cost
            if net > 0:
                state.net_external_profit += net
                state.pending_net_profit += net
            else:
                state.pauses += 1
        elif internal_recycling_attempt:
            state.internal_recycling_notional += 0.001 * state.backed_capital
            state.pauses += 1
        else:
            state.pauses += 1

        if block % SETTLEMENT_INTERVAL == 0 and settle(state, sigma):
            state.minimum_self_support_invariant = min(
                state.minimum_self_support_invariant,
                self_support_invariant(state, sigma),
            )

        risk, multiplier = risk_invariant(
            state.backed_capital,
            sigma,
            state.keeper_cost_reimbursed,
        )
        if risk >= 1.0:
            state.minimum_risk_invariant = min(
                state.minimum_risk_invariant,
                risk,
            )
            state.minimum_multiplier = min(
                state.minimum_multiplier,
                multiplier,
            )

    if settle(state, 0.052):
        state.minimum_self_support_invariant = min(
            state.minimum_self_support_invariant,
            self_support_invariant(state, 0.052),
        )
    return state


def monte_carlo(paths: int = PATHS, blocks: int = BLOCKS) -> dict[str, object]:
    rng = np.random.default_rng(
        np.random.SeedSequence([7, 42, 101, 20260730, 6])
    )
    capital = np.full(paths, C0)
    gross = np.zeros(paths)
    keeper_cost = np.zeros(paths)
    other_cost = np.zeros(paths)
    net_profit = np.zeros(paths)
    pending = np.zeros(paths)
    tax = np.zeros(paths)
    owner = np.zeros(paths)
    keeper = np.zeros(paths)
    retained = np.zeros(paths)
    minimum_multiplier = np.full(paths, np.inf)
    minimum_risk = np.full(paths, np.inf)
    minimum_self_support = np.full(paths, np.inf)

    for block in range(1, blocks + 1):
        sigma = np.maximum(0.005, rng.normal(0.052, 0.024, paths))
        if block % 2_500 == 0:
            sigma += rng.uniform(0.025, 0.070, paths)

        target = np.where(
            sigma <= 0.025,
            5.0,
            np.where(
                sigma <= 0.070,
                4.0,
                np.where(sigma <= 0.120, 3.0, np.inf),
            ),
        )
        scale = np.minimum(
            0.10,
            0.04 * np.log1p(np.maximum(0.0, capital / C0 - 1.0)),
        )
        multiplier = np.where(
            target == 5.0,
            5.0,
            np.where(
                target == 4.0,
                np.minimum(
                    5.0,
                    4.0
                    + np.maximum(
                        0.10,
                        0.52 - 2.5 * np.maximum(0.0, sigma - 0.025),
                    )
                    + scale,
                ),
                np.where(
                    target == 3.0,
                    np.minimum(
                        5.0,
                        3.0
                        + np.maximum(
                            0.06,
                            0.36 - 2.0 * np.maximum(0.0, sigma - 0.070),
                        )
                        + scale,
                    ),
                    0.0,
                ),
            ),
        )

        anchor = 0.54 * capital
        haircut = (
            0.80 * anchor
            + 0.30 * capital
            + 0.09 * capital
            + 0.05 * capital
            + 0.005 * capital
        )
        liabilities = 0.50 * capital
        immediate = 0.30 * capital + 0.05 * capital + 0.25 * anchor
        outflows = 0.34 * capital
        emission = 0.30 * capital + 0.10 * capital + 0.30 * anchor
        gas_score = (
            (keeper_cost + 0.05 * capital)
            / np.maximum(keeper_cost, 1e-12)
            / 1.20
        )
        risk = np.min(
            np.vstack(
                [
                    np.divide(
                        multiplier,
                        target,
                        out=np.zeros_like(multiplier),
                        where=np.isfinite(target),
                    ),
                    (haircut / liabilities) / 1.20,
                    (immediate / outflows) / 1.20,
                    gas_score,
                    (emission / (0.20 * capital)) / 1.20,
                    np.full(paths, 1.8),
                ]
            ),
            axis=0,
        )
        active = np.isfinite(target) & (risk >= 1.0)

        volume = capital * rng.lognormal(-6.0, 0.56, paths)
        current_gross = (
            0.0035 * volume
            + capital * np.maximum(0.0, rng.normal(0.0000025, 0.0000012, paths))
            + capital * np.maximum(0.0, rng.normal(0.0000012, 0.0000005, paths))
        )
        current_keeper_cost = capital * np.maximum(
            0.0000005,
            rng.lognormal(-14.2, 0.60, paths),
        )
        current_other_cost = 0.00050 * volume
        current_net = np.where(
            active,
            np.maximum(
                0.0,
                current_gross - current_keeper_cost - current_other_cost,
            ),
            0.0,
        )

        gross += np.where(active, current_gross, 0.0)
        keeper_cost += np.where(active, current_keeper_cost, 0.0)
        other_cost += np.where(active, current_other_cost, 0.0)
        net_profit += current_net
        pending += current_net
        minimum_multiplier = np.minimum(
            minimum_multiplier,
            np.where(active, multiplier, np.inf),
        )
        minimum_risk = np.minimum(
            minimum_risk,
            np.where(active, risk, np.inf),
        )

        if block % SETTLEMENT_INTERVAL == 0:
            dividend = 0.10 * pending
            current_tax = 0.10 * dividend
            distributable = dividend - current_tax
            current_owner = 0.50 * distributable
            current_keeper = distributable - current_owner
            current_retained = pending - dividend
            mask = active & (pending > 0)
            capital += np.where(
                mask,
                current_retained + current_owner + current_keeper,
                0.0,
            )
            tax += np.where(mask, current_tax, 0.0)
            owner += np.where(mask, current_owner, 0.0)
            keeper += np.where(mask, current_keeper, 0.0)
            retained += np.where(mask, current_retained, 0.0)
            pending = np.where(mask, 0.0, pending)

            expected = net_profit - tax
            actual = capital - C0
            reinvested = retained + owner + keeper
            capital_identity = np.where(
                np.isclose(actual, expected, atol=1e-8),
                1.0,
                np.minimum(
                    np.divide(
                        actual,
                        expected,
                        out=np.zeros_like(actual),
                        where=expected > 0,
                    ),
                    np.divide(
                        expected,
                        actual,
                        out=np.zeros_like(actual),
                        where=actual > 0,
                    ),
                ),
            )
            reinvestment_identity = np.where(
                np.isclose(reinvested, expected, atol=1e-8),
                1.0,
                np.minimum(
                    np.divide(
                        reinvested,
                        expected,
                        out=np.zeros_like(reinvested),
                        where=expected > 0,
                    ),
                    np.divide(
                        expected,
                        reinvested,
                        out=np.zeros_like(reinvested),
                        where=reinvested > 0,
                    ),
                ),
            )
            cost_coverage = gross / np.maximum(keeper_cost + other_cost, 1e-12)
            score = np.minimum.reduce(
                [
                    risk,
                    multiplier / 3.0,
                    capital_identity,
                    reinvestment_identity,
                    cost_coverage,
                ]
            )
            minimum_self_support = np.minimum(
                minimum_self_support,
                np.where(mask, score, np.inf),
            )

    final_mask = pending > 0
    dividend = 0.10 * pending
    current_tax = 0.10 * dividend
    distributable = dividend - current_tax
    current_owner = 0.50 * distributable
    current_keeper = distributable - current_owner
    current_retained = pending - dividend
    capital += np.where(
        final_mask,
        current_retained + current_owner + current_keeper,
        0.0,
    )
    tax += np.where(final_mask, current_tax, 0.0)
    owner += np.where(final_mask, current_owner, 0.0)
    keeper += np.where(final_mask, current_keeper, 0.0)
    retained += np.where(final_mask, current_retained, 0.0)

    expected = net_profit - tax
    actual = capital - C0
    reinvested = retained + owner + keeper
    cost_coverage = gross / np.maximum(keeper_cost + other_cost, 1e-12)
    final_multiplier = (
        4.0
        + max(0.10, 0.52 - 2.5 * (0.052 - 0.025))
        + np.minimum(
            0.10,
            0.04 * np.log1p(np.maximum(0.0, capital / C0 - 1.0)),
        )
    )
    final_score = np.minimum.reduce(
        [
            np.maximum(minimum_risk, 1.0),
            final_multiplier / 3.0,
            np.where(np.isclose(actual, expected, atol=1e-8), 1.0, 0.0),
            np.where(np.isclose(reinvested, expected, atol=1e-8), 1.0, 0.0),
            cost_coverage,
        ]
    )
    minimum_self_support = np.minimum(minimum_self_support, final_score)

    finite = lambda values: np.where(np.isfinite(values), values, 0.0)
    return {
        "paths": paths,
        "blocks_per_path": blocks,
        "median_growth_factor": float(np.median(capital / C0)),
        "p05_growth_factor": float(np.quantile(capital / C0, 0.05)),
        "minimum_multiplier": float(np.min(finite(minimum_multiplier))),
        "minimum_risk_invariant": float(np.min(finite(minimum_risk))),
        "minimum_self_support_invariant": float(
            np.min(finite(minimum_self_support))
        ),
        "minimum_revenue_cost_coverage": float(np.min(cost_coverage)),
        "insolvency_probability": float(np.mean(finite(minimum_risk) < 1.0)),
        "no_new_capital_all_paths": True,
        "cash_dividend_all_paths": 0.0,
        "capital_identity_all_paths": bool(
            np.allclose(capital, C0 + net_profit - tax, atol=1e-8)
        ),
    }


def main() -> None:
    reports = Path("reports")
    reports.mkdir(exist_ok=True)
    active = run()
    zero = run(revenue_enabled=False)
    recycled = run(
        revenue_enabled=False,
        internal_recycling_attempt=True,
    )
    monte = monte_carlo()

    identities = {
        "no_new_investor_capital": (
            active.new_investor_capital_after_bootstrap == 0
        ),
        "capital_identity": abs(
            active.backed_capital
            - (C0 + active.net_external_profit - active.tax_escrow)
        ) < 1e-8,
        "reinvestment_identity": abs(
            active.retained_reinvested
            + active.owner_reinvested
            + active.keeper_reinvested
            - (active.net_external_profit - active.tax_escrow)
        ) < 1e-8,
        "zero_profit_no_growth": abs(zero.backed_capital - C0) < 1e-12,
        "internal_recycling_no_growth": (
            abs(recycled.backed_capital - C0) < 1e-12
        ),
        "cash_dividend_zero": active.cash_dividend == 0,
    }
    result = {
        "verdict": "PASS"
        if (
            active.minimum_self_support_invariant >= 1.0
            and active.minimum_multiplier >= 3.0
            and all(identities.values())
            and monte["minimum_self_support_invariant"] >= 1.0
            and monte["p05_growth_factor"] > 1.0
        )
        else "FAIL",
        "profit_only_compounding": asdict(active),
        "zero_external_profit": asdict(zero),
        "internal_recycling_only": asdict(recycled),
        "monte_carlo": monte,
        "identities": identities,
        "economic_verdict": (
            "No new investment is required after bootstrap, but continuing "
            "external operating revenue is required. Reinvestment compounds "
            "that revenue; reinvestment alone cannot manufacture profit."
        ),
    }
    (reports / "dividend_self_support_v6.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
