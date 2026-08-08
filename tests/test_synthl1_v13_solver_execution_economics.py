import importlib.util
import pathlib
import unittest

MODULE = pathlib.Path(__file__).resolve().parents[1] / "simulation" / "synthl1" / "v13_solver_execution_economics.py"
spec = importlib.util.spec_from_file_location("v13_solver_execution_economics", MODULE)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


class V13SolverExecutionEconomicsTests(unittest.TestCase):
    def test_polygon_gas_cost_conversion(self):
        self.assertAlmostEqual(mod.gas_cost_usd(500_000, 100, 0.15), 0.0075, places=12)
        self.assertAlmostEqual(mod.gas_cost_usd(500_000, 300, 0.15), 0.0225, places=12)

    def test_99_percent_ceiling_is_not_executable_when_solver_floor_is_large(self):
        x = mod.adaptive_execution(
            gross_profit_usd=0.109498,
            external_lp_loss_usd=0.119014,
            gas_units=500_000,
            gas_price_gwei=300,
            native_usd=0.15,
            tax_ceiling=0.99,
            gas_safety_multiple=1.25,
            risk_premium_usd=0.001,
        )
        self.assertLess(x.executable_tax_share, 0.80)
        self.assertGreaterEqual(x.solver_reward_usd + 1e-15, x.solver_floor_usd)
        self.assertGreater(x.protocol_hardnav_gain_usd, 0.0)

    def test_low_gas_allows_high_capture(self):
        x = mod.adaptive_execution(
            gross_profit_usd=0.109498,
            external_lp_loss_usd=0.119014,
            gas_units=200_000,
            gas_price_gwei=30,
            native_usd=0.15,
        )
        self.assertGreater(x.executable_tax_share, 0.97)
        self.assertGreater(x.protocol_hardnav_gain_usd, 0.10)

    def test_conservation_identity(self):
        x = mod.adaptive_execution(
            gross_profit_usd=0.109498,
            external_lp_loss_usd=0.119014,
            gas_units=500_000,
            gas_price_gwei=100,
            native_usd=0.15,
        )
        self.assertAlmostEqual(
            x.protocol_hardnav_gain_usd + x.solver_reward_usd,
            x.external_lp_loss_usd,
            places=12,
        )


if __name__ == "__main__":
    unittest.main()
