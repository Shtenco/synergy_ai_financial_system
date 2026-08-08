import importlib.util
import pathlib
import sys
import unittest

MODULE = pathlib.Path(__file__).resolve().parents[1] / "simulation" / "v15" / "recap_auction.py"
spec = importlib.util.spec_from_file_location("v15_recap_auction", MODULE)
m = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = m
spec.loader.exec_module(m)


def state():
    return m.RecapState(
        risk_assets=110,
        liabilities=100,
        target_coverage=1.30,
        contribution_risk_factor=0.95,
        existing_synr_supply=1_000,
        max_post_raise_dilution=0.10,
    )


class RecapAuctionTests(unittest.TestCase):
    def test_required_hard_capital_is_balance_sheet_derived(self):
        self.assertAlmostEqual(state().hard_capital_required, 20 / 0.95, places=12)

    def test_minimum_price_enforces_max_post_raise_dilution(self):
        s = state()
        floor = m.minimum_clearing_price_for_dilution(s)
        qmax = s.max_new_synr
        self.assertAlmostEqual(s.hard_capital_required / floor, qmax, places=10)

    def test_successful_auction_restores_target_and_is_not_operating_profit(self):
        s = state()
        bids = [m.AuctionBid(8, .50), m.AuctionBid(8, .35), m.AuctionBid(8, .25)]
        r = m.clear_uniform_price_auction(s, bids)
        self.assertTrue(r.successful)
        self.assertGreaterEqual(r.post_coverage, 1.30)
        self.assertLessEqual(r.post_raise_dilution, 0.10 + 1e-12)
        self.assertEqual(r.operating_pnl, 0.0)

    def test_insufficient_external_hard_demand_fails_instead_of_claiming_success(self):
        s = state()
        bids = [m.AuctionBid(5, .50), m.AuctionBid(5, .40)]
        r = m.clear_uniform_price_auction(s, bids)
        self.assertFalse(r.successful)
        self.assertEqual(r.reason, "insufficient-hard-demand")

    def test_low_price_demand_below_dilution_floor_is_rejected(self):
        s = state()
        floor = m.minimum_clearing_price_for_dilution(s)
        bids = [m.AuctionBid(100, floor * 0.5)]
        r = m.clear_uniform_price_auction(s, bids)
        self.assertFalse(r.successful)
        self.assertEqual(r.reason, "insufficient-hard-demand")

    def test_zero_need_issues_no_synr(self):
        s = m.RecapState(150, 100, 1.30, .95, 1000, .10)
        r = m.clear_uniform_price_auction(s, [])
        self.assertTrue(r.successful)
        self.assertEqual(r.synr_issued, 0.0)
        self.assertEqual(r.hard_capital_raised, 0.0)


if __name__ == "__main__":
    unittest.main()
