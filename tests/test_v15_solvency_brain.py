import importlib.util
import math
import pathlib
import unittest
import sys

MODULE = pathlib.Path(__file__).resolve().parents[1] / "simulation" / "v15" / "solvency_brain.py"
spec = importlib.util.spec_from_file_location("v15_solvency", MODULE)
m = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = m
spec.loader.exec_module(m)


class V15SolvencyTests(unittest.TestCase):
    def test_hardnav_excludes_own_synthetic(self):
        sheet = m.BalanceSheet(
            hard_assets={"USDC": m.HardAsset(100, 1, 1, 1, 1)},
            liabilities={"redeem": m.Liability(20, 1)},
            synthetics={"SYNA": m.SyntheticLedger(1_000_000, {"treasury": 1_000_000})},
        )
        self.assertEqual(sheet.hard_nav(), 80.0)

    def test_risknav_is_separate_and_conservative(self):
        sheet = m.BalanceSheet(
            hard_assets={"USDC": m.HardAsset(100, 1.0, 0.99, 0.95, 0.98)},
            liabilities={"redeem": m.Liability(20, 1.0, 1.05)},
        )
        self.assertAlmostEqual(sheet.hard_nav(), 80.0, places=12)
        self.assertAlmostEqual(sheet.risk_assets_value(), 93.1, places=12)
        self.assertAlmostEqual(sheet.risk_nav(), 72.1, places=12)

    def test_supply_neutral_gradient(self):
        ledger = m.SyntheticLedger(200, {"source_pool": 100, "destination_pool": 100})
        ledger.supply_neutral_transfer("source_pool", "destination_pool", 40)
        self.assertEqual(ledger.total_supply, 200)
        self.assertEqual(ledger.partitions["source_pool"], 60)
        self.assertEqual(ledger.partitions["destination_pool"], 140)

    def test_v13_positive_fixture_conserves(self):
        r = m.v13_two_pool_fixture(10_100.0)
        self.assertGreater(r.protocol_hardnav_delta, 0.117)
        self.assertGreater(r.gross_profit, 0)
        self.assertGreaterEqual(r.solver_reward, 0.001)
        self.assertLess(abs(r.conservation_residual), 1e-9)

    def test_aligned_market_has_no_executable_protocol_accretive_route(self):
        r = m.best_executable_v13_protocol_delta(10_000.0, steps=4000)
        self.assertIsNotNone(r)
        self.assertLess(r.protocol_hardnav_delta, 0.0)

    def test_robust_gate_rejects_nominal_but_not_robust_gain(self):
        brain = m.SolvencyBrain(m.RiskPolicy(), min_robust_gain=0.05)
        c = m.Candidate(
            "fragile", delta_hard_nav=0.10, oracle_uncertainty=0.04, system_cost=0.02,
            post_hard_nav=10, pre_coverage=1.5, post_coverage=1.5,
            pre_sts=1.5, post_sts=1.5
        )
        self.assertFalse(brain.admissible(c, m.Mode.GREEN))

    def test_hold_when_no_safe_candidate(self):
        brain = m.SolvencyBrain(m.RiskPolicy(), min_robust_gain=0.05)
        bad = [
            m.Candidate("loss", -1, 0, 0, 9, 1.5, 1.5, 1.5, 1.5),
            m.Candidate("undercovered", 1, 0, 0, 11, 1.5, 1.1, 1.5, 1.5),
        ]
        self.assertIsNone(brain.choose(bad, m.Mode.GREEN))

    def test_stress_can_force_red(self):
        sheet = m.BalanceSheet(
            hard_assets={"USDC": m.HardAsset(120, 1, 1, 1, 1)},
            liabilities={"USDx": m.Liability(100, 1)},
        )
        stress = [m.StressScenario(
            "depeg+liquidity", {"USDC": 0.92}, {"USDC": 0.90}, {"USDx": 1.05}, 1.0
        )]
        brain = m.SolvencyBrain(m.RiskPolicy())
        self.assertEqual(brain.classify(sheet, stress, m.Mode.GREEN), m.Mode.RED)

    def test_capital_flow_adjusted_pnl(self):
        self.assertEqual(m.operating_hard_pnl(100, 130, contributions=20), 10)
        self.assertEqual(m.operating_hard_pnl(100, 90, withdrawals=20), 10)

    def test_waterfall_cannot_distribute_more_than_hard_profit(self):
        out = m.revenue_waterfall(10, 4, {"reserve": 4, "holders": 4, "projects": 4})
        self.assertAlmostEqual(sum(out.values()), 6.0, places=12)

    def test_orange_rejects_risk_expansion_but_allows_unwind(self):
        brain = m.SolvencyBrain(m.RiskPolicy(), min_robust_gain=0.01)
        expand = m.Candidate(
            "expand", 1, 0, 0, 10, 1.2, 1.25, 1.2, 1.25,
            action_class=m.ActionClass.EXPAND
        )
        unwind = m.Candidate(
            "unwind", -0.005, 0, 0, 10, 1.1, 1.2, 1.1, 1.2,
            action_class=m.ActionClass.REDUCE
        )
        self.assertFalse(brain.admissible(expand, m.Mode.ORANGE))
        self.assertTrue(brain.admissible(unwind, m.Mode.ORANGE))

    def test_red_allows_only_bounded_defensive_improvement(self):
        brain = m.SolvencyBrain(m.RiskPolicy(max_defensive_nav_cost=0.02))
        hedge = m.Candidate(
            "hedge", -0.01, 0, 0, 9.99, 0.98, 1.02, 0.99, 1.04,
            action_class=m.ActionClass.REDUCE
        )
        expand = m.Candidate(
            "expand", 1.0, 0, 0, 11, 0.98, 1.2, 0.99, 1.2,
            action_class=m.ActionClass.EXPAND
        )
        self.assertTrue(brain.admissible(hedge, m.Mode.RED))
        self.assertFalse(brain.admissible(expand, m.Mode.RED))


if __name__ == "__main__":
    unittest.main()
