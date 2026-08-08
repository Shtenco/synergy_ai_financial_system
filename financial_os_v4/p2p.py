from __future__ import annotations

from dataclasses import dataclass, field
from itertools import count
from math import isfinite

EPS = 1e-9


def _positive(value: float, name: str) -> None:
    if not isfinite(value) or value <= 0:
        raise ValueError(f"{name} must be finite and positive")


@dataclass
class FundingTranche:
    owner_id: str
    amount: float
    unlock_week: int
    committed: float = 0.0

    def __post_init__(self) -> None:
        _positive(self.amount, "funding amount")
        if self.unlock_week <= 0:
            raise ValueError("unlock_week must be positive")
        if self.committed < -EPS or self.committed > self.amount + EPS:
            raise ValueError("invalid committed amount")

    @property
    def available(self) -> float:
        return max(0.0, self.amount - self.committed)


@dataclass(frozen=True)
class LoanRequest:
    borrower_id: str
    principal: float
    start_week: int
    maturity_weeks: int
    annual_rate: float

    def __post_init__(self) -> None:
        _positive(self.principal, "principal")
        if self.start_week < 0:
            raise ValueError("start_week cannot be negative")
        if self.maturity_weeks <= 0:
            raise ValueError("maturity_weeks must be positive")
        if not isfinite(self.annual_rate) or self.annual_rate < 0:
            raise ValueError("annual_rate must be finite and non-negative")

    @property
    def due_week(self) -> int:
        return self.start_week + self.maturity_weeks

    @property
    def contractual_interest(self) -> float:
        return self.principal * self.annual_rate * self.maturity_weeks / 52.0


@dataclass(frozen=True)
class FundingSlice:
    tranche_index: int
    amount: float
    unlock_week: int


@dataclass
class LoanPosition:
    loan_id: int
    request: LoanRequest
    funding: tuple[FundingSlice, ...]
    outstanding_principal: float
    status: str = "ACTIVE"
    realized_interest: float = 0.0
    realized_loss: float = 0.0


