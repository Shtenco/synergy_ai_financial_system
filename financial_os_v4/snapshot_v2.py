from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import json
from math import isfinite

from .accounting import CanonicalDoubleEntryLedger
from .core import PolicyDecision
from .maturity import MaturityBook
from .money import SegregatedTripleMoneyLedger


@dataclass(frozen=True)
class FinancialSnapshotV2:
    schema_version: str
    ledger_sequence: int
    ledger_digest_sha256: str
    hard_nav: float
    liquid_nav: float
    economic_nav: float
    hard_assets: float
    external_liabilities: float
    immediate_hard_liabilities: float
    hard_coverage_ratio: float | None
    distributable_profit: float
    realized_external_revenue: float
    net_new_capital: float
    synt_coverage: float | None
    synr_nav: float
    syna_nav: float
    current_week: int
    unlock_curve_1_100: tuple[float, ...]
    unlock_1w: float
    unlock_4w: float
    unlock_8w: float
    unlock_26w: float
    unlock_100w: float
    lcr_1w: float | None
    lcr_4w: float | None
    lcr_8w: float | None
    policy_mode: str
    policy_invariant_failures: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.ledger_sequence < 0 or self.current_week < 0:
            raise ValueError("sequences cannot be negative")
        if len(self.unlock_curve_1_100) != 100:
            raise ValueError("unlock curve must contain exactly 100 weekly buckets")
        finite_fields = (
            self.hard_nav,
            self.liquid_nav,
            self.economic_nav,
            self.hard_assets,
            self.external_liabilities,
            self.immediate_hard_liabilities,
            self.distributable_profit,
            self.realized_external_revenue,
            self.net_new_capital,
            self.synr_nav,
            self.syna_nav,
            self.unlock_1w,
            self.unlock_4w,
            self.unlock_8w,
            self.unlock_26w,
            self.unlock_100w,
        ) + self.unlock_curve_1_100
        if not all(isfinite(value) for value in finite_fields):
            raise ValueError("snapshot values must be finite")
        for ratio in (
            self.hard_coverage_ratio,
            self.synt_coverage,
            self.lcr_1w,
            self.lcr_4w,
            self.lcr_8w,
        ):
            if ratio is not None and not isfinite(ratio):
                raise ValueError("ratios must be finite or null")
        if self.hard_nav > self.liquid_nav + 1e-9:
            raise ValueError("HardNAV cannot exceed LiquidNAV")
        if self.liquid_nav > self.economic_nav + 1e-9:
            raise ValueError("LiquidNAV cannot exceed EconomicNAV")

    def as_dict(self) -> dict[str, object]:
        data = asdict(self)
        data["unlock_curve_1_100"] = list(self.unlock_curve_1_100)
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
        ledger: CanonicalDoubleEntryLedger,
        previous_ledger_sequence: int,
        previous_hard_nav: float,
        money: SegregatedTripleMoneyLedger,
        maturity: MaturityBook,
        policy: PolicyDecision,
        current_week: int,
        liquid_reserve: float,
        expected_inflows_1w: float = 0.0,
        expected_inflows_4w: float = 0.0,
        expected_inflows_8w: float = 0.0,
        stress_buffer_1w: float = 0.0,
        stress_buffer_4w: float = 0.0,
        stress_buffer_8w: float = 0.0,
    ) -> "FinancialSnapshotV2":
        ledger.assert_balanced()
        sheet = ledger.balance_sheet(previous_sequence=previous_ledger_sequence)
        maturity_summary = maturity.summary(current_week)
        immediate = ledger.immediate_hard_liabilities()
        hard_coverage = None if immediate <= 1e-12 else sheet.hard_assets / immediate
        synt_coverage = money.synt_coverage()
        if not isfinite(synt_coverage):
            synt_coverage = None
        return cls(
            schema_version="sinergy-financial-snapshot/v2",
            ledger_sequence=ledger.sequence,
            ledger_digest_sha256=ledger.digest_sha256,
            hard_nav=sheet.hard_nav,
            liquid_nav=sheet.liquid_nav,
            economic_nav=sheet.economic_nav,
            hard_assets=sheet.hard_assets,
            external_liabilities=sheet.liabilities_total,
            immediate_hard_liabilities=immediate,
            hard_coverage_ratio=hard_coverage,
            distributable_profit=sheet.distributable_profit(previous_hard_nav),
            realized_external_revenue=ledger.realized_external_revenue_since(previous_ledger_sequence),
            net_new_capital=ledger.net_new_capital_since(previous_ledger_sequence),
            synt_coverage=synt_coverage,
            synr_nav=money.synr_nav(),
            syna_nav=money.syna_nav(),
            current_week=current_week,
            unlock_curve_1_100=maturity_summary["unlock_curve_1_100"],
            unlock_1w=maturity_summary["unlock_1w"],
            unlock_4w=maturity_summary["unlock_4w"],
            unlock_8w=maturity_summary["unlock_8w"],
            unlock_26w=maturity_summary["unlock_26w"],
            unlock_100w=maturity_summary["unlock_100w"],
            lcr_1w=maturity.lcr(
                current_week=current_week,
                horizon_weeks=1,
                liquid_reserve=liquid_reserve,
                expected_inflows=expected_inflows_1w,
                stress_buffer=stress_buffer_1w,
            ),
            lcr_4w=maturity.lcr(
                current_week=current_week,
                horizon_weeks=4,
                liquid_reserve=liquid_reserve,
                expected_inflows=expected_inflows_4w,
                stress_buffer=stress_buffer_4w,
            ),
            lcr_8w=maturity.lcr(
                current_week=current_week,
                horizon_weeks=8,
                liquid_reserve=liquid_reserve,
                expected_inflows=expected_inflows_8w,
                stress_buffer=stress_buffer_8w,
            ),
            policy_mode=policy.mode,
            policy_invariant_failures=policy.invariant_failures,
        )
