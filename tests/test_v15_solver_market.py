import importlib.util
import pathlib
import sys
import unittest

MODULE = pathlib.Path(__file__).resolve().parents[1] / "simulation" / "v15" / "solver_market.py"
spec = importlib.util.spec_from_file_location("v15_solver_market", MODULE)
m = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = m
spec.loader.exec_module(m)


class SolverMarketTests(unittest.TestCase):
    def test_frozen_executor_split_leaves_absolute_floor_when_it_binds(self):
        tax, reward = m.realized_tax(0.10, 0.01, 0.99)
        self.assertAlmostEqual(tax, 0.09)
        self.assertAlmostEqual(reward, 0.01)

    def test_more_competing_solvers_increases_any_participation_probability(self):
        costs = [0.005, 0.010, 0.020, 0.030]
        _, p1 = m.participation_probability(costs, 0.010, 1)
        _, p5 = m.participation_probability(costs, 0.010, 5)
        self.assertGreater(p5, p1)

    def test_headline_99pct_tax_is_not_equal_to_expected_capture_rate(self):
        costs = [0.01, 0.02, 0.03, 0.04]
        r = m.policy_result(0.10, 0.001, costs, solver_count=1, tax_ceiling=0.99)
        self.assertLess(r.any_solver_participation, 1.0)
        self.assertLess(r.effective_capture_rate, 0.99)

    def test_optimizer_can_raise_reward_floor_to_improve_expected_protocol_revenue(self):
        costs = [0.004, 0.006, 0.008, 0.010, 0.020]
        best = m.optimize_reward_floor(0.10, costs, solver_count=2)
        zero_floor = m.policy_result(0.10, 0.0, costs, solver_count=2)
        self.assertGreaterEqual(best.expected_protocol_capture, zero_floor.expected_protocol_capture)
        self.assertGreater(best.solver_reward, 0.001 - 1e-12)

    def test_no_capture_when_required_reward_consumes_entire_edge(self):
        r = m.policy_result(0.01, 0.02, [0.001, 0.002], solver_count=3)
        self.assertEqual(r.protocol_capture_if_executed, 0.0)
        self.assertEqual(r.expected_protocol_capture, 0.0)


if __name__ == "__main__":
    unittest.main()