@dataclass
class DurationFundingBook:
    """Reference P2P book with explicit maturity and impairment accounting.

    Funding is never double-counted. A loan may use only tranches whose unlock
    occurs strictly after the loan due week. The global credit share limits total
    outstanding principal relative to currently active savings principal.

    A written-off principal creates `uncovered_credit_loss`. Even after funding
    tranches are released, that impairment reduces new credit capacity until an
    explicit reserve/insurance/first-loss transfer covers it.
    """

    max_credit_share: float = 0.45
    tranches: list[FundingTranche] = field(default_factory=list)
    loans: dict[int, LoanPosition] = field(default_factory=dict)
    realized_interest_income: float = 0.0
    realized_credit_losses: float = 0.0
    uncovered_credit_loss: float = 0.0
    _loan_ids: count = field(default_factory=lambda: count(1), repr=False)

    def __post_init__(self) -> None:
        if not isfinite(self.max_credit_share) or not 0 <= self.max_credit_share <= 1:
            raise ValueError("max_credit_share must be finite and in [0,1]")

    def add_funding(self, owner_id: str, amount: float, unlock_week: int) -> int:
        tranche = FundingTranche(owner_id, amount, unlock_week)
        self.tranches.append(tranche)
        return len(self.tranches) - 1

    def active_savings_principal(self, week: int) -> float:
        if week < 0:
            raise ValueError("week cannot be negative")
        return sum(t.amount for t in self.tranches if t.unlock_week > week)

    def outstanding_principal(self) -> float:
        return sum(
            loan.outstanding_principal
            for loan in self.loans.values()
            if loan.status == "ACTIVE"
        )

    def credit_cap(self, week: int) -> float:
        gross_cap = self.active_savings_principal(week) * self.max_credit_share
        return max(0.0, gross_cap - self.uncovered_credit_loss)

    def lendable_capacity(self, request: LoanRequest) -> float:
        maturity_eligible = sum(
            tranche.available
            for tranche in self.tranches
            if tranche.unlock_week > request.due_week
        )
        global_headroom = max(
            0.0,
            self.credit_cap(request.start_week) - self.outstanding_principal(),
        )
        return min(maturity_eligible, global_headroom)

    def originate(self, request: LoanRequest) -> LoanPosition:
        if self.lendable_capacity(request) + EPS < request.principal:
            raise RuntimeError("insufficient maturity-matched credit capacity")

        remaining = request.principal
        slices: list[FundingSlice] = []
        eligible = sorted(
            (
                (index, tranche)
                for index, tranche in enumerate(self.tranches)
                if tranche.unlock_week > request.due_week and tranche.available > EPS
            ),
            key=lambda item: item[1].unlock_week,
            reverse=True,
        )
        for index, tranche in eligible:
            if remaining <= EPS:
                break
            amount = min(remaining, tranche.available)
            tranche.committed += amount
            slices.append(FundingSlice(index, amount, tranche.unlock_week))
            remaining -= amount

        if remaining > EPS:
            for funding_slice in slices:
                self.tranches[funding_slice.tranche_index].committed -= funding_slice.amount
            raise RuntimeError("atomic funding allocation failed")

        loan_id = next(self._loan_ids)
        position = LoanPosition(
            loan_id=loan_id,
            request=request,
            funding=tuple(slices),
            outstanding_principal=request.principal,
        )
        self.loans[loan_id] = position
        return position

    def _release_funding(self, loan: LoanPosition) -> None:
        for funding_slice in loan.funding:
            tranche = self.tranches[funding_slice.tranche_index]
            tranche.committed = max(0.0, tranche.committed - funding_slice.amount)

    def repay(self, loan_id: int, principal: float, interest: float) -> LoanPosition:
        loan = self.loans[loan_id]
        if loan.status != "ACTIVE":
            raise RuntimeError("loan is not active")
        if not isfinite(principal) or principal < 0:
            raise ValueError("principal repayment must be finite and non-negative")
        if not isfinite(interest) or interest < 0:
            raise ValueError("interest payment must be finite and non-negative")
        if principal > loan.outstanding_principal + EPS:
            raise ValueError("principal repayment exceeds outstanding principal")

        loan.outstanding_principal = max(0.0, loan.outstanding_principal - principal)
        loan.realized_interest += interest
        self.realized_interest_income += interest
        if loan.outstanding_principal <= EPS:
            loan.outstanding_principal = 0.0
            loan.status = "REPAID"
            self._release_funding(loan)
        return loan

    def write_off(self, loan_id: int, loss_principal: float) -> LoanPosition:
        loan = self.loans[loan_id]
        if loan.status != "ACTIVE":
            raise RuntimeError("loan is not active")
        if not isfinite(loss_principal) or loss_principal <= 0:
            raise ValueError("loss_principal must be finite and positive")
        if loss_principal > loan.outstanding_principal + EPS:
            raise ValueError("write-off exceeds outstanding principal")

        loan.outstanding_principal = max(0.0, loan.outstanding_principal - loss_principal)
        loan.realized_loss += loss_principal
        self.realized_credit_losses += loss_principal
        self.uncovered_credit_loss += loss_principal
        if loan.outstanding_principal <= EPS:
            loan.outstanding_principal = 0.0
            loan.status = "DEFAULTED"
            self._release_funding(loan)
        return loan

    def cover_credit_loss(self, amount: float) -> float:
        """Apply actual reserve/insurance/first-loss capital to an impairment.

        This restores lending capacity; it is not booked here as P2P interest or
        profit. Consolidated accounting decides whether the transfer is internal
        risk allocation or genuinely new external capital.
        """

        if not isfinite(amount) or amount <= 0:
            raise ValueError("coverage amount must be finite and positive")
        applied = min(amount, self.uncovered_credit_loss)
        self.uncovered_credit_loss = max(0.0, self.uncovered_credit_loss - applied)
        return applied

    @property
    def net_realized_credit_result(self) -> float:
        return self.realized_interest_income - self.realized_credit_losses
