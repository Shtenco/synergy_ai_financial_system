from __future__ import annotations

from dataclasses import dataclass
from math import exp, isfinite, log
from typing import Iterable

EPS = 1e-12


def _finite_nonnegative(value: float, name: str) -> None:
    if not isfinite(value) or value < 0.0:
        raise ValueError(f"{name} must be finite and non-negative")


def _unit_interval(value: float, name: str) -> None:
    if not isfinite(value) or not 0.0 <= value <= 1.0:
        raise ValueError(f"{name} must be finite and in [0,1]")


@dataclass(frozen=True)
class TermRiskPoint:
    """Borrower credit-risk estimate at one contractual horizon.

    `pd` is cumulative probability of default to this horizon, not an annual
    rate. `lgd` is loss given default after collateral/recovery assumptions.
    `ead_factor` is expected exposure at default divided by original principal.
    The curve should come from the bank's validated scoring/rating system.
    """

    weeks: int
    pd: float
    lgd: float
    ead_factor: float = 1.0

    def __post_init__(self) -> None:
        if self.weeks <= 0:
            raise ValueError("weeks must be positive")
        _unit_interval(self.pd, "pd")
        _unit_interval(self.lgd, "lgd")
        _finite_nonnegative(self.ead_factor, "ead_factor")
        if self.ead_factor > 1.5:
            raise ValueError("ead_factor above 1.5 requires a different exposure model")


@dataclass(frozen=True)
class BorrowerRiskProfile:
    rating: str
    curve: tuple[TermRiskPoint, ...]

    def __post_init__(self) -> None:
        if not self.rating.strip():
            raise ValueError("rating is required")
        if not self.curve:
            raise ValueError("at least one term-risk point is required")
        weeks = [p.weeks for p in self.curve]
        if weeks != sorted(weeks) or len(set(weeks)) != len(weeks):
            raise ValueError("risk curve must be strictly increasing by weeks")
        # Cumulative PD should not fall with horizon in one frozen rating curve.
        if any(right.pd + EPS < left.pd for left, right in zip(self.curve, self.curve[1:])):
            raise ValueError("cumulative PD must be non-decreasing with horizon")

    def at(self, weeks: int) -> TermRiskPoint:
        """Interpolate the term structure without forcing one annual PD on all loans.

        PD is interpolated in cumulative-hazard space so survival probabilities
        remain coherent. LGD/EAD are linearly interpolated. Outside the supplied
        horizon the nearest endpoint is used; production systems should normally
        require explicit curve coverage instead of extrapolating silently.
        """
        if weeks <= 0:
            raise ValueError("weeks must be positive")
        if weeks <= self.curve[0].weeks:
            p = self.curve[0]
            return TermRiskPoint(weeks, p.pd, p.lgd, p.ead_factor)
        if weeks >= self.curve[-1].weeks:
            p = self.curve[-1]
            return TermRiskPoint(weeks, p.pd, p.lgd, p.ead_factor)

        for left, right in zip(self.curve, self.curve[1:]):
            if left.weeks <= weeks <= right.weeks:
                w = (weeks - left.weeks) / (right.weeks - left.weeks)
                h_left = -log(max(EPS, 1.0 - left.pd))
                h_right = -log(max(EPS, 1.0 - right.pd))
                hazard = h_left + w * (h_right - h_left)
                pd = 1.0 - exp(-hazard)
                lgd = left.lgd + w * (right.lgd - left.lgd)
                ead = left.ead_factor + w * (right.ead_factor - left.ead_factor)
                return TermRiskPoint(weeks, pd, lgd, ead)
        raise AssertionError("unreachable risk-curve interpolation")


@dataclass(frozen=True)
class FundingCurvePoint:
    weeks: int
    reference_rate: float
    funding_basis: float = 0.0
    liquidity_term_premium: float = 0.0

    def __post_init__(self) -> None:
        if self.weeks <= 0:
            raise ValueError("weeks must be positive")
        for name in ("reference_rate", "funding_basis", "liquidity_term_premium"):
            _finite_nonnegative(getattr(self, name), name)


