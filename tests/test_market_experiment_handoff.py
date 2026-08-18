from decimal import Decimal

import pytest

from sinergy_rnd_handoff import (
    MarketExperimentInvariantError,
    MarketExperimentResult,
    review_market_experiment,
)


def _result(**changes) -> MarketExperimentResult:
    kwargs = {
        "experiment_id": "amm-fork-001",
        "experiment_class": "AMM",
        "mode": "FORK",
        "network": "Base",
        "reporting_asset": "USDC",
        "external_assets_before": "100",
        "external_liabilities_before": "0",
        "external_assets_after": "101",
        "external_liabilities_after": "0",
        "net_new_external_capital": "0",
        "externally_observed_revenue": "1.2",
        "gas_cost": "0.05",
        "venue_fees": "0.03",
        "bridge_fees": "0.02",
        "flash_fees": "0.01",
        "other_external_costs": "0.01",
        "mint_notional": "1000000",
        "flash_principal_peak": "5000000",
        "internal_mark_change": "999999",
        "self_token_mark_change": "888888",
        "revenue_evidence_digest": "aa" * 32,
        "execution_evidence_digest": "bb" * 32,
    }
    kwargs.update(changes)
    return MarketExperimentResult(**kwargs)


def test_internal_marks_mint_and_flash_principal_do_not_change_pnl_candidate() -> None:
    base = _result()
    extreme = _result(
        mint_notional="999999999999",
        flash_principal_peak="777777777777",
        internal_mark_change="123456789",
        self_token_mark_change="987654321",
    )
    assert base.external_pnl_candidate == Decimal("1.08")
    assert extreme.external_pnl_candidate == base.external_pnl_candidate


def test_candidate_is_explicit_revenue_minus_all_external_costs() -> None:
    result = _result(
        externally_observed_revenue="2",
        gas_cost="0.1",
        venue_fees="0.2",
        bridge_fees="0.3",
        flash_fees="0.4",
        other_external_costs="0.5",
    )
    assert result.total_external_costs == Decimal("1.5")
    assert result.external_pnl_candidate == Decimal("0.5")


def test_external_nav_surplus_is_diagnostic_not_pnl_formula() -> None:
    result = _result(
        external_assets_before="100",
        external_assets_after="140",
        net_new_external_capital="0",
        externally_observed_revenue="0",
        revenue_evidence_digest=None,
        gas_cost="1",
        venue_fees="0",
        bridge_fees="0",
        flash_fees="0",
        other_external_costs="0",
    )
    assert result.external_nav_surplus_after_capital == Decimal("40")
    assert result.external_pnl_candidate == Decimal("-1")


def test_new_external_capital_does_not_become_pnl() -> None:
    result = _result(
        external_assets_before="100",
        external_assets_after="200",
        net_new_external_capital="100",
        externally_observed_revenue="0",
        revenue_evidence_digest=None,
        gas_cost="0",
        venue_fees="0",
        bridge_fees="0",
        flash_fees="0",
        other_external_costs="0",
    )
    assert result.external_nav_surplus_after_capital == Decimal("0")
    assert result.external_pnl_candidate == Decimal("0")


def test_positive_revenue_requires_independent_evidence_digest() -> None:
    with pytest.raises(MarketExperimentInvariantError):
        _result(externally_observed_revenue="1", revenue_evidence_digest=None)


def test_fork_or_live_result_requires_execution_evidence() -> None:
    with pytest.raises(MarketExperimentInvariantError):
        _result(execution_evidence_digest=None)


def test_handoff_never_recognizes_financial_os_profit() -> None:
    review = review_market_experiment(_result())
    assert review.status == "HANDOFF_REVIEWABLE"
    assert review.financial_os_recognition == "NOT_PERFORMED"


@pytest.mark.parametrize("field", [
    "external_assets_before", "external_liabilities_before",
    "external_assets_after", "external_liabilities_after",
    "net_new_external_capital", "externally_observed_revenue",
    "gas_cost", "venue_fees", "bridge_fees", "flash_fees",
    "other_external_costs", "mint_notional", "flash_principal_peak",
    "internal_mark_change", "self_token_mark_change",
])
@pytest.mark.parametrize("bad", ["NaN", "Infinity", "-Infinity"])
def test_all_numeric_inputs_are_finite(field: str, bad: str) -> None:
    with pytest.raises(MarketExperimentInvariantError):
        _result(**{field: bad})


def test_serialization_uses_unique_decimal_text() -> None:
    payload = _result(
        external_assets_before="100.000",
        gas_cost="0.0500",
        internal_mark_change="-0.000",
    ).to_dict()
    assert payload["external_assets_before"] == "100"
    assert payload["gas_cost"] == "0.05"
    assert payload["internal_mark_change"] == "0"


def test_rnd_repository_cannot_claim_accounting_authority() -> None:
    with pytest.raises(MarketExperimentInvariantError):
        _result(accounting_authority="Shtenco/ai_financial_system")
