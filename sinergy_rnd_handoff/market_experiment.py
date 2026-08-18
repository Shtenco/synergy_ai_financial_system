from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation


SCHEMA = "market.experiment-result/v1"
ZERO = Decimal("0")
HEX = frozenset("0123456789abcdef")
ALLOWED_MODES = frozenset({"SIMULATION", "FORK", "LIVE_OBSERVED"})
ALLOWED_CLASSES = frozenset({"AMM", "QE_QT", "MEV", "FLASH", "GRAPH", "BRIDGE", "OTHER"})


class MarketExperimentInvariantError(ValueError):
    """Raised when a preserved financial R&D result is unsafe or ambiguous."""


def _decimal(value: Decimal | int | str, field_name: str) -> Decimal:
    if isinstance(value, bool):
        raise MarketExperimentInvariantError(f"{field_name} must be a finite decimal")
    try:
        result = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise MarketExperimentInvariantError(f"{field_name} must be a finite decimal") from exc
    if not result.is_finite():
        raise MarketExperimentInvariantError(f"{field_name} must be finite")
    return result


def _nonnegative(value: Decimal | int | str, field_name: str) -> Decimal:
    result = _decimal(value, field_name)
    if result < ZERO:
        raise MarketExperimentInvariantError(f"{field_name} must be non-negative")
    return result


