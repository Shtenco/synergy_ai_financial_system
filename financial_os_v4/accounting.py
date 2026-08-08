from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
from hashlib import sha256
import json
from threading import RLock
from typing import Iterable, Mapping

from .core import AssetPosition, BalanceSheet, LiabilityPosition

D = Decimal
ZERO = D("0")


class LedgerError(ValueError):
    pass


class AccountClass(str, Enum):
    ASSET = "ASSET"
    LIABILITY = "LIABILITY"
    EQUITY = "EQUITY"
    INCOME = "INCOME"
    EXPENSE = "EXPENSE"


class FlowType(str, Enum):
    INTERNAL = "INTERNAL"
    EXTERNAL_CAPITAL = "EXTERNAL_CAPITAL"
    EXTERNAL_REVENUE = "EXTERNAL_REVENUE"
    EXTERNAL_EXPENSE = "EXTERNAL_EXPENSE"
    LIABILITY_ISSUANCE = "LIABILITY_ISSUANCE"
    LIABILITY_REDEMPTION = "LIABILITY_REDEMPTION"
    CREDIT_ORIGINATION = "CREDIT_ORIGINATION"
    CREDIT_REPAYMENT = "CREDIT_REPAYMENT"
    CREDIT_LOSS = "CREDIT_LOSS"
    SETTLEMENT = "SETTLEMENT"


@dataclass(frozen=True, slots=True)
class AccountSpec:
    account_id: str
    name: str
    account_class: AccountClass
    hard_haircut: float = 0.0
    liquid_haircut: float = 0.0
    economic_haircut: float = 0.0
    external: bool = True
    immediate_liability: bool = False
    role: str = ""

    def __post_init__(self) -> None:
        if not self.account_id.strip() or not self.name.strip():
            raise LedgerError("account_id and name are required")
        for field_name in ("hard_haircut", "liquid_haircut", "economic_haircut"):
            value = getattr(self, field_name)
            if not 0.0 <= value <= 1.0:
                raise LedgerError(f"{field_name} must be in [0,1]")
        if self.hard_haircut > self.liquid_haircut + 1e-12:
            raise LedgerError("hard_haircut cannot exceed liquid_haircut")
        if self.liquid_haircut > self.economic_haircut + 1e-12:
            raise LedgerError("liquid_haircut cannot exceed economic_haircut")
        if self.account_class != AccountClass.ASSET:
            if any(abs(getattr(self, field_name)) > 1e-12 for field_name in (
                "hard_haircut", "liquid_haircut", "economic_haircut"
            )):
                raise LedgerError("valuation haircuts belong only to ASSET accounts")
        if self.immediate_liability and self.account_class != AccountClass.LIABILITY:
            raise LedgerError("immediate_liability is valid only for LIABILITY accounts")


@dataclass(frozen=True, slots=True)
class JournalLine:
    account_id: str
    debit: Decimal = ZERO
    credit: Decimal = ZERO
    memo: str = ""

    def __post_init__(self) -> None:
        debit = D(self.debit)
        credit = D(self.credit)
        if debit < 0 or credit < 0:
            raise LedgerError("debit and credit must be non-negative")
        if (debit > 0) == (credit > 0):
            raise LedgerError("each journal line must contain exactly one positive side")
        object.__setattr__(self, "debit", debit)
        object.__setattr__(self, "credit", credit)


@dataclass(frozen=True, slots=True)
class JournalEntry:
    sequence: int
    reference: str
    lines: tuple[JournalLine, ...]
    flow_type: FlowType = FlowType.INTERNAL
    metadata: Mapping[str, str] = field(default_factory=dict)

    @property
    def debit_total(self) -> Decimal:
        return sum((line.debit for line in self.lines), ZERO)

    @property
    def credit_total(self) -> Decimal:
        return sum((line.credit for line in self.lines), ZERO)


