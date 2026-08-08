from __future__ import annotations

from dataclasses import dataclass
from math import isfinite


@dataclass(frozen=True)
class UnderwritingScenario:
    success_probability: float
    loss_given_default: float
    duration_weeks: int
    annual_project_yield: float
    annual_funding_cost: float = 0.0
    annual_capital_charge: float = 0.0
    operating_cost_share: float = 0.0
    external_first_loss_share: float = 0.0

    def __post_init__(self) -> None:
        for name in (
            "success_probability",
            "loss_given_default",
            "external_first_loss_share",
        ):
            value = getattr(self, name)
            if not isfinite(value) or not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must be in [0,1]")
        for name in (
            "annual_project_yield",
            "annual_funding_cost",
            "annual_capital_charge",
            "operating_cost_share",
        ):
            value = getattr(self, name)
            if not isfinite(value) or value < 0.0:
                raise ValueError(f"{name} must be finite and non-negative")
        if self.duration_weeks <= 0:
            raise ValueError("duration_weeks must be positive")

    @property
    def default_probability(self) -> float:
        return 1.0 - self.success_probability

    @property
    def duration_years(self) -> float:
        return self.duration_weeks / 52.0

    @property
    def expected_gross_interest_share(self) -> float:
        return (
            self.success_probability
            * self.annual_project_yield
            * self.duration_years
        )

    @property
    def expected_credit_loss_share(self) -> float:
        gross = self.default_probability * self.loss_given_default
        return max(0.0, gross - self.external_first_loss_share)

    @property
    def funding_cost_share(self) -> float:
        return self.annual_funding_cost * self.duration_years

    @property
    def capital_charge_share(self) -> float:
        return self.annual_capital_charge * self.duration_years

    @property
    def expected_net_margin_share(self) -> float:
        return (
            self.expected_gross_interest_share
            - self.expected_credit_loss_share
            - self.funding_cost_share
            - self.capital_charge_share
            - self.operating_cost_share
        )

    def break_even_annual_yield(self) -> float:
        denominator = self.success_probability * self.duration_years
        if denominator <= 0:
            return float("inf")
        required_share = (
            self.expected_credit_loss_share
            + self.funding_cost_share
            + self.capital_charge_share
            + self.operating_cost_share
        )
        return required_share / denominator


@dataclass(frozen=True)
class UnderwritingDecision:
    approved: bool
    expected_net_margin_share: float
    break_even_annual_yield: float
    required_additional_first_loss_share: float
    reason: str


class BankUnderwritingPolicy:
    """Investment-bank gate before the Productive Capital Auction.

    Targeted monetary authorisation is deliberately absent from the expected-return
    formula. A bank cannot use future SINERGY issuance as a synthetic yield subsidy.
    """

    def __init__(self, minimum_margin_share: float = 0.0) -> None:
        if not isfinite(minimum_margin_share):
            raise ValueError("minimum margin must be finite")
        self.minimum_margin_share = minimum_margin_share

    def decide(self, scenario: UnderwritingScenario) -> UnderwritingDecision:
        margin = scenario.expected_net_margin_share
        approved = margin >= self.minimum_margin_share
        shortfall = max(0.0, self.minimum_margin_share - margin)
        return UnderwritingDecision(
            approved=approved,
            expected_net_margin_share=margin,
            break_even_annual_yield=scenario.break_even_annual_yield(),
            required_additional_first_loss_share=shortfall,
            reason=(
                "risk-adjusted project economics pass bank gate"
                if approved
                else "NO ACTION: project economics do not cover expected loss/cost"
            ),
        )
