"""SINERGY Financial OS V4 reference core.

This package is intentionally side-by-side with the legacy DeFi experiments.
It does not import or mutate old contracts or simulation modules.
"""

from .core import (
    AssetPosition,
    BalanceSheet,
    Constitution,
    LiabilityPosition,
    MonetaryAction,
    MonetaryResidual,
    MonetaryState,
    PolicyBounds,
    PolicyDecision,
    TripleMoneyLedger,
)
from .gesell import DemurrageAllocation, GesellTransactionPolicy
from .p2p import DurationFundingBook, FundingTranche, LoanPosition, LoanRequest
from .productive_credit import (
    ProductiveCapacity,
    ProductiveCreditRequest,
    VerificationPolicy,
    VerifierAttestation,
)
from .risk import LossAllocation, LossEvent, LossWaterfall
from .snapshot import FinancialSnapshot

__all__ = [
    "AssetPosition",
    "BalanceSheet",
    "Constitution",
    "DemurrageAllocation",
    "DurationFundingBook",
    "FinancialSnapshot",
    "FundingTranche",
    "GesellTransactionPolicy",
    "LiabilityPosition",
    "LoanPosition",
    "LoanRequest",
    "LossAllocation",
    "LossEvent",
    "LossWaterfall",
    "MonetaryAction",
    "MonetaryResidual",
    "MonetaryState",
    "PolicyBounds",
    "PolicyDecision",
    "ProductiveCapacity",
    "ProductiveCreditRequest",
    "TripleMoneyLedger",
    "VerificationPolicy",
    "VerifierAttestation",
]
