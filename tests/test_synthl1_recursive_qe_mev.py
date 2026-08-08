import importlib.util
import pathlib
import unittest

MODULE = pathlib.Path(__file__).resolve().parents[1] / "simulation" / "synthl1" / "recursive_qe_mev.py"
spec = importlib.util.spec_from_file_location("synthl1_recursive", MODULE)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


class SynthL1RecursiveQEMEVTests(unittest.TestCase):
    def test_initial_qe_creates_large_wedge_and_tax(self):
        rows = mod.run(seed=80.0, reserve=100.0, pools_n=15, capture_share=0.99, cycles=3)
        self.assertGreater(rows[0].pre_wedge_pct, 100.0)
        self.assertGreater(rows[0].tax_usdx, 0.0)
        self.assertGreater(rows[0].searcher_reward_usdx, 0.0)

    def test_reinvestment_uses_captured_tax_not_fresh_mint(self):
        rows = mod.run(seed=80.0, reserve=100.0, pools_n=15, capture_share=0.99, cycles=4)
        self.assertAlmostEqual(rows[1].pulse_usdx, rows[0].tax_usdx, places=10)
        self.assertAlmostEqual(rows[2].pulse_usdx, rows[1].tax_usdx, places=10)

    def test_closed_recursive_loop_does_not_create_hard_nav(self):
        rows = mod.run(seed=80.0, reserve=100.0, pools_n=15, capture_share=0.99, cycles=20)
        self.assertLessEqual(rows[-1].hard_nav_delta_usd, 0.0)
        self.assertGreater(sum(x.tax_usdx for x in rows), 0.0)

    def test_external_topup_can_prevent_decay_but_is_external_value(self):
        closed = mod.run(seed=80.0, capture_share=0.99, cycles=2)
        gap = max(0.0, 80.0 - closed[0].tax_usdx)
        topped = mod.run(seed=80.0, capture_share=0.99, cycles=2, external_topup=gap)
        self.assertAlmostEqual(topped[1].pulse_usdx, 80.0, places=8)

    def test_gas_floor_stops_tiny_searcher_reward(self):
        rows = mod.run(
            seed=80.0,
            capture_share=0.99,
            cycles=30,
            searcher_gas_usdx=0.10,
            min_searcher_reward_usdx=0.01,
        )
        self.assertTrue(rows)
        self.assertLess(len(rows), 30)
        self.assertEqual(rows[-1].tax_usdx, 0.0)

    def test_external_principal_cap_is_binding(self):
        unlimited = mod.run(seed=80.0, capture_share=0.99, cycles=1)
        capped = mod.run(seed=80.0, capture_share=0.99, cycles=1, external_principal_cap_usdx=1.0)
        self.assertLessEqual(capped[0].searcher_principal_usdx, 1.0 + 1e-12)
        self.assertLess(capped[0].tax_usdx, unlimited[0].tax_usdx)


if __name__ == "__main__":
    unittest.main()
