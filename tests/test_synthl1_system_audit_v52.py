import importlib.util
import pathlib
import unittest

MODULE = pathlib.Path(__file__).resolve().parents[1] / "simulation" / "synthl1" / "system_audit_v52.py"
spec = importlib.util.spec_from_file_location("synthl1_system_audit_v52", MODULE)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


class SynthL1SystemAuditV52Tests(unittest.TestCase):
    def test_large_wedge_has_large_core_inventory_cost(self):
        self.assertAlmostEqual(mod.pulse_wedge_pct(80.0, 100.0), 223.568, places=3)
        burn = mod.first_pulse_core_burn_fraction(80.0, 100.0)
        self.assertGreater(burn, 0.44)
        self.assertLess(burn, 0.45)

    def test_extreme_wedge_consumes_most_target_pool_core(self):
        burn = mod.first_pulse_core_burn_fraction(500.0, 100.0)
        self.assertGreater(burn, 0.83)
        self.assertLess(burn, 0.84)

    def test_closed_loop_hard_cnav_is_not_positive(self):
        rows = mod.run_system(
            seed=80.0,
            reserve=100.0,
            hard_assets_start_usd=5.0,
            external_hard_revenue_per_cycle_usd=0.0,
            core_nav_haircut=0.0,
        )
        self.assertTrue(rows)
        self.assertLess(rows[-1].hard_cnav_delta_usd, 0.0)

    def test_core_opportunity_cost_makes_liquid_nav_stricter(self):
        hard_only = mod.run_system(core_nav_haircut=0.0)
        liquid = mod.run_system(core_nav_haircut=0.25)
        self.assertLess(liquid[-1].liquid_economic_nav_delta_usd, hard_only[-1].hard_cnav_delta_usd)

    def test_adaptive_tax_leaves_solver_reward_floor(self):
        floor = 0.01
        rows = mod.run_system(solver_reward_floor_usdx=floor, cycles=2)
        self.assertGreaterEqual(rows[0].searcher_reward_usdx + 1e-12, floor)
        self.assertLessEqual(rows[0].protocol_tax_usdx, 0.99 * rows[0].gross_arb_profit_usdx + 1e-12)

    def test_scaled_five_dollar_target_still_needs_external_value(self):
        rows = mod.run_system(
            seed=5.0,
            reserve=6.25,
            hard_assets_start_usd=5.0,
            solver_reward_floor_usdx=0.001,
            core_nav_haircut=0.0,
        )
        needed = mod.required_external_revenue_for_target(rows, 5.0, 0.10)
        self.assertGreater(needed, 0.50)
        self.assertLess(needed, 0.60)

    def test_reference_hard_reserve_remains_above_120pct_coverage(self):
        rows = mod.run_system(
            seed=80.0,
            reserve=100.0,
            hard_assets_start_usd=5.0,
            solver_reward_floor_usdx=0.01,
        )
        self.assertGreater(rows[-1].coverage_ratio, 1.20)


if __name__ == "__main__":
    unittest.main()