@dataclass(frozen=True)
class FundingCurve:
    points: tuple[FundingCurvePoint, ...]

    def __post_init__(self) -> None:
        if not self.points:
            raise ValueError("funding curve requires at least one point")
        weeks = [p.weeks for p in self.points]
        if weeks != sorted(weeks) or len(set(weeks)) != len(weeks):
            raise ValueError("funding curve must be strictly increasing")

    def at(self, weeks: int) -> FundingCurvePoint:
        if weeks <= 0:
            raise ValueError("weeks must be positive")
        if weeks <= self.points[0].weeks:
            p = self.points[0]
            return FundingCurvePoint(weeks, p.reference_rate, p.funding_basis, p.liquidity_term_premium)
        if weeks >= self.points[-1].weeks:
            p = self.points[-1]
            return FundingCurvePoint(weeks, p.reference_rate, p.funding_basis, p.liquidity_term_premium)
        for left, right in zip(self.points, self.points[1:]):
            if left.weeks <= weeks <= right.weeks:
                w = (weeks - left.weeks) / (right.weeks - left.weeks)
                return FundingCurvePoint(
                    weeks=weeks,
                    reference_rate=left.reference_rate + w * (right.reference_rate - left.reference_rate),
                    funding_basis=left.funding_basis + w * (right.funding_basis - left.funding_basis),
                    liquidity_term_premium=(
                        left.liquidity_term_premium
                        + w * (right.liquidity_term_premium - left.liquidity_term_premium)
                    ),
                )
        raise AssertionError("unreachable funding-curve interpolation")


@dataclass(frozen=True)
class BorrowerFinancials:
    dscr: float
    ltv: float

    def __post_init__(self) -> None:
        _finite_nonnegative(self.dscr, "dscr")
        _finite_nonnegative(self.ltv, "ltv")


@dataclass(frozen=True)
class UnderwritingLimits:
    max_pd_horizon: float = 0.25
    max_lgd: float = 0.70
    min_dscr: float = 1.20
    max_ltv: float = 0.80

    def __post_init__(self) -> None:
        _unit_interval(self.max_pd_horizon, "max_pd_horizon")
        _unit_interval(self.max_lgd, "max_lgd")
        _finite_nonnegative(self.min_dscr, "min_dscr")
        _finite_nonnegative(self.max_ltv, "max_ltv")


@dataclass(frozen=True)
class LoanPricingRequest:
    principal: float
    duration_weeks: int
    risk_profile: BorrowerRiskProfile
    borrower_financials: BorrowerFinancials
    annual_capital_charge: float = 0.0
    annual_operating_cost: float = 0.0
    target_margin: float = 0.0
    external_first_loss_share: float = 0.0

    def __post_init__(self) -> None:
        if not isfinite(self.principal) or self.principal <= 0.0:
            raise ValueError("principal must be finite and positive")
        if self.duration_weeks <= 0:
            raise ValueError("duration_weeks must be positive")
        for name in ("annual_capital_charge", "annual_operating_cost", "target_margin"):
            _finite_nonnegative(getattr(self, name), name)
        _unit_interval(self.external_first_loss_share, "external_first_loss_share")


@dataclass(frozen=True)
class LoanPriceQuote:
    approved: bool
    rating: str
    duration_weeks: int
    pd_horizon: float
    lgd: float
    ead_factor: float
    reference_rate: float
    funding_basis: float
    liquidity_term_premium: float
    expected_loss_share: float
    credit_risk_spread: float
    capital_charge: float
    operating_cost: float
    target_margin: float
    annual_rate: float
    reason: str


