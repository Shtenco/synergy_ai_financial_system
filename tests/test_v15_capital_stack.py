import importlib.util
import pathlib
import sys
import unittest

MODULE = pathlib.Path(__file__).resolve().parents[1] / "simulation" / "v15" / "capital_stack.py"
spec = importlib.util.spec_from_file_location("v15_capital_stack", MODULE)
m = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = m
spec.loader.exec_module(m)


class CapitalStackTests(unittest.TestCase):
    def test_internal_synr_mint_without_hard_inflow_does_not_improve_hard_nav_or_coverage(self):
        s = m.BalanceSheet(120, 110, 100)
        post = m.issue_internal_token_without_hard_inflow(s, 1_000_000)
        self.assertEqual(post, s)
        self.assertEqual(post.hard_nav, s.hard_nav)
        self.assertEqual(post.coverage, s.coverage)

    def test_actual_hard_capital_raise_improves_coverage_but_is_not_operating_profit(self):
        s = m.BalanceSheet(120, 110, 100)
        post, pnl = m.junior_capital_raise(s, 30, 0.95)
        self.assertGreater(post.coverage, s.coverage)
        self.assertEqual(pnl, 0.0)

    def test_hard_redemption_promise_reduces_recapitalization_quality(self):
        s = m.BalanceSheet(120, 110, 100)
        equity_like, _ = m.junior_capital_raise(s, 30, 0.95, 0)
        redeemable, _ = m.junior_capital_raise(s, 30, 0.95, 30)
        self.assertGreater(equity_like.hard_nav, redeemable.hard_nav)
        self.assertGreater(equity_like.coverage, redeemable.coverage)

    def test_recapitalization_need_hits_target_coverage(self):
        s = m.BalanceSheet(120, 110, 100)
        need = m.required_canonical_recapitalization(110, 100, 1.30, 0.95)
        post, _ = m.junior_capital_raise(s, need, 0.95)
        self.assertAlmostEqual(post.coverage, 1.30, places=12)

    def test_external_buyback_or_distribution_reduces_hard_nav(self):
        s = m.BalanceSheet(150, 140, 100)
        post = m.hard_surplus_distribution(s, 10, 1.0)
        self.assertEqual(post.hard_nav, s.hard_nav - 10)
        self.assertLess(post.coverage, s.coverage)

    def test_permanent_redeemable_usdx_is_a_liability(self):
        s = m.BalanceSheet(100, 100, 50)
        post = m.issue_redeemable_usdx_against_hard_deposit(s, 20, 1.0, 20)
        self.assertEqual(post.hard_nav, s.hard_nav)
        self.assertEqual(post.coverage, s.coverage)


if __name__ == "__main__":
    unittest.main()
