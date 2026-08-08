from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import json

from .core import BalanceSheet, PolicyDecision, TripleMoneyLedger


@dataclass(frozen=True)
class FinancialSnapshot:
    """Portable read-only state for portals, auditors and downstream services.

    The digest is not a digital signature. A production signer/HSM can sign the
    canonical bytes returned by `canonical_bytes()` without changing the schema.
    """

    schema_version: str
    sequence: int
    hard_nav: float
    liquid_nav: float
    economic_nav: float
    hard_assets: float
    external_liabilities: float
    distributable_profit: float
    synt_coverage: float
    synr_nav: float
    syna_nav: float
    policy_mode: str
    policy_invariant_failures: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.sequence < 0:
            raise ValueError("sequence cannot be negative")
        if self.hard_nav > self.liquid_nav + 1e-9:
            raise ValueError("HardNAV cannot exceed LiquidNAV in canonical snapshots")
        if self.liquid_nav > self.economic_nav + 1e-9:
            raise ValueError("LiquidNAV cannot exceed EconomicNAV in canonical snapshots")
        if self.distributable_profit < -1e-9:
            raise ValueError("distributable profit cannot be negative")

    def as_dict(self) -> dict[str, object]:
        data = asdict(self)
        data["policy_invariant_failures"] = list(self.policy_invariant_failures)
        return data

    def canonical_bytes(self) -> bytes:
        return json.dumps(
            self.as_dict(),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")

    @property
    def digest_sha256(self) -> str:
        return sha256(self.canonical_bytes()).hexdigest()

    @classmethod
    def capture(
        cls,
        *,
        sequence: int,
        balance_sheet: BalanceSheet,
        ledger: TripleMoneyLedger,
        policy: PolicyDecision,
        previous_hard_nav: float,
    ) -> FinancialSnapshot:
        return cls(
            schema_version="sinergy-financial-snapshot/v1",
            sequence=sequence,
            hard_nav=balance_sheet.hard_nav,
            liquid_nav=balance_sheet.liquid_nav,
            economic_nav=balance_sheet.economic_nav,
            hard_assets=balance_sheet.hard_assets,
            external_liabilities=balance_sheet.liabilities_total,
            distributable_profit=balance_sheet.distributable_profit(previous_hard_nav),
            synt_coverage=ledger.synt_coverage(),
            synr_nav=ledger.synr_nav(),
            syna_nav=ledger.syna_nav(),
            policy_mode=policy.mode,
            policy_invariant_failures=policy.invariant_failures,
        )
