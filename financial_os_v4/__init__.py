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
    TripleMoneyLedger as LegacyTripleMoneyLedger,
)
from .gesell import DemurrageAllocation, GesellTransactionPolicy
from .money import SegregatedTripleMoneyLedger
from .p2p import DurationFundingBook, FundingTranche, LoanPosition, LoanRequest
from .productive_credit import (
    ProductiveCapacity,
    ProductiveCreditRequest,
    VerificationPolicy,
    VerifierAttestation,
)
from .risk import LossAllocation, LossEvent, LossWaterfall
from .rl_env import ConstrainedMonetaryEnv, PolicyTransition, RewardWeights
from .snapshot import FinancialSnapshot

__all__ = [
    "AssetPosition",
    "BalanceSheet",
    "Constitution",
    "ConstrainedMonetaryEnv",
    "DemurrageAllocation",
    "DurationFundingBook",
    "FinancialSnapshot",
    "FundingTranche",
    "GesellTransactionPolicy",
    "LegacyTripleMoneyLedger",
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
    "PolicyTransition",
    "ProductiveCapacity",
    "ProductiveCreditRequest",
    "RewardWeights",
    "SegregatedTripleMoneyLedger",
    "VerificationPolicy",
    "VerifierAttestation",
]
