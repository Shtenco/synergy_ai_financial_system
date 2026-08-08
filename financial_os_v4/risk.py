from __future__ import annotations

from dataclasses import dataclass
from math import isfinite

EPS = 1e-9


@dataclass(frozen=True)
class LossEvent:
    event_id: str
    gross_loss: float
    collateral_recovery: float = 0.0
    expected_loss_reserve_eligible: bool = False
    insurance_eligible: bool = False
    description: str = ""

    def __post_init__(self) -> None:
        if not self.event_id.strip():
            raise ValueError("event_id is required")
        if not isfinite(self.gross_loss) or self.gross_loss < 0:
            raise ValueError("gross_loss must be finite and non-negative")
        if not isfinite(self.collateral_recovery) or self.collateral_recovery < 0:
            raise ValueError("collateral_recovery must be finite and non-negative")
        if self.collateral_recovery > self.gross_loss + EPS:
            raise ValueError("collateral recovery cannot exceed gross loss")


@dataclass(frozen=True)
class LossAllocation:
    event_id: str
    gross_loss: float
    collateral_recovery: float
    expected_loss_reserve: float
    insurance: float
    general_reserve: float
    sponsor_first_loss: float
    saver_residual_loss: float

    @property
    def absorbed_total(self) -> float:
        return (
            self.collateral_recovery
            + self.expected_loss_reserve
            + self.insurance
            + self.general_reserve
            + self.sponsor_first_loss
            + self.saver_residual_loss
        )


@dataclass
class LossWaterfall:
    expected_loss_reserve: float
    insurance_reserve: float
    general_reserve: float
    sponsor_first_loss: float

    def __post_init__(self) -> None:
        for name in (
            "expected_loss_reserve",
            "insurance_reserve",
            "general_reserve",
            "sponsor_first_loss",
        ):
            value = getattr(self, name)
            if not isfinite(value) or value < 0:
                raise ValueError(f"{name} must be finite and non-negative")

    @staticmethod
    def _draw(remaining: float, balance: float) -> tuple[float, float, float]:
        used = min(remaining, balance)
        return remaining - used, balance - used, used

    def absorb(self, event: LossEvent) -> LossAllocation:
        remaining = event.gross_loss - event.collateral_recovery
        expected_used = 0.0
        insurance_used = 0.0

        if event.expected_loss_reserve_eligible and remaining > EPS:
            remaining, self.expected_loss_reserve, expected_used = self._draw(
                remaining,
                self.expected_loss_reserve,
            )

        if event.insurance_eligible and remaining > EPS:
            remaining, self.insurance_reserve, insurance_used = self._draw(
                remaining,
                self.insurance_reserve,
            )

        remaining, self.general_reserve, general_used = self._draw(
            remaining,
            self.general_reserve,
        )
        remaining, self.sponsor_first_loss, sponsor_used = self._draw(
            remaining,
            self.sponsor_first_loss,
        )
        saver_loss = max(0.0, remaining)

        allocation = LossAllocation(
            event_id=event.event_id,
            gross_loss=event.gross_loss,
            collateral_recovery=event.collateral_recovery,
            expected_loss_reserve=expected_used,
            insurance=insurance_used,
            general_reserve=general_used,
            sponsor_first_loss=sponsor_used,
            saver_residual_loss=saver_loss,
        )
        if abs(allocation.absorbed_total - event.gross_loss) > 1e-6:
            raise RuntimeError("loss waterfall conservation failure")
        return allocation
