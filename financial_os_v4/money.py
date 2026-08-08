from __future__ import annotations

from dataclasses import dataclass
from math import isfinite

EPS = 1e-9


def _nonnegative(value: float, name: str) -> None:
    if not isfinite(value) or value < 0:
        raise ValueError(f"{name} must be finite and non-negative")


def _positive(value: float, name: str) -> None:
    if not isfinite(value) or value <= 0:
        raise ValueError(f"{name} must be finite and positive")


@dataclass
class SegregatedTripleMoneyLedger:
    """Canonical non-overlapping asset buckets for SYNA / SYNR / SYNT.

    The same asset value is never simultaneously pledged to multiple monetary
    layers in this reference ledger.

    - SYNT is a senior transaction-money liability backed by `synt_hard_reserve`.
    - SYNR is reserve/savings capital backed by its own `synr_reserve_value`.
    - SYNA is equity/risk capital backed by its own `syna_equity_value`.

    `other_external_liabilities` are charged against the equity bucket here.
    A production legal structure may assign different seniority, but it must do
    so explicitly rather than double-counting one reserve across all tokens.
    """

    synt_money_units: float = 0.0
    synt_hard_reserve: float = 0.0
    synr_reserve_units: float = 0.0
    synr_reserve_value: float = 0.0
    syna_equity_units: float = 0.0
    syna_equity_value: float = 0.0
    other_external_liabilities: float = 0.0

    def __post_init__(self) -> None:
        for field_name in self.__dataclass_fields__:
            _nonnegative(getattr(self, field_name), field_name)

    @property
    def consolidated_external_assets(self) -> float:
        return self.synt_hard_reserve + self.synr_reserve_value + self.syna_equity_value

    @property
    def consolidated_external_liabilities(self) -> float:
        return self.synt_money_units + self.other_external_liabilities

    @property
    def consolidated_equity(self) -> float:
        return self.consolidated_external_assets - self.consolidated_external_liabilities

    def synt_coverage(self) -> float:
        if self.synt_money_units <= EPS:
            return float("inf")
        return self.synt_hard_reserve / self.synt_money_units

    def synr_nav(self) -> float:
        if self.synr_reserve_units <= EPS:
            return 0.0
        return self.synr_reserve_value / self.synr_reserve_units

    def syna_nav(self) -> float:
        if self.syna_equity_units <= EPS:
            return 0.0
        residual = max(0.0, self.syna_equity_value - self.other_external_liabilities)
        return residual / self.syna_equity_units

    def mint_synt_backed(self, amount: float, hard_backing_received: float) -> None:
        _positive(amount, "SYNT mint amount")
        _nonnegative(hard_backing_received, "hard_backing_received")
        if hard_backing_received + EPS < amount:
            raise ValueError("SYNT primary mint must be fully hard-backed at par")
        self.synt_money_units += amount
        self.synt_hard_reserve += hard_backing_received

    def redeem_synt(self, amount: float) -> float:
        _positive(amount, "SYNT redemption amount")
        if amount > self.synt_money_units + EPS:
            raise ValueError("redemption exceeds SYNT supply")
        if amount > self.synt_hard_reserve + EPS:
            raise RuntimeError("insufficient dedicated SYNT hard reserve")
        self.synt_money_units -= amount
        self.synt_hard_reserve -= amount
        return amount

    def issue_synr_backed(self, units: float, reserve_value_received: float) -> None:
        _positive(units, "SYNR units")
        _positive(reserve_value_received, "SYNR reserve value")
        self.synr_reserve_units += units
        self.synr_reserve_value += reserve_value_received

    def redeem_synr(self, units: float) -> float:
        _positive(units, "SYNR redemption units")
        if units > self.synr_reserve_units + EPS:
            raise ValueError("redemption exceeds SYNR units")
        nav = self.synr_nav()
        payout = units * nav
        if payout > self.synr_reserve_value + EPS:
            raise RuntimeError("insufficient dedicated SYNR reserve")
        self.synr_reserve_units -= units
        self.synr_reserve_value -= payout
        return payout

    def issue_syna_against_equity(self, units: float, equity_received: float) -> None:
        _positive(units, "SYNA units")
        _positive(equity_received, "SYNA equity received")
        self.syna_equity_units += units
        self.syna_equity_value += equity_received

    def add_realized_profit_to_equity(self, amount: float) -> None:
        _nonnegative(amount, "realized profit")
        self.syna_equity_value += amount

    def add_realized_profit_to_reserve(self, amount: float) -> None:
        _nonnegative(amount, "realized reserve profit")
        self.synr_reserve_value += amount
