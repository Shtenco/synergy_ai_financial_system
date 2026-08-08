from decimal import Decimal
import unittest

from financial_os_v4.accounting import (
    AccountClass,
    AccountSpec,
    CanonicalDoubleEntryLedger,
    FlowType,
    JournalLine,
    LedgerError,
)
from financial_os_v4.core import Constitution, MonetaryState
from financial_os_v4.maturity import MaturityBook, MaturityClaim
from financial_os_v4.money import SegregatedTripleMoneyLedger
from financial_os_v4.snapshot_v2 import FinancialSnapshotV2

D = Decimal


def build_ledger() -> CanonicalDoubleEntryLedger:
    ledger = CanonicalDoubleEntryLedger("KZT")
    ledger.register_account(AccountSpec(
        "cash", "External settlement cash", AccountClass.ASSET,
        hard_haircut=1.0, liquid_haircut=1.0, economic_haircut=1.0,
    ))
    ledger.register_account(AccountSpec(
        "loan", "Performing credit asset", AccountClass.ASSET,
        hard_haircut=0.0, liquid_haircut=0.25, economic_haircut=0.80,
    ))
    ledger.register_account(AccountSpec(
        "synt", "SYNT settlement liability", AccountClass.LIABILITY,
        immediate_liability=True,
    ))
    ledger.register_account(AccountSpec("capital", "Contributed capital", AccountClass.EQUITY))
    ledger.register_account(AccountSpec("revenue", "External revenue", AccountClass.INCOME))
    ledger.register_account(AccountSpec("expense", "Operating expense", AccountClass.EXPENSE))
    return ledger


class CanonicalLedgerTests(unittest.TestCase):
    def test_trial_balance_and_profit_excludes_new_capital(self):
        ledger = build_ledger()
        ledger.post(
            reference="capital-1",
            flow_type=FlowType.EXTERNAL_CAPITAL,
            lines=(
                JournalLine("cash", debit=D("1000")),
                JournalLine("capital", credit=D("1000")),
            ),
        )
        sheet = ledger.balance_sheet(previous_sequence=0)
        self.assertEqual(sheet.hard_nav, 1000.0)
        self.assertEqual(sheet.net_new_capital, 1000.0)
        self.assertEqual(sheet.distributable_profit(0.0), 0.0)
        previous_sequence = ledger.sequence
        previous_hard_nav = sheet.hard_nav

        ledger.post(
            reference="revenue-1",
            flow_type=FlowType.EXTERNAL_REVENUE,
            lines=(
                JournalLine("cash", debit=D("100")),
                JournalLine("revenue", credit=D("100")),
            ),
        )
        next_sheet = ledger.balance_sheet(previous_sequence=previous_sequence)
        self.assertEqual(next_sheet.distributable_profit(previous_hard_nav), 100.0)
        self.assertEqual(ledger.realized_external_revenue_since(previous_sequence), 100.0)
        self.assertEqual(ledger.trial_balance()[0], ledger.trial_balance()[1])

    def test_unbalanced_entry_fails_closed(self):
        ledger = build_ledger()
        with self.assertRaises(LedgerError):
            ledger.post(
                reference="bad",
                lines=(
                    JournalLine("cash", debit=D("10")),
                    JournalLine("capital", credit=D("9")),
                ),
            )


class SnapshotV2Tests(unittest.TestCase):
    def test_snapshot_contains_ledger_digest_and_100_week_unlock_curve(self):
        ledger = build_ledger()
        ledger.post(
            reference="capital-1",
            flow_type=FlowType.EXTERNAL_CAPITAL,
            lines=(
                JournalLine("cash", debit=D("1000")),
                JournalLine("capital", credit=D("1000")),
            ),
        )
        previous_sequence = ledger.sequence
        previous_hard_nav = ledger.balance_sheet().hard_nav
        ledger.post(
            reference="synt-issue-1",
            flow_type=FlowType.LIABILITY_ISSUANCE,
            lines=(
                JournalLine("cash", debit=D("500")),
                JournalLine("synt", credit=D("500")),
            ),
        )
        ledger.post(
            reference="revenue-1",
            flow_type=FlowType.EXTERNAL_REVENUE,
            lines=(
                JournalLine("cash", debit=D("50")),
                JournalLine("revenue", credit=D("50")),
            ),
        )

        maturity = MaturityBook()
        maturity.add(MaturityClaim("saver-a", 100.0, due_week=4, source="term-savings"))
        maturity.add(MaturityClaim("saver-b", 50.0, due_week=8, source="term-savings"))
        money = SegregatedTripleMoneyLedger(
            synt_money_units=500.0,
            synt_hard_reserve=500.0,
            synr_reserve_units=100.0,
            synr_reserve_value=120.0,
            syna_equity_units=100.0,
            syna_equity_value=300.0,
        )
        state = MonetaryState(
            inflation=0.02,
            output_gap=0.0,
            unemployment_gap=0.0,
            velocity_gap=0.0,
            hard_nav_ratio=1.2,
            liquidity_coverage_ratio=2.0,
            nonperforming_loan_ratio=0.02,
            reserve_coverage_ratio=1.5,
            upcoming_unlock_ratio_8w=0.1,
            external_pnl_ratio=0.01,
        )
        policy = Constitution().decide(state)
        snapshot = FinancialSnapshotV2.capture(
            ledger=ledger,
            previous_ledger_sequence=previous_sequence,
            previous_hard_nav=previous_hard_nav,
            money=money,
            maturity=maturity,
            policy=policy,
            current_week=0,
            liquid_reserve=800.0,
            expected_inflows_4w=20.0,
            expected_inflows_8w=40.0,
        )
        self.assertEqual(snapshot.schema_version, "sinergy-financial-snapshot/v2")
        self.assertEqual(len(snapshot.unlock_curve_1_100), 100)
        self.assertEqual(snapshot.unlock_4w, 100.0)
        self.assertEqual(snapshot.unlock_8w, 150.0)
        self.assertAlmostEqual(snapshot.hard_coverage_ratio, 1550.0 / 500.0)
        self.assertEqual(snapshot.distributable_profit, 50.0)
        self.assertEqual(snapshot.realized_external_revenue, 50.0)
        self.assertEqual(len(snapshot.digest_sha256), 64)
        self.assertEqual(len(snapshot.ledger_digest_sha256), 64)


if __name__ == "__main__":
    unittest.main()
