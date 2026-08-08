from decimal import Decimal
import unittest

from financial_os_v4.accounting import (
    AccountClass,
    AccountSpec,
    CanonicalDoubleEntryLedger,
    FlowType,
    JournalLine,
)

D = Decimal


class ExternalRevenueAccountingTests(unittest.TestCase):
    def test_metapay_fee_paid_in_synt_is_external_value(self):
        ledger = CanonicalDoubleEntryLedger("KZT")
        ledger.register_account(AccountSpec(
            "cash", "Cash", AccountClass.ASSET,
            hard_haircut=1.0, liquid_haircut=1.0, economic_haircut=1.0,
        ))
        ledger.register_account(AccountSpec(
            "synt", "SYNT liability", AccountClass.LIABILITY,
            immediate_liability=True,
        ))
        ledger.register_account(AccountSpec("revenue", "Revenue", AccountClass.INCOME))
        ledger.post(
            reference="issue",
            flow_type=FlowType.LIABILITY_ISSUANCE,
            lines=(
                JournalLine("cash", debit=D("1000")),
                JournalLine("synt", credit=D("1000")),
            ),
        )
        start = ledger.sequence
        ledger.post(
            reference="fee",
            flow_type=FlowType.EXTERNAL_REVENUE,
            lines=(
                JournalLine("synt", debit=D("10")),
                JournalLine("revenue", credit=D("10")),
            ),
        )
        self.assertEqual(ledger.realized_external_revenue_since(start), 10.0)
        self.assertEqual(ledger.immediate_hard_liabilities(), 990.0)
        ledger.assert_balanced()

    def test_internal_income_reclassification_is_not_external_revenue(self):
        ledger = CanonicalDoubleEntryLedger("KZT")
        ledger.register_account(AccountSpec(
            "internal_asset", "Internal mark", AccountClass.ASSET,
            hard_haircut=0.0, liquid_haircut=0.0, economic_haircut=0.0,
            external=False,
        ))
        ledger.register_account(AccountSpec("revenue", "Revenue", AccountClass.INCOME))
        ledger.post(
            reference="internal-mark",
            flow_type=FlowType.EXTERNAL_REVENUE,
            lines=(
                JournalLine("internal_asset", debit=D("500")),
                JournalLine("revenue", credit=D("500")),
            ),
        )
        self.assertEqual(ledger.realized_external_revenue_since(0), 0.0)
        self.assertEqual(ledger.balance_sheet().hard_assets, 0.0)


if __name__ == "__main__":
    unittest.main()
