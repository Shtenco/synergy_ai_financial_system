"""SINERGY Financial OS V4/V5 research core.

The package is intentionally side-by-side with legacy DeFi experiments. It does
not import or mutate old contracts or historical simulation modules.
"""

from .accounting import (
    AccountClass,
    AccountSpec,
    CanonicalDoubleEntryLedger,
    FlowType,
    JournalEntry,
    JournalLine,
    LedgerError,
)
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
from .maturity import MaturityBook, MaturityClaim
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
from .snapshot_v2 import FinancialSnapshotV2

__all__ = [
    "AccountClass",
    "AccountSpec",
    "AssetPosition",
    "BalanceSheet",
    "CanonicalDoubleEntryLedger",
    "Constitution",
    "ConstrainedMonetaryEnv",
    "DemurrageAllocation",
    "DurationFundingBook",
    "FinancialSnapshot",
    "FinancialSnapshotV2",
    "FlowType",
    "FundingTranche",
    "GesellTransactionPolicy",
    "JournalEntry",
    "JournalLine",
    "LedgerError",
    "LegacyTripleMoneyLedger",
    "LiabilityPosition",
    "LoanPosition",
    "LoanRequest",
    "LossAllocation",
    "LossEvent",
    "LossWaterfall",
    "MaturityBook",
    "MaturityClaim",
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
