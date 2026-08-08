from __future__ import annotations

from dataclasses import dataclass, field
from math import isfinite
from typing import Iterable

EPS = 1e-9


def _ratio(value: float, name: str) -> None:
    if not isfinite(value) or not 0.0 <= value <= 1.0:
        raise ValueError(f"{name} must be finite and in [0,1]")


def _nonnegative(value: float, name: str) -> None:
    if not isfinite(value) or value < 0.0:
        raise ValueError(f"{name} must be finite and non-negative")


@dataclass(frozen=True)
class FXSettlementProfile:
    """Observed or scenario currency composition of import settlement.

    The profile is a settlement-flow description, not a claim about the origin of
    goods. In production it should be sourced from bank/MetaPay invoices and
    reconciled payment rails, not inferred from marketplace GMV alone.
    """

    rub: float
    cny: float
    usd_eur: float
    other: float

    def __post_init__(self) -> None:
        for name in ("rub", "cny", "usd_eur", "other"):
            _ratio(getattr(self, name), name)
        if abs(self.rub + self.cny + self.usd_eur + self.other - 1.0) > 1e-9:
            raise ValueError("FX settlement shares must sum to 1")

    def allocate(self, import_value: float) -> dict[str, float]:
        _nonnegative(import_value, "import_value")
        return {
            "RUB": import_value * self.rub,
            "CNY": import_value * self.cny,
            "USD_EUR": import_value * self.usd_eur,
            "OTHER": import_value * self.other,
        }


@dataclass(frozen=True)
class MarketplaceObservation:
    """One reconciled marketplace observation in constant-price reporting value.

    `local_channel_share` describes where the customer bought the item.
    `domestic_channel_import_content` describes estimated origin of goods sold by
    local sellers/platforms. These are intentionally separate because a locally
    sold SKU may still be imported.
    """

    period: str
    delivered_constant_value: float
    saleable_inventory_constant_value: float
    local_channel_share: float
    crossborder_share: float
    domestic_channel_import_content: float
    returns_share: float = 0.0

    def __post_init__(self) -> None:
        _nonnegative(self.delivered_constant_value, "delivered_constant_value")
        _nonnegative(self.saleable_inventory_constant_value, "saleable_inventory_constant_value")
        for name in (
            "local_channel_share",
            "crossborder_share",
            "domestic_channel_import_content",
            "returns_share",
        ):
            _ratio(getattr(self, name), name)
        if abs(self.local_channel_share + self.crossborder_share - 1.0) > 1e-9:
            raise ValueError("local and cross-border channel shares must sum to 1")

    @property
    def net_delivered_value(self) -> float:
        return self.delivered_constant_value * (1.0 - self.returns_share)

    @property
    def import_origin_share(self) -> float:
        return self.crossborder_share + self.local_channel_share * self.domestic_channel_import_content

    @property
    def domestic_origin_share(self) -> float:
        return 1.0 - self.import_origin_share

    @property
    def domestic_origin_goods(self) -> float:
        return self.net_delivered_value * self.domestic_origin_share

    @property
    def import_origin_goods(self) -> float:
        return self.net_delivered_value * self.import_origin_share

    @property
    def goods_availability_base(self) -> float:
        return self.net_delivered_value + self.saleable_inventory_constant_value


@dataclass(frozen=True)
class GoodsBaseDelta:
    domestic_goods_delta: float
    import_goods_delta: float
    inventory_delta: float

    @property
    def availability_delta(self) -> float:
        return self.domestic_goods_delta + self.import_goods_delta + self.inventory_delta


class MarketplaceGoodsObservatory:
    """Builds a real-economy goods signal from reconciled marketplace states.

    GMV alone is not physical output. Production deployments should combine
    delivered/refunded orders, warehouse inventory, fiscal receipts, customs/HS
    origin and bank/MetaPay settlement evidence. This class only performs the
    deterministic accounting decomposition after those values are supplied.
    """

    @staticmethod
    def delta(previous: MarketplaceObservation, current: MarketplaceObservation) -> GoodsBaseDelta:
        return GoodsBaseDelta(
            domestic_goods_delta=current.domestic_origin_goods - previous.domestic_origin_goods,
            import_goods_delta=current.import_origin_goods - previous.import_origin_goods,
            inventory_delta=(
                current.saleable_inventory_constant_value
                - previous.saleable_inventory_constant_value
            ),
        )


