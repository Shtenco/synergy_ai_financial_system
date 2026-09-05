from __future__ import annotations

from dataclasses import asdict, dataclass
from decimal import Decimal
from hashlib import sha256
import json

D = Decimal


@dataclass(frozen=True, slots=True)
class DexExternalProfitEvidence:
    """Conservative DEX settlement evidence for the MetaPay External Profit Bus.

    `pre_external_balance` and `post_external_balance` must refer to the same
    externally redeemable settlement asset and the same consolidated economic
    perimeter. Internal protocol transfers (for example executor -> treasury tax)
    must be consolidated rather than treated as external costs.
    """

    evidence_id: str
    route_id: str
    settlement_asset: str
    pre_external_balance: Decimal
    post_external_balance: Decimal
    external_costs_remaining: Decimal = D("0")
    flash_premium_remaining: Decimal = D("0")
    flash_principal_repaid: bool = True
    settlement_realized: bool = False
    independent_external_counterparty: bool = False
    chain_id: int | None = None
    tx_hash: str | None = None
    block_number: int | None = None
    provider_references: tuple[str, ...] = ()
    internal_mint_quantity: Decimal = D("0")
    internal_mark_delta: Decimal = D("0")

    @property
    def external_cash_delta(self) -> Decimal:
        return self.post_external_balance - self.pre_external_balance

    @property
    def candidate_external_pnl(self) -> Decimal:
        return (
            self.external_cash_delta
            - self.external_costs_remaining
            - self.flash_premium_remaining
        )

    @property
    def admissible(self) -> bool:
        return bool(
            self.settlement_realized
            and self.independent_external_counterparty
            and self.flash_principal_repaid
            and self.tx_hash
            and self.block_number is not None
            and self.candidate_external_pnl > 0
        )

    def to_metapay_payload(self) -> dict[str, str | bool | list[str]]:
        """Return the cross-repo wire payload expected by MetaPay's profit gate.

        DEX evidence is balance-delta based, so input principal is represented as
        zero and the already-consolidated external balance delta is passed as
        `settled_output`. This avoids counting working principal twice.
        """
        route_digest = self.digest()
        return {
            "evidence_id": self.evidence_id,
            "source": "DEX_ARBITRAGE",
            "settlement_asset": self.settlement_asset,
            "input_amount": "0",
            "settled_output": str(self.external_cash_delta),
            "external_costs": str(self.external_costs_remaining),
            "flash_premium": str(self.flash_premium_remaining),
            "settlement_realized": self.settlement_realized,
            "independent_external_counterparty": self.independent_external_counterparty,
            "flash_principal_repaid": self.flash_principal_repaid,
            "provider_references": list(self.provider_references),
            "route_digest": route_digest,
            "internal_mint_quantity": str(self.internal_mint_quantity),
            "internal_mark_delta": str(self.internal_mark_delta),
        }

    def digest(self) -> str:
        canonical = {
            key: self._json_value(value)
            for key, value in sorted(asdict(self).items())
        }
        encoded = json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode()
        return sha256(encoded).hexdigest()

    @staticmethod
    def _json_value(value):
        if isinstance(value, Decimal):
            return str(value)
        if isinstance(value, tuple):
            return list(value)
        return value


def assert_external_profit_invariants(evidence: DexExternalProfitEvidence) -> None:
    if evidence.pre_external_balance < 0 or evidence.post_external_balance < 0:
        raise ValueError("external balances must be non-negative")
    if evidence.external_costs_remaining < 0 or evidence.flash_premium_remaining < 0:
        raise ValueError("costs must be non-negative")
    if not evidence.settlement_asset.strip():
        raise ValueError("settlement asset is required")
    if evidence.settlement_realized and not evidence.tx_hash:
        raise ValueError("realized DEX settlement requires tx hash")
    if evidence.settlement_realized and evidence.block_number is None:
        raise ValueError("realized DEX settlement requires block number")
    if evidence.internal_mint_quantity < 0:
        raise ValueError("internal mint quantity cannot be negative")
