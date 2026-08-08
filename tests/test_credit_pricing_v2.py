from financial_os_v4.credit_pricing_v2 import (
    BorrowerFinancials,
    BorrowerRiskProfile,
    LoanPricingRequest,
    RiskBasedLoanPricer,
    TermRiskPoint,
    UnderwritingLimits,
    make_flat_policy_rate_curve,
)


def profile() -> BorrowerRiskProfile:
    return BorrowerRiskProfile(
        "BBB-internal",
        (
            TermRiskPoint(14, 0.008, 0.35, 1.0),
            TermRiskPoint(52, 0.030, 0.35, 1.0),
            TermRiskPoint(156, 0.110, 0.40, 0.9),
        ),
    )


def test_rate_contains_policy_funding_term_risk_and_cost_components() -> None:
    curve = make_flat_policy_rate_curve(
        0.14,
        tenors_weeks=(14, 52, 156),
        funding_basis=0.0125,
        liquidity_premiums=(0.0025, 0.0050, 0.0125),
    )
    quote = RiskBasedLoanPricer(curve).quote(
        LoanPricingRequest(
            principal=100_000_000,
            duration_weeks=52,
            risk_profile=profile(),
            borrower_financials=BorrowerFinancials(dscr=1.5, ltv=0.60),
            annual_capital_charge=0.010,
            annual_operating_cost=0.0075,
            target_margin=0.0125,
        )
    )
    assert quote.approved
    assert quote.reference_rate == 0.14
    assert quote.credit_risk_spread > 0
    assert quote.annual_rate > quote.reference_rate


def test_same_rating_has_term_specific_pd_and_price() -> None:
    curve = make_flat_policy_rate_curve(
        0.14,
        tenors_weeks=(14, 52, 156),
        funding_basis=0.0125,
        liquidity_premiums=(0.0025, 0.0050, 0.0125),
    )
    pricer = RiskBasedLoanPricer(curve)
    common = dict(
        principal=100_000_000,
        risk_profile=profile(),
        borrower_financials=BorrowerFinancials(dscr=1.5, ltv=0.60),
        annual_capital_charge=0.010,
        annual_operating_cost=0.0075,
        target_margin=0.0125,
    )
    short = pricer.quote(LoanPricingRequest(duration_weeks=14, **common))
    long = pricer.quote(LoanPricingRequest(duration_weeks=156, **common))
    assert short.pd_horizon < long.pd_horizon
    assert short.liquidity_term_premium < long.liquidity_term_premium
    assert short.annual_rate < long.annual_rate


def test_rating_is_not_only_price_because_hard_limits_can_reject() -> None:
    risky = BorrowerRiskProfile(
        "B-internal",
        (
            TermRiskPoint(52, 0.18, 0.60),
            TermRiskPoint(156, 0.45, 0.65),
        ),
    )
    curve = make_flat_policy_rate_curve(0.14, tenors_weeks=(52, 156))
    quote = RiskBasedLoanPricer(
        curve,
        UnderwritingLimits(max_pd_horizon=0.25, max_lgd=0.70, min_dscr=1.20, max_ltv=0.80),
    ).quote(
        LoanPricingRequest(
            principal=50_000_000,
            duration_weeks=156,
            risk_profile=risky,
            borrower_financials=BorrowerFinancials(dscr=1.4, ltv=0.70),
        )
    )
    assert not quote.approved
    assert "NO ACTION" in quote.reason


def test_first_loss_reduces_expected_loss_component_but_not_reference_rate() -> None:
    curve = make_flat_policy_rate_curve(0.14, tenors_weeks=(52,))
    pricer = RiskBasedLoanPricer(curve)
    base = dict(
        principal=100_000_000,
        duration_weeks=52,
        risk_profile=profile(),
        borrower_financials=BorrowerFinancials(dscr=1.5, ltv=0.60),
    )
    no_support = pricer.quote(LoanPricingRequest(**base))
    protected = pricer.quote(LoanPricingRequest(external_first_loss_share=0.005, **base))
    assert protected.reference_rate == no_support.reference_rate
    assert protected.expected_loss_share < no_support.expected_loss_share
    assert protected.annual_rate < no_support.annual_rate


def test_dscr_and_ltv_can_reject_even_good_rating() -> None:
    curve = make_flat_policy_rate_curve(0.14, tenors_weeks=(52,))
    quote = RiskBasedLoanPricer(curve).quote(
        LoanPricingRequest(
            principal=100_000_000,
            duration_weeks=52,
            risk_profile=profile(),
            borrower_financials=BorrowerFinancials(dscr=0.95, ltv=0.90),
        )
    )
    assert not quote.approved
    assert "DSCR" in quote.reason
    assert "LTV" in quote.reason
