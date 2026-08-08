from __future__ import annotations

from decimal import Decimal, ROUND_HALF_EVEN

D = Decimal
MONEY_QUANTUM = D("0.000001")
EPS = D("0.0000005")


def money(value: float | Decimal | str) -> Decimal:
    """Convert a non-negative monetary value to the canonical journal quantum.

    Unlike the first integrated simulator helper, this function never converts a
    negative amount to zero. Negative monetary state is an error that must be
    handled by the accounting logic instead of being silently hidden.
    """

    amount = D(str(value))
    if amount < -EPS:
        raise ValueError("money amount cannot be negative")
    if amount < 0:
        amount = D("0")
    return amount.quantize(MONEY_QUANTUM, rounding=ROUND_HALF_EVEN)


def exact_split(total: float | Decimal | str, first: float | Decimal | str) -> tuple[Decimal, Decimal]:
    """Return two journal amounts whose sum is exactly the quantized total."""

    total_q = money(total)
    first_q = min(total_q, money(first))
    second_q = total_q - first_q
    return first_q, second_q
