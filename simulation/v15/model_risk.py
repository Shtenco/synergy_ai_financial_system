#!/usr/bin/env python3
"""V15 model-risk calibration for large graph search.

When many candidate gradients/routes/sizes are scanned, choosing the maximum
estimated edge creates selection bias (winner's curse). This module provides a
simple conservative reference penalty that is fed into RobustGovernor as
`model_uncertainty`; it does not replace EVM postconditions.

No distributional assumption is treated as a production theorem. Gaussian-style
extreme-value penalty here is a reference lower layer; production should calibrate
against empirical quote->execution errors and block/bootstrap maxima.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import log, sqrt
from typing import Iterable, Sequence


def empirical_overstatement_buffer(prediction_errors: Sequence[float], quantile: float = 0.99) -> float:
    """One-sided buffer for predicted - realized hard gain.

    Positive error means the model over-predicted protocol HardNAV gain.
    Negative error is not dangerous for this acceptance bound and is clipped to 0.
    """
    if not prediction_errors:
        raise ValueError("need prediction errors")
    if not (0.5 <= quantile < 1.0):
        raise ValueError("quantile must be in [0.5,1)")
    xs = sorted(max(0.0, x) for x in prediction_errors)
    idx = min(len(xs) - 1, int(quantile * len(xs)))
    return xs[idx]


def search_space_penalty(sigma_error: float, candidate_count: int, family_alpha: float = 0.01) -> float:
    """Conservative Gaussian-style extreme-value reference penalty.

    sigma * sqrt(2 ln(M/alpha)) grows with the number M of simultaneously tested
    candidates. This is intentionally simple and must be replaced/validated by an
    empirical maximum-error distribution once enough live/fork observations exist.
    """
    if sigma_error < 0 or candidate_count <= 0 or not (0 < family_alpha < 1):
        raise ValueError("bad model-risk input")
    if sigma_error == 0:
        return 0.0
    return sigma_error * sqrt(2.0 * log(candidate_count / family_alpha))


def shrink_to_zero(sample_mean_edge: float, observations: int, prior_strength: float = 50.0) -> float:
    """Simple zero-prior shrinkage against small-sample edge overestimation."""
    if observations < 0 or prior_strength < 0:
        raise ValueError("bad shrinkage input")
    if observations == 0:
        return 0.0
    weight = observations / (observations + prior_strength)
    return weight * sample_mean_edge


@dataclass(frozen=True)
class ModelRiskBudget:
    empirical_overstatement: float
    selection_penalty: float
    structural_addon: float

    @property
    def total(self) -> float:
        return self.empirical_overstatement + self.selection_penalty + self.structural_addon


def build_model_risk_budget(
    prediction_errors: Sequence[float],
    sigma_error: float,
    candidate_count: int,
    structural_addon: float = 0.0,
    quantile: float = 0.99,
    family_alpha: float = 0.01,
) -> ModelRiskBudget:
    if structural_addon < 0:
        raise ValueError("negative structural addon")
    return ModelRiskBudget(
        empirical_overstatement=empirical_overstatement_buffer(prediction_errors, quantile),
        selection_penalty=search_space_penalty(sigma_error, candidate_count, family_alpha),
        structural_addon=structural_addon,
    )


def accepted_after_model_risk(
    worst_case_hard_gain: float,
    oracle_uncertainty: float,
    system_cost: float,
    model_risk: ModelRiskBudget,
    minimum_gain: float,
) -> bool:
    if min(oracle_uncertainty, system_cost, minimum_gain) < 0:
        raise ValueError("negative acceptance input")
    robust = worst_case_hard_gain - oracle_uncertainty - system_cost - model_risk.total
    return robust >= minimum_gain


def main() -> None:
    errors = [0.001, 0.003, -0.001, 0.006, 0.002, 0.004] * 20
    for m in (1, 10, 100, 1_000, 100_000):
        b = build_model_risk_budget(errors, sigma_error=0.004, candidate_count=m)
        print(f"M={m:6d} empirical={b.empirical_overstatement:.5f} selection={b.selection_penalty:.5f} total={b.total:.5f}")


if __name__ == "__main__":
    main()
