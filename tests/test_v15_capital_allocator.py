import importlib.util
import pathlib
import sys
import unittest

MODULE = pathlib.Path(__file__).resolve().parents[1] / "simulation" / "v15" / "capital_allocator.py"
spec = importlib.util.spec_from_file_location("v15_capital_allocator", MODULE)
m = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = m
spec.loader.exec_module(m)


class CapitalAllocatorTests(unittest.TestCase):
    def test_loss_carryforward_is_recovered_before_distribution(self):
        state = m.CapitalState(200, 100, 1.30, 100, (m.StressCapitalState("s", 180, 100, 1.20),))
        a = m.allocate(25, 20, state)
        self.assertEqual(a.loss_carryforward_after, 0)
        self.assertEqual(a.profit_after_loss, 5)
        self.assertEqual(a.max_external_distribution, 5)

    def test_base_coverage_can_be_binding_distribution_cap(self):
        state = m.CapitalState(140, 100, 1.30, 100, (m.StressCapitalState("s", 200, 100, 1.20),))
        a = m.allocate(50, 0, state)
        self.assertAlmostEqual(state.base_coverage_headroom, 10)
        self.assertAlmostEqual(a.max_external_distribution, 10)
        self.assertAlmostEqual(a.retained_profit, 40)

    def test_stress_headroom_can_be_more_binding_than_base_coverage(self):
        state = m.CapitalState(180, 100, 1.30, 100, (m.StressCapitalState("s", 125, 100, 1.20),))
        a = m.allocate(50, 0, state)
        self.assertAlmostEqual(state.stress_headroom, 5)
        self.assertAlmostEqual(a.max_external_distribution, 5)

    def test_absolute_capital_floor_can_bind_even_with_infinite_ratio_headroom(self):
        state = m.CapitalState(105, 0, 1.30, 100, (m.StressCapitalState("s", 105, 0, 1.20),))
        self.assertAlmostEqual(state.distribution_headroom, 5)

    def test_negative_period_increases_loss_carryforward_and_distributes_zero(self):
        state = m.CapitalState(200, 100, 1.30, 100, (m.StressCapitalState("s", 180, 100, 1.20),))
        a = m.allocate(-7, 3, state)
        self.assertEqual(a.loss_carryforward_after, 10)
        self.assertEqual(a.max_external_distribution, 0)


if __name__ == "__main__":
    unittest.main()