@dataclass(frozen=True)
class SavingsFundingState:
    new_financial_savings: float
    capture_share: float
    term_eligible_share: float
    bank_transform_cap: float

    def __post_init__(self) -> None:
        _nonnegative(self.new_financial_savings, "new_financial_savings")
        for name in ("capture_share", "term_eligible_share", "bank_transform_cap"):
            _ratio(getattr(self, name), name)

    @property
    def orchestrated_savings(self) -> float:
        return self.new_financial_savings * self.capture_share

    @property
    def term_eligible_savings(self) -> float:
        return self.orchestrated_savings * self.term_eligible_share

    @property
    def maximum_new_productive_funding(self) -> float:
        return self.term_eligible_savings * self.bank_transform_cap


@dataclass(frozen=True)
class InvestmentBankBid:
    bank_id: str
    funded_amount: float
    annual_funding_cost: float
    capital_charge: float
    maturity_weeks: int
    risk_score: float
    funding_currency: str = "RUB"
    fx_hedged: bool = True

    def __post_init__(self) -> None:
        if not self.bank_id.strip():
            raise ValueError("bank_id is required")
        _nonnegative(self.funded_amount, "funded_amount")
        _nonnegative(self.annual_funding_cost, "annual_funding_cost")
        _nonnegative(self.capital_charge, "capital_charge")
        _ratio(self.risk_score, "risk_score")
        if self.maturity_weeks <= 0:
            raise ValueError("maturity_weeks must be positive")

    @property
    def all_in_score(self) -> float:
        # Lower is better. Risk is a capital/risk penalty, not a probability forecast.
        return self.annual_funding_cost + self.capital_charge + 0.10 * self.risk_score


@dataclass(frozen=True)
class AuctionAllocation:
    bank_id: str
    amount: float
    all_in_score: float


@dataclass(frozen=True)
class ProductiveCapitalAuctionResult:
    requested_private_funding: float
    allocated_private_funding: float
    allocations: tuple[AuctionAllocation, ...]
    fully_funded: bool


class ProductiveCapitalAuction:
    """Competitive investment-bank funding before any escrow release.

    Banks invest real funded capital. The targeted monetary authorisation is not
    a guaranteed bank return and is not counted as bank collateral or HardNAV.
    """

    def __init__(self, max_bank_concentration: float = 0.35) -> None:
        _ratio(max_bank_concentration, "max_bank_concentration")
        if max_bank_concentration <= 0:
            raise ValueError("max_bank_concentration must be positive")
        self.max_bank_concentration = max_bank_concentration

    def clear(
        self,
        *,
        requested_private_funding: float,
        project_maturity_weeks: int,
        bids: Iterable[InvestmentBankBid],
    ) -> ProductiveCapitalAuctionResult:
        _nonnegative(requested_private_funding, "requested_private_funding")
        if project_maturity_weeks <= 0:
            raise ValueError("project_maturity_weeks must be positive")

        eligible = [
            bid
            for bid in bids
            if bid.funded_amount > EPS
            and bid.maturity_weeks > project_maturity_weeks
            and (bid.funding_currency.upper() == "RUB" or bid.fx_hedged)
        ]
        eligible.sort(key=lambda x: (x.all_in_score, x.risk_score, x.bank_id))

        remaining = requested_private_funding
        allocations: list[AuctionAllocation] = []
        concentration_cap = requested_private_funding * self.max_bank_concentration
        for bid in eligible:
            if remaining <= EPS:
                break
            amount = min(remaining, bid.funded_amount, concentration_cap)
            if amount <= EPS:
                continue
            allocations.append(AuctionAllocation(bid.bank_id, amount, bid.all_in_score))
            remaining -= amount

        allocated = requested_private_funding - remaining
        return ProductiveCapitalAuctionResult(
            requested_private_funding=requested_private_funding,
            allocated_private_funding=allocated,
            allocations=tuple(allocations),
            fully_funded=remaining <= EPS,
        )


@dataclass(frozen=True)
class TargetedEscrowAuthorization:
    """Conditional monetary authorisation, not circulating money.

    A smart contract may materialise non-transferable escrow units, but the
    canonical balance sheet should treat them as a conditional commitment until a
    beneficiary obtains an enforceable claim. Only `released_amount` becomes a
    monetary liability and only against a verified performing asset/claim.
    """

    project_id: str
    authorized_amount: float
    target_goods_increase: float
    target_productive_base_increase: float
    goods_weight: float = 0.60
    productive_base_weight: float = 0.40
    import_goods_haircut: float = 0.30

    def __post_init__(self) -> None:
        if not self.project_id.strip():
            raise ValueError("project_id is required")
        for name in (
            "authorized_amount",
            "target_goods_increase",
            "target_productive_base_increase",
        ):
            _nonnegative(getattr(self, name), name)
        for name in ("goods_weight", "productive_base_weight", "import_goods_haircut"):
            _ratio(getattr(self, name), name)
        if abs(self.goods_weight + self.productive_base_weight - 1.0) > 1e-9:
            raise ValueError("release weights must sum to 1")


