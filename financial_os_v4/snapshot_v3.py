from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import json
from math import isfinite

from .snapshot_v2 import FinancialSnapshotV2


@dataclass(frozen=True)
class RealEconomyState:
    goods_availability_base: float
    domestic_origin_goods: float
    import_origin_goods: float
    productive_base: float
    import_dependency_ratio: float
    new_financial_savings: float
    term_eligible_savings: float
    bank_productive_funding_capacity: float
    private_bank_funding_committed: float
    targeted_authorization_outstanding: float
    import_fx_demand_rub_equivalent: float
    import_settlement_rub: float
    import_settlement_cny_rub_equivalent: float
    import_settlement_usd_eur_rub_equivalent: float
    import_settlement_other_rub_equivalent: float

    def __post_init__(self) -> None:
        for field_name in self.__dataclass_fields__:
            value = getattr(self, field_name)
            if not isfinite(value):
                raise ValueError(f"{field_name} must be finite")
            if value < 0:
                raise ValueError(f"{field_name} must be non-negative")
        if self.import_dependency_ratio > 1.0:
            raise ValueError("import_dependency_ratio must be in [0,1]")


@dataclass(frozen=True)
class FinancialSnapshotV3:
    """Financial Snapshot V2 plus reconciled real-economy observability.

    V3 does not let GMV or goods indices override the double-entry ledger. The
    financial snapshot remains the monetary source of truth; the real-economy
    block is an auditable policy/verification input for productive credit and
    conditional targeted monetary authorisations.
    """

    schema_version: str
    financial: FinancialSnapshotV2
    real_economy: RealEconomyState

    def __post_init__(self) -> None:
        if self.schema_version != "sinergy-financial-snapshot/v3":
            raise ValueError("unsupported snapshot V3 schema version")

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "financial": self.financial.as_dict(),
            "real_economy": asdict(self.real_economy),
        }

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
    def wrap(
        cls,
        *,
        financial: FinancialSnapshotV2,
        real_economy: RealEconomyState,
    ) -> "FinancialSnapshotV3":
        return cls(
            schema_version="sinergy-financial-snapshot/v3",
            financial=financial,
            real_economy=real_economy,
        )