class CanonicalDoubleEntryLedger:
    """Append-only reporting-currency ledger for monetary truth.

    The ledger stores reconciled book values in one reporting unit. External
    quantities and market data must be valued before posting. Browser prices,
    self-token marks and virtual TVL therefore cannot silently become profit.
    """

    def __init__(self, reporting_unit: str = "KZT") -> None:
        self.reporting_unit = reporting_unit.upper().strip()
        if not self.reporting_unit:
            raise LedgerError("reporting_unit is required")
        self._accounts: dict[str, AccountSpec] = {}
        self._entries: list[JournalEntry] = []
        self._by_reference: dict[str, JournalEntry] = {}
        self._raw_debits: dict[str, Decimal] = defaultdict(lambda: ZERO)
        self._raw_credits: dict[str, Decimal] = defaultdict(lambda: ZERO)
        self._lock = RLock()

    @property
    def sequence(self) -> int:
        return len(self._entries)

    def register_account(self, spec: AccountSpec) -> None:
        with self._lock:
            if spec.account_id in self._accounts:
                raise LedgerError(f"account already registered: {spec.account_id}")
            self._accounts[spec.account_id] = spec

    def account(self, account_id: str) -> AccountSpec:
        try:
            return self._accounts[account_id]
        except KeyError as exc:
            raise LedgerError(f"unknown account: {account_id}") from exc

    def post(
        self,
        *,
        reference: str,
        lines: Iterable[JournalLine],
        flow_type: FlowType = FlowType.INTERNAL,
        metadata: Mapping[str, str] | None = None,
    ) -> JournalEntry:
        if not reference.strip():
            raise LedgerError("journal reference is required")
        lines_tuple = tuple(lines)
        if len(lines_tuple) < 2:
            raise LedgerError("journal entry requires at least two lines")
        for line in lines_tuple:
            self.account(line.account_id)
        debit_total = sum((line.debit for line in lines_tuple), ZERO)
        credit_total = sum((line.credit for line in lines_tuple), ZERO)
        if debit_total <= 0 or debit_total != credit_total:
            raise LedgerError(
                f"unbalanced journal: debit={debit_total}, credit={credit_total}"
            )

        with self._lock:
            existing = self._by_reference.get(reference)
            if existing is not None:
                return existing
            entry = JournalEntry(
                sequence=self.sequence + 1,
                reference=reference,
                lines=lines_tuple,
                flow_type=flow_type,
                metadata=dict(metadata or {}),
            )
            for line in lines_tuple:
                self._raw_debits[line.account_id] += line.debit
                self._raw_credits[line.account_id] += line.credit
            self._entries.append(entry)
            self._by_reference[reference] = entry
            return entry

    def _normal_balance(self, account_id: str) -> Decimal:
        spec = self.account(account_id)
        debit = self._raw_debits[account_id]
        credit = self._raw_credits[account_id]
        if spec.account_class in (AccountClass.ASSET, AccountClass.EXPENSE):
            value = debit - credit
        else:
            value = credit - debit
        if value < ZERO:
            raise LedgerError(f"abnormal negative balance for {account_id}: {value}")
        return value

    def balance(self, account_id: str) -> Decimal:
        with self._lock:
            return self._normal_balance(account_id)

    def trial_balance(self) -> tuple[Decimal, Decimal]:
        with self._lock:
            debits = sum(self._raw_debits.values(), ZERO)
            credits = sum(self._raw_credits.values(), ZERO)
            return debits, credits

    def assert_balanced(self) -> None:
        debits, credits = self.trial_balance()
        if debits != credits:
            raise LedgerError(f"trial balance mismatch: {debits} != {credits}")

    def entries_since(self, sequence: int) -> tuple[JournalEntry, ...]:
        if sequence < 0 or sequence > self.sequence:
            raise LedgerError("invalid ledger sequence")
        return tuple(self._entries[sequence:])

    def _external_asset_debits(self, entry: JournalEntry) -> Decimal:
        total = ZERO
        for line in entry.lines:
            spec = self.account(line.account_id)
            if spec.account_class == AccountClass.ASSET and spec.external:
                total += line.debit
        return total

    def net_new_capital_since(self, sequence: int) -> float:
        total = ZERO
        for entry in self.entries_since(sequence):
            if entry.flow_type == FlowType.EXTERNAL_CAPITAL:
                total += self._external_asset_debits(entry)
        return float(total)

    def realized_external_revenue_since(self, sequence: int) -> float:
        total = ZERO
        for entry in self.entries_since(sequence):
            if entry.flow_type == FlowType.EXTERNAL_REVENUE:
                total += self._external_asset_debits(entry)
        return float(total)

    def immediate_hard_liabilities(self) -> float:
        total = ZERO
        for account_id, spec in self._accounts.items():
            if (
                spec.account_class == AccountClass.LIABILITY
                and spec.external
                and spec.immediate_liability
            ):
                total += self._normal_balance(account_id)
        return float(total)

    def balance_sheet(self, *, previous_sequence: int = 0) -> BalanceSheet:
        assets: list[AssetPosition] = []
        liabilities: list[LiabilityPosition] = []
        for account_id, spec in self._accounts.items():
            balance = float(self._normal_balance(account_id))
            if balance <= 1e-12:
                continue
            if spec.account_class == AccountClass.ASSET and spec.external:
                assets.append(
                    AssetPosition(
                        name=spec.name,
                        value=balance,
                        hard_haircut=spec.hard_haircut,
                        liquid_haircut=spec.liquid_haircut,
                        economic_haircut=spec.economic_haircut,
                    )
                )
            elif spec.account_class == AccountClass.LIABILITY and spec.external:
                liabilities.append(LiabilityPosition(spec.name, balance))
        return BalanceSheet(
            assets=assets,
            liabilities=liabilities,
            net_new_capital=self.net_new_capital_since(previous_sequence),
        )

    def canonical_state(self) -> dict[str, object]:
        balances = {
            account_id: str(self._normal_balance(account_id))
            for account_id in sorted(self._accounts)
        }
        return {
            "schema_version": "sinergy-double-entry-ledger/v1",
            "reporting_unit": self.reporting_unit,
            "sequence": self.sequence,
            "balances": balances,
        }

    @property
    def digest_sha256(self) -> str:
        raw = json.dumps(
            self.canonical_state(),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
        return sha256(raw).hexdigest()