@dataclass(frozen=True)
class GrowthProof:
    domestic_goods_increase: float
    import_goods_increase: float
    productive_base_increase: float
    verifier_quorum_ok: bool

    def __post_init__(self) -> None:
        for name in (
            "domestic_goods_increase",
            "import_goods_increase",
            "productive_base_increase",
        ):
            _nonnegative(getattr(self, name), name)


@dataclass(frozen=True)
class EscrowReleaseDecision:
    released_amount: float
    cancelled_amount: float
    goods_score: float
    productive_base_score: float
    release_factor: float
    reason: str


class ProductiveEscrowPolicy:
    @staticmethod
    def release(
        authorization: TargetedEscrowAuthorization,
        proof: GrowthProof,
    ) -> EscrowReleaseDecision:
        if not proof.verifier_quorum_ok:
            return EscrowReleaseDecision(
                released_amount=0.0,
                cancelled_amount=authorization.authorized_amount,
                goods_score=0.0,
                productive_base_score=0.0,
                release_factor=0.0,
                reason="verifier quorum failed",
            )

        eligible_goods = (
            proof.domestic_goods_increase
            + authorization.import_goods_haircut * proof.import_goods_increase
        )
        if authorization.target_goods_increase <= EPS:
            goods_score = 1.0
        else:
            goods_score = min(1.0, eligible_goods / authorization.target_goods_increase)

        if authorization.target_productive_base_increase <= EPS:
            base_score = 1.0
        else:
            base_score = min(
                1.0,
                proof.productive_base_increase
                / authorization.target_productive_base_increase,
            )

        release_factor = min(
            1.0,
            authorization.goods_weight * goods_score
            + authorization.productive_base_weight * base_score,
        )
        released = authorization.authorized_amount * release_factor
        return EscrowReleaseDecision(
            released_amount=released,
            cancelled_amount=authorization.authorized_amount - released,
            goods_score=goods_score,
            productive_base_score=base_score,
            release_factor=release_factor,
            reason="verified milestone release",
        )


@dataclass(frozen=True)
class OrchestratedProductiveFunding:
    private_funding: float
    targeted_authorization: float
    funding_gap: float
    savings_capacity: float
    risk_capacity: float
    liquidity_capacity: float


class FinancialOSRealEconomyOrchestrator:
    """Joins savings transformation, investment-bank bids and conditional money.

    The OS does not replace banks. Banks continue to transform funded savings into
    investment assets. The OS orchestrates maturity/risk limits, capital auctions,
    marketplace/productive verification, and conditional refinancing/liability
    creation after verified economic growth.
    """

    def __init__(self, private_match_ratio: float = 1.0) -> None:
        if not isfinite(private_match_ratio) or private_match_ratio <= 0:
            raise ValueError("private_match_ratio must be positive")
        self.private_match_ratio = private_match_ratio

    def authorize(
        self,
        *,
        requested_targeted_authorization: float,
        savings_state: SavingsFundingState,
        auction_result: ProductiveCapitalAuctionResult,
        risk_capacity: float,
        liquidity_capacity: float,
    ) -> OrchestratedProductiveFunding:
        for name, value in (
            ("requested_targeted_authorization", requested_targeted_authorization),
            ("risk_capacity", risk_capacity),
            ("liquidity_capacity", liquidity_capacity),
        ):
            _nonnegative(value, name)

        private_funding = min(
            auction_result.allocated_private_funding,
            savings_state.maximum_new_productive_funding,
        )
        authorization = min(
            requested_targeted_authorization,
            private_funding / self.private_match_ratio,
            risk_capacity,
            liquidity_capacity,
        )
        return OrchestratedProductiveFunding(
            private_funding=private_funding,
            targeted_authorization=authorization,
            funding_gap=max(0.0, requested_targeted_authorization - authorization),
            savings_capacity=savings_state.maximum_new_productive_funding,
            risk_capacity=risk_capacity,
            liquidity_capacity=liquidity_capacity,
        )
