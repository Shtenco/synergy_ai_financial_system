from __future__ import annotations

from dataclasses import dataclass
from math import isfinite


@dataclass(frozen=True)
class DemurrageAllocation:
    total_charge: float
    qt: float
    insurance: float
    reserve: float

    @property
    def allocated_total(self) -> float:
        return self.qt + self.insurance + self.reserve


@dataclass(frozen=True)
class GesellTransactionPolicy:
    """Reference demurrage policy for idle *transactional SYNT only*.

    This class is not a savings penalty. SYNR/term savings and SYNA capital are
    outside this policy. The protected balance allows ordinary transaction money
    to remain cost-free while a bounded carry cost can apply above that level.
    """

    protected_balance: float = 0.0
    annual_demurrage_rate: float = 0.0
    qt_share: float = 0.50
    insurance_share: float = 0.25
    reserve_share: float = 0.25

    def __post_init__(self) -> None:
        if not isfinite(self.protected_balance) or self.protected_balance < 0:
            raise ValueError("protected_balance must be finite and non-negative")
        if not isfinite(self.annual_demurrage_rate):
            raise ValueError("annual_demurrage_rate must be finite")
        if not 0 <= self.annual_demurrage_rate <= 0.10:
            raise ValueError("annual_demurrage_rate must be in [0, 10%]")
        shares = (self.qt_share, self.insurance_share, self.reserve_share)
        if not all(isfinite(share) and share >= 0 for share in shares):
            raise ValueError("demurrage shares must be finite and non-negative")
        if abs(sum(shares) - 1.0) > 1e-9:
            raise ValueError("demurrage shares must sum to 1")

    @property
    def weekly_effective_rate(self) -> float:
        if self.annual_demurrage_rate == 0:
            return 0.0
        return 1.0 - (1.0 - self.annual_demurrage_rate) ** (1.0 / 52.0)

    def charge(self, transactional_balance: float, idle_weeks: float) -> float:
        if not isfinite(transactional_balance) or transactional_balance < 0:
            raise ValueError("transactional_balance must be finite and non-negative")
        if not isfinite(idle_weeks) or idle_weeks < 0:
            raise ValueError("idle_weeks must be finite and non-negative")
        excess = max(0.0, transactional_balance - self.protected_balance)
        if excess == 0 or idle_weeks == 0 or self.annual_demurrage_rate == 0:
            return 0.0
        remaining_factor = (1.0 - self.weekly_effective_rate) ** idle_weeks
        return excess * (1.0 - remaining_factor)

    def allocate(self, total_charge: float) -> DemurrageAllocation:
        if not isfinite(total_charge) or total_charge < 0:
            raise ValueError("total_charge must be finite and non-negative")
        allocation = DemurrageAllocation(
            total_charge=total_charge,
            qt=total_charge * self.qt_share,
            insurance=total_charge * self.insurance_share,
            reserve=total_charge * self.reserve_share,
        )
        if abs(allocation.allocated_total - total_charge) > 1e-8:
            raise RuntimeError("demurrage allocation conservation failure")
        return allocation