class RiskBasedLoanPricer:
    """Term-structured bank pricing and underwriting gate.

    The loan rate is not a single project yield. It is assembled from a funding
    reference (for example a policy-rate-linked or internal FTP curve), funding
    basis, term/liquidity premium, credit-risk compensation, capital charge,
    operating cost and target margin.

    Rating/scoring protects the balance sheet twice: first through PD/LGD/EAD
    used in price, and second through hard underwriting limits. A sufficiently
    risky borrower can therefore be `NO ACTION` even if a mathematically huge
    interest rate would cover expected loss.
    """

    def __init__(self, funding_curve: FundingCurve, limits: UnderwritingLimits | None = None) -> None:
        self.funding_curve = funding_curve
        self.limits = limits or UnderwritingLimits()

    @staticmethod
    def _risk_spread(point: TermRiskPoint, duration_weeks: int, first_loss_share: float) -> tuple[float, float]:
        years = duration_weeks / 52.0
        gross_expected_loss = point.pd * point.lgd * point.ead_factor
        net_expected_loss = max(0.0, gross_expected_loss - first_loss_share)
        # Uniform-default-timing approximation for exposure that survives long
        # enough to earn contractual spread. Production pricing can replace this
        # with cash-flow-level hazard integration.
        survival_exposure = max(EPS, 1.0 - 0.5 * point.pd)
        annualized = net_expected_loss / max(EPS, years * survival_exposure)
        return net_expected_loss, annualized

    def quote(self, request: LoanPricingRequest) -> LoanPriceQuote:
        risk = request.risk_profile.at(request.duration_weeks)
        funds = self.funding_curve.at(request.duration_weeks)
        expected_loss, risk_spread = self._risk_spread(
            risk, request.duration_weeks, request.external_first_loss_share
        )
        annual_rate = (
            funds.reference_rate
            + funds.funding_basis
            + funds.liquidity_term_premium
            + risk_spread
            + request.annual_capital_charge
            + request.annual_operating_cost
            + request.target_margin
        )

        reasons: list[str] = []
        if risk.pd > self.limits.max_pd_horizon:
            reasons.append("horizon PD exceeds policy limit")
        if risk.lgd > self.limits.max_lgd:
            reasons.append("LGD exceeds policy limit")
        if request.borrower_financials.dscr < self.limits.min_dscr:
            reasons.append("DSCR below policy minimum")
        if request.borrower_financials.ltv > self.limits.max_ltv:
            reasons.append("LTV above policy maximum")
        approved = not reasons
        return LoanPriceQuote(
            approved=approved,
            rating=request.risk_profile.rating,
            duration_weeks=request.duration_weeks,
            pd_horizon=risk.pd,
            lgd=risk.lgd,
            ead_factor=risk.ead_factor,
            reference_rate=funds.reference_rate,
            funding_basis=funds.funding_basis,
            liquidity_term_premium=funds.liquidity_term_premium,
            expected_loss_share=expected_loss,
            credit_risk_spread=risk_spread,
            capital_charge=request.annual_capital_charge,
            operating_cost=request.annual_operating_cost,
            target_margin=request.target_margin,
            annual_rate=annual_rate,
            reason=("risk and affordability gates pass" if approved else "NO ACTION: " + "; ".join(reasons)),
        )


def make_flat_policy_rate_curve(
    policy_rate: float,
    tenors_weeks: Iterable[int] = (4, 13, 26, 52, 104, 260),
    funding_basis: float = 0.0,
    liquidity_premiums: Iterable[float] | None = None,
) -> FundingCurve:
    """Research helper; production should use the bank's actual FTP/market curve."""
    tenors = tuple(tenors_weeks)
    if liquidity_premiums is None:
        premiums = tuple(0.0 for _ in tenors)
    else:
        premiums = tuple(liquidity_premiums)
    if len(tenors) != len(premiums):
        raise ValueError("tenors_weeks and liquidity_premiums length mismatch")
    return FundingCurve(tuple(
        FundingCurvePoint(w, policy_rate, funding_basis, p)
        for w, p in zip(tenors, premiums)
    ))
