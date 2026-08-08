import unittest

from financial_os_v4.money import SegregatedTripleMoneyLedger


class SegregatedTripleMoneyLedgerTests(unittest.TestCase):
    def test_synt_backing_does_not_appear_in_synr_or_syna_buckets(self):
        ledger = SegregatedTripleMoneyLedger()
        ledger.mint_synt_backed(100_000, 100_000)
        self.assertEqual(ledger.synt_hard_reserve, 100_000)
        self.assertEqual(ledger.synr_reserve_value, 0)
        self.assertEqual(ledger.syna_equity_value, 0)
        self.assertEqual(ledger.consolidated_external_assets, 100_000)
        self.assertEqual(ledger.consolidated_external_liabilities, 100_000)
        self.assertEqual(ledger.consolidated_equity, 0)

    def test_three_layers_use_separate_asset_values(self):
        ledger = SegregatedTripleMoneyLedger()
        ledger.mint_synt_backed(100_000, 100_000)
        ledger.issue_synr_backed(1_000, 50_000)
        ledger.issue_syna_against_equity(1_000, 20_000)
        self.assertEqual(ledger.synt_coverage(), 1.0)
        self.assertEqual(ledger.synr_nav(), 50.0)
        self.assertEqual(ledger.syna_nav(), 20.0)
        self.assertEqual(ledger.consolidated_external_assets, 170_000)
        self.assertEqual(ledger.consolidated_external_liabilities, 100_000)
        self.assertEqual(ledger.consolidated_equity, 70_000)

    def test_synt_redemption_does_not_consume_synr_or_syna_assets(self):
        ledger = SegregatedTripleMoneyLedger()
        ledger.mint_synt_backed(100_000, 100_000)
        ledger.issue_synr_backed(1_000, 50_000)
        ledger.issue_syna_against_equity(1_000, 20_000)
        payout = ledger.redeem_synt(40_000)
        self.assertEqual(payout, 40_000)
        self.assertEqual(ledger.synt_hard_reserve, 60_000)
        self.assertEqual(ledger.synr_reserve_value, 50_000)
        self.assertEqual(ledger.syna_equity_value, 20_000)

    def test_other_liabilities_reduce_syna_residual_not_synt_backing(self):
        ledger = SegregatedTripleMoneyLedger(
            syna_equity_units=1_000,
            syna_equity_value=50_000,
            other_external_liabilities=20_000,
        )
        self.assertEqual(ledger.syna_nav(), 30.0)


if __name__ == "__main__":
    unittest.main()
