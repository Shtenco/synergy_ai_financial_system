import unittest

from financial_os_v4.core import (
    AssetPosition,
    BalanceSheet,
    Constitution,
    LiabilityPosition,
    MonetaryResidual,
    MonetaryState,
    TripleMoneyLedger,
)
from financial_os_v4.simulation import base_200_participant_scenario
from financial_os_v4.snapshot import FinancialSnapshot


class BalanceSheetTests(unittest.TestCase):
    def test_internal_token_market_cap_is_not_hard_nav(self):
        sheet = BalanceSheet(
            assets=[
                AssetPosition("USDC", 1_000_000),
                AssetPosition(
                    "SYNA market cap",
                    9_000_000,
                    hard_haircut=0,
                    liquid_haircut=0,
                    economic_haircut=0.25,
                ),
            ],
            liabilities=[LiabilityPosition("SYNT", 800_000)],
        )
        self.assertEqual(sheet.hard_nav, 200_000)
        self.assertGreater(sheet.economic_nav, sheet.hard_nav)

    def test_new_capital_is_not_profit(self):
        sheet = BalanceSheet(
            assets=[AssetPosition("cash", 1_500_000)],
            liabilities=[LiabilityPosition("money liabilities", 1_000_000)],
            net_new_capital=400_000,
        )
        self.assertEqual(sheet.distributable_profit(previous_hard_nav=100_000), 0)


class TripleMoneyTests(unittest.TestCase):
    def test_synt_requires_backing_and_burns_on_redemption(self):
        ledger = TripleMoneyLedger()
        ledger.mint_synt_backed(100_000, 100_000)
        self.assertEqual(ledger.synt_coverage(), 1.0)
        self.assertEqual(ledger.redeem_synt(25_000), 25_000)
        self.assertEqual(ledger.synt_money_units, 75_000)
        self.assertEqual(ledger.hard_reserve_value, 75_000)

        with self.assertRaises(ValueError):
            ledger.mint_synt_backed(100, 99)


class PolicyTests(unittest.TestCase):
    @staticmethod
    def _healthy_state() -> MonetaryState:
        return MonetaryState(
            inflation=0.03,
            output_gap=0.01,
            unemployment_gap=0,
            velocity_gap=0,
            hard_nav_ratio=1.2,
            liquidity_coverage_ratio=2.2,
            nonperforming_loan_ratio=0.03,
            reserve_coverage_ratio=1.5,
            upcoming_unlock_ratio_8w=0.10,
            external_pnl_ratio=0.02,
        )

    def test_default_rl_residual_is_exactly_zero(self):
        decision = Constitution().decide(self._healthy_state())
        self.assertEqual(decision.rl_residual, MonetaryResidual())
        self.assertEqual(decision.bounded, decision.baseline)

    def test_rl_is_bounded(self):
        c = Constitution()
        huge_rl = MonetaryResidual(
            demurrage_rate=99,
            term_savings_reward_rate=99,
            credit_cap_ratio=99,
            productive_qe_ratio=99,
            qt_ratio=99,
            insurance_target_ratio=99,
            reserve_target_ratio=99,
            midas_cap_ratio=99,
            buyback_profit_share=99,
        )
        d = c.decide(self._healthy_state(), huge_rl)
        self.assertLessEqual(d.bounded.demurrage_rate, 0.06)
        self.assertLessEqual(d.bounded.credit_cap_ratio, 0.60)
        self.assertLessEqual(d.bounded.midas_cap_ratio, 0.15)

    def test_invariant_failure_forces_emergency(self):
        state = MonetaryState(
            inflation=0.02,
            output_gap=0,
            unemployment_gap=0,
            velocity_gap=0,
            hard_nav_ratio=0.95,
            liquidity_coverage_ratio=1.2,
            nonperforming_loan_ratio=0.04,
            reserve_coverage_ratio=1.0,
            upcoming_unlock_ratio_8w=0.2,
            external_pnl_ratio=-0.01,
        )
        d = Constitution().decide(state, unbacked_mint=1)
        self.assertEqual(d.mode, "EMERGENCY")
        self.assertEqual(d.bounded.credit_cap_ratio, 0)
        self.assertEqual(d.bounded.midas_cap_ratio, 0)
        self.assertEqual(d.bounded.buyback_profit_share, 0)
        self.assertIn("UNBACKED_MINT", d.invariant_failures)


class SnapshotTests(unittest.TestCase):
    def test_snapshot_is_deterministic_and_accounting_first(self):
        sheet = BalanceSheet(
            assets=[
                AssetPosition("USDC", 1_500_000),
                AssetPosition(
                    "performing P2P loans",
                    500_000,
                    hard_haircut=0,
                    liquid_haircut=0.50,
                    economic_haircut=0.90,
                ),
            ],
            liabilities=[LiabilityPosition("SYNT", 1_000_000)],
            net_new_capital=100_000,
        )
        ledger = TripleMoneyLedger(
            syna_equity_units=10_000,
            synr_reserve_units=10_000,
            synt_money_units=1_000_000,
            hard_reserve_value=1_500_000,
            reserve_basket_value=2_000_000,
            external_liabilities=1_000_000,
        )
        policy = Constitution().decide(PolicyTests._healthy_state())
        snapshot = FinancialSnapshot.capture(
            sequence=42,
            balance_sheet=sheet,
            ledger=ledger,
            policy=policy,
            previous_hard_nav=300_000,
        )
        self.assertEqual(snapshot.hard_nav, 500_000)
        self.assertEqual(snapshot.distributable_profit, 100_000)
        self.assertEqual(len(snapshot.digest_sha256), 64)
        self.assertEqual(snapshot.digest_sha256, snapshot.digest_sha256)


class ScenarioTests(unittest.TestCase):
    def test_200_participant_scenario_is_positive_but_not_magic(self):
        s = base_200_participant_scenario()
        self.assertAlmostEqual(s.weekly_savings, 484_615.3846153846)
        self.assertAlmostEqual(s.contributions, 48_461_538.46153846)
        self.assertGreater(s.annual_p2p_profit, 0)
        self.assertTrue(0 < s.saver_yield_on_locked < 0.20)


if __name__ == "__main__":
    unittest.main()
