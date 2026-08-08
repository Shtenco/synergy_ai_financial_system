import importlib.util
import pathlib
import unittest

MODULE = pathlib.Path(__file__).resolve().parents[1] / "simulation" / "synthl1" / "reserve_gradient_v6.py"
spec = importlib.util.spec_from_file_location("synthl1_gradient_v6", MODULE)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


class SynthL1ReserveGradientV6Tests(unittest.TestCase):
    def test_40pct_supply_neutral_gradient_has_expected_ratio(self):
        self.assertAlmostEqual(mod.gradient_price_ratio(40.0), 2.3333333333333335, places=10)

    def test_one_initiated_gradient_is_exploited_multiple_times(self):
        rows = mod.run_aligned_control(shift=40.0, cycles=50)
        self.assertGreaterEqual(len(rows), 5)
        self.assertGreater(sum(x.protocol_tax_b for x in rows), 0.0)
        self.assertGreater(sum(x.solver_reward_b for x in rows), 0.0)

    def test_each_exploitation_restores_supply_neutral_synthetic_target(self):
        # run_aligned_control raises on any source/destination restoration mismatch.
        rows = mod.run_aligned_control(shift=80.0, cycles=50)
        self.assertGreaterEqual(len(rows), 5)
        self.assertGreater(sum(x.synthetic_restored for x in rows), 0.0)

    def test_conservation_closes_each_cycle(self):
        rows = mod.run_aligned_control(shift=40.0, cycles=50)
        self.assertTrue(rows)
        self.assertLess(max(abs(x.conservation_error_b) for x in rows), 1e-7)

    def test_aligned_external_market_is_negative_consolidated_control(self):
        rows = mod.run_aligned_control(shift=40.0, cycles=50)
        self.assertTrue(rows)
        self.assertLess(rows[-1].protocol_real_delta_b, 0.0)
        self.assertGreater(rows[-1].external_lp_delta_b, 0.0)

    def test_larger_gradient_creates_larger_initial_edge_surface(self):
        self.assertGreater(mod.gradient_price_ratio(80.0), mod.gradient_price_ratio(40.0))
        self.assertAlmostEqual(mod.gradient_price_ratio(80.0), 9.0, places=10)


if __name__ == "__main__":
    unittest.main()
