import importlib.util
import pathlib
import unittest

MODULE = pathlib.Path(__file__).resolve().parents[1] / "simulation" / "synthl1" / "economic_audit.py"
spec = importlib.util.spec_from_file_location("synthl1_audit", MODULE)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


class SynthL1EconomicAuditTests(unittest.TestCase):
    def test_80_on_100_initializer_creates_expected_wedge(self):
        self.assertAlmostEqual(mod.analytic_pulse_wedge_pct(80.0, 100.0), 223.568, places=3)

    def test_30pct_output_toll_creates_large_no_arb_band(self):
        band = (mod.no_arb_ratio(0.30) - 1.0) * 100.0
        self.assertGreater(band, 43.0)
        self.assertLess(band, 44.5)

    def test_contract_realistic_closed_loop_is_not_positive_cnav(self):
        rows = mod.run_static_recursive(seed=80.0, reserve=100.0, output_toll=0.30, cycles=30)
        self.assertTrue(rows)
        self.assertLess(rows[-1].ecosystem_cnav_delta, 0.0)
        self.assertGreater(sum(r.toll for r in rows), 0.0)

    def test_protocol_owned_pulse_pool_is_required_for_internal_qe(self):
        self.assertEqual(mod.initial_qe_external_liability(80.0, 1.0), 0.0)
        self.assertEqual(mod.initial_qe_external_liability(80.0, 0.5), 40.0)
        self.assertEqual(mod.initial_qe_external_liability(80.0, 0.0), 80.0)

    def test_external_revenue_required_to_offset_searcher_leakage(self):
        rows = mod.run_static_recursive(seed=80.0, reserve=100.0, output_toll=0.30, cycles=30)
        needed = mod.required_external_revenue_for_break_even(rows)
        self.assertGreater(needed, 10.0)
        self.assertLess(needed, 12.0)


if __name__ == "__main__":
    unittest.main()
