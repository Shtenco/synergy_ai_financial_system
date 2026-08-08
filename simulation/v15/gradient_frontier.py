#!/usr/bin/env python3
"""Two-pool V15 reference frontier.

This is a deliberately small deterministic model used to prove one policy rule:
maximum wedge is not the objective. The optimizer should choose the gradient size
that maximizes robust post-cost HardNAV for the currently available external basis.

It is not a Polygon-fork result.
"""
from dataclasses import dataclass
from typing import Iterable, Optional

FEE = 0.003
TAX_SHARE = 0.99
SOLVER_FLOOR = 0.001


def cp_out(reserve_in: float, reserve_out: float, amount_in: float, fee: float = FEE) -> float:
    effective = amount_in * (1.0 - fee)
    return reserve_out * effective / (reserve_in + effective)


@dataclass(frozen=True)
class RouteResult:
    gradient_pct: float
    external_basis: float
    principal: float
    gross_arb_profit: float
    protocol_hard_gain: float
    robust_hard_gain: float
    solver_reward: float
    hard_turnover: float


def evaluate(
    gradient_pct: float,
    external_basis: float,
    principal: float,
    oracle_error_bps: float = 10.0,
    system_cost: float = 0.001,
) -> Optional[RouteResult]:
    delta = gradient_pct
    if not (0.0 < delta < 100.0) or principal <= 0:
        return None

    # destination B -> SYN after supply-neutral reserve shift
    synthetic = cp_out(100.0, 100.0 + delta, principal)
    # source SYN -> A
    a_out = cp_out(100.0 - delta, 100.0, synthetic)
    # external A -> B. Canonical marks remain A=B=$1; venue contains basis.
    returned_b = cp_out(10_000.0, 10_000.0 * (1.0 + external_basis), a_out)
    gross = returned_b - principal
    if gross <= SOLVER_FLOOR:
        return None

    tax = min(TAX_SHARE * gross, gross - SOLVER_FLOOR)
    solver = gross - tax
    protocol_gain = principal + tax - a_out
    turnover = principal + a_out + tax
    uncertainty = turnover * oracle_error_bps / 10_000.0
    robust = protocol_gain - uncertainty - system_cost

    return RouteResult(
        gradient_pct=gradient_pct,
        external_basis=external_basis,
        principal=principal,
        gross_arb_profit=gross,
        protocol_hard_gain=protocol_gain,
        robust_hard_gain=robust,
        solver_reward=solver,
        hard_turnover=turnover,
    )


def searcher_optimal(
    gradient_pct: float,
    external_basis: float,
    principal_cap: float = 70.0,
    steps: int = 4000,
    oracle_error_bps: float = 10.0,
    system_cost: float = 0.001,
) -> Optional[RouteResult]:
    """Searcher maximizes its gross arb profit; 99% proportional tax preserves argmax."""
    best = None
    for i in range(1, steps + 1):
        principal = principal_cap * i / steps
        r = evaluate(gradient_pct, external_basis, principal, oracle_error_bps, system_cost)
        if r is not None and (best is None or r.gross_arb_profit > best.gross_arb_profit):
            best = r
    return best


def best_gradient(
    external_basis: float,
    gradients: Iterable[float] = (5, 10, 15, 20, 25, 30, 40, 50, 60, 70, 80),
    **kwargs,
) -> Optional[RouteResult]:
    rows = [searcher_optimal(g, external_basis, **kwargs) for g in gradients]
    rows = [r for r in rows if r is not None]
    return max(rows, key=lambda r: r.robust_hard_gain) if rows else None


def main() -> None:
    for basis in (0.004, 0.006, 0.008, 0.010, 0.015, 0.020):
        r = best_gradient(basis)
        if r is None:
            print(f"basis={basis:.2%}: no executable route")
        else:
            print(
                f"basis={basis:.2%} bestGradient={r.gradient_pct:.0f}% "
                f"robust={r.robust_hard_gain:+.6f} hard={r.protocol_hard_gain:+.6f} "
                f"gross={r.gross_arb_profit:.6f} principal={r.principal:.4f}"
            )


if __name__ == "__main__":
    main()