def _decimal_text(value: Decimal | int | str, field_name: str) -> str:
    number = _decimal(value, field_name)
    if number == ZERO:
        return "0"
    text = format(number, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text


def _text(value: str, field_name: str) -> str:
    if not isinstance(value, str):
        raise MarketExperimentInvariantError(f"{field_name} must be text")
    result = value.strip()
    if not result:
        raise MarketExperimentInvariantError(f"{field_name} is required")
    return result


def _hex64(value: str | None, field_name: str) -> str | None:
    if value is None:
        return None
    result = _text(value, field_name).lower()
    if len(result) != 64 or any(char not in HEX for char in result):
        raise MarketExperimentInvariantError(
            f"{field_name} must be a 64-character hexadecimal digest"
        )
    return result


@dataclass(frozen=True)
class MarketExperimentResult:
    experiment_id: str
    experiment_class: str
    mode: str
    network: str
    reporting_asset: str
    external_assets_before: Decimal
    external_liabilities_before: Decimal
    external_assets_after: Decimal
    external_liabilities_after: Decimal
    net_new_external_capital: Decimal
    externally_observed_revenue: Decimal
    gas_cost: Decimal
    venue_fees: Decimal
    bridge_fees: Decimal
    flash_fees: Decimal
    other_external_costs: Decimal
    mint_notional: Decimal = ZERO
    flash_principal_peak: Decimal = ZERO
    internal_mark_change: Decimal = ZERO
    self_token_mark_change: Decimal = ZERO
    revenue_evidence_digest: str | None = None
    execution_evidence_digest: str | None = None
    classification: str = "RND_ONLY"
    accounting_authority: str = "Shtenco/synergy_financial_os"

    def __post_init__(self) -> None:
        experiment_id = _text(self.experiment_id, "experiment_id")
        experiment_class = _text(self.experiment_class, "experiment_class").upper()
        mode = _text(self.mode, "mode").upper()
        network = _text(self.network, "network")
        reporting_asset = _text(self.reporting_asset, "reporting_asset").upper()
        if experiment_class not in ALLOWED_CLASSES:
            raise MarketExperimentInvariantError(
                f"unsupported experiment_class: {experiment_class}"
            )
        if mode not in ALLOWED_MODES:
            raise MarketExperimentInvariantError(f"unsupported mode: {mode}")
        if self.classification != "RND_ONLY":
            raise MarketExperimentInvariantError("financial R&D result must remain RND_ONLY")
        if self.accounting_authority != "Shtenco/synergy_financial_os":
            raise MarketExperimentInvariantError("Financial OS is the only accounting authority")

        nonnegative_fields = (
            "external_assets_before",
            "external_liabilities_before",
            "external_assets_after",
            "external_liabilities_after",
            "externally_observed_revenue",
            "gas_cost",
            "venue_fees",
            "bridge_fees",
            "flash_fees",
            "other_external_costs",
            "mint_notional",
            "flash_principal_peak",
        )
        for field_name in nonnegative_fields:
            object.__setattr__(
                self,
                field_name,
                _nonnegative(getattr(self, field_name), field_name),
            )
        for field_name in (
            "net_new_external_capital",
            "internal_mark_change",
            "self_token_mark_change",
        ):
            object.__setattr__(
                self,
                field_name,
                _decimal(getattr(self, field_name), field_name),
            )

        revenue_digest = _hex64(self.revenue_evidence_digest, "revenue_evidence_digest")
        execution_digest = _hex64(
            self.execution_evidence_digest, "execution_evidence_digest"
        )
        if self.externally_observed_revenue > ZERO and revenue_digest is None:
            raise MarketExperimentInvariantError(
                "positive externally_observed_revenue requires evidence digest"
            )
        if mode in {"FORK", "LIVE_OBSERVED"} and execution_digest is None:
            raise MarketExperimentInvariantError(
                f"{mode} result requires execution_evidence_digest"
            )

        object.__setattr__(self, "experiment_id", experiment_id)
        object.__setattr__(self, "experiment_class", experiment_class)
        object.__setattr__(self, "mode", mode)
        object.__setattr__(self, "network", network)
        object.__setattr__(self, "reporting_asset", reporting_asset)
        object.__setattr__(self, "revenue_evidence_digest", revenue_digest)
        object.__setattr__(self, "execution_evidence_digest", execution_digest)

    @property
    def external_nav_before(self) -> Decimal:
        return self.external_assets_before - self.external_liabilities_before

    @property
    def external_nav_after(self) -> Decimal:
        return self.external_assets_after - self.external_liabilities_after

    @property
    def external_nav_surplus_after_capital(self) -> Decimal:
        """Diagnostic only; asset hardening can change this without creating P&L."""

        return self.external_nav_after - self.external_nav_before - self.net_new_external_capital

    @property
    def total_external_costs(self) -> Decimal:
        return (
            self.gas_cost
            + self.venue_fees
            + self.bridge_fees
            + self.flash_fees
            + self.other_external_costs
        )

    @property
    def external_pnl_candidate(self) -> Decimal:
        """Explicit revenue minus external costs; no marks, mint or flash principal."""

        return self.externally_observed_revenue - self.total_external_costs

    def to_dict(self) -> dict[str, object]:
        decimal_fields = {
            "external_assets_before": self.external_assets_before,
            "external_liabilities_before": self.external_liabilities_before,
            "external_assets_after": self.external_assets_after,
            "external_liabilities_after": self.external_liabilities_after,
            "net_new_external_capital": self.net_new_external_capital,
            "externally_observed_revenue": self.externally_observed_revenue,
            "gas_cost": self.gas_cost,
            "venue_fees": self.venue_fees,
            "bridge_fees": self.bridge_fees,
            "flash_fees": self.flash_fees,
            "other_external_costs": self.other_external_costs,
            "total_external_costs": self.total_external_costs,
            "mint_notional": self.mint_notional,
            "flash_principal_peak": self.flash_principal_peak,
            "internal_mark_change": self.internal_mark_change,
            "self_token_mark_change": self.self_token_mark_change,
            "external_nav_before": self.external_nav_before,
            "external_nav_after": self.external_nav_after,
            "external_nav_surplus_after_capital": self.external_nav_surplus_after_capital,
            "external_pnl_candidate": self.external_pnl_candidate,
        }
        payload: dict[str, object] = {
            "schema": SCHEMA,
            "experiment_id": self.experiment_id,
            "experiment_class": self.experiment_class,
            "mode": self.mode,
            "network": self.network,
            "reporting_asset": self.reporting_asset,
            "classification": self.classification,
            "accounting_authority": self.accounting_authority,
            "revenue_evidence_digest": self.revenue_evidence_digest,
            "execution_evidence_digest": self.execution_evidence_digest,
        }
        payload.update(
            {
                field_name: _decimal_text(value, field_name)
                for field_name, value in decimal_fields.items()
            }
        )
        return payload


@dataclass(frozen=True)
class MarketExperimentReview:
    status: str
    blockers: tuple[str, ...]
    external_pnl_candidate: Decimal
    financial_os_recognition: str = "NOT_PERFORMED"


def review_market_experiment(result: MarketExperimentResult) -> MarketExperimentReview:
    blockers: set[str] = set()
    if result.externally_observed_revenue > ZERO and result.revenue_evidence_digest is None:
        blockers.add("REVENUE_EVIDENCE_MISSING")
    if result.mode in {"FORK", "LIVE_OBSERVED"} and result.execution_evidence_digest is None:
        blockers.add("EXECUTION_EVIDENCE_MISSING")
    status = "HANDOFF_REVIEWABLE" if not blockers else "RND_BLOCKED"
    return MarketExperimentReview(
        status=status,
        blockers=tuple(sorted(blockers)),
        external_pnl_candidate=result.external_pnl_candidate,
        financial_os_recognition="NOT_PERFORMED",
    )
