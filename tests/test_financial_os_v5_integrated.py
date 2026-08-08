import unittest

from simulation.financial_os_v5_integrated import (
    IntegratedFinancialOSSimulation,
    Scenario,
)


class IntegratedFinancialOSV5Tests(unittest.TestCase):
    def test_base_100_cycles_keeps_a_balanced_ledger(self):
        result = IntegratedFinancialOSSimulation(
            100,
            20261809,
            Scenario("base"),
        ).run()
        self.assertEqual(result["cycles"], 100)
        self.assertGreater(result["ledger_sequence"], 2)
        self.assertEqual(len(result["ledger_digest_sha256"]), 64)
        self.assertEqual(len(result["snapshot_digest_sha256"]), 64)
        self.assertGreater(result["final_economic_nav"], 0)
        self.assertGreater(result["min_hard_coverage"], 1.0)
        self.assertGreater(result["min_lcr_8w"], 1.0)
        self.assertGreaterEqual(result["qt_retirement_ratio"], 0.0)
        self.assertLessEqual(result["qt_retirement_ratio"], 1.0 + 1e-9)

    def test_oracle_outliers_are_blocked_not_capitalised(self):
        seed = 20261809
        base = IntegratedFinancialOSSimulation(
            100,
            seed,
            Scenario("base"),
        ).run()
        attacked = IntegratedFinancialOSSimulation(
            100,
            seed,
            Scenario("oracle", oracle_attack=True),
        ).run()
        self.assertGreater(attacked["oracle_blocked_value"], 0)
        self.assertLessEqual(attacked["qe_issued"], base["qe_issued"] + 1e-6)
        self.assertEqual(len(attacked["ledger_digest_sha256"]), 64)

    def test_bridge_and_midas_stress_surface_as_risk(self):
        result = IntegratedFinancialOSSimulation(
            100,
            20261809,
            Scenario(
                "stress",
                bear=True,
                mass_withdrawal=True,
                credit_stress=True,
                bridge_failure=True,
                midas_crash=True,
                insurance_catastrophe=True,
                oracle_attack=True,
                adversarial_flow=True,
            ),
        ).run()
        self.assertGreater(result["metapay_unsettled"], 0)
        self.assertGreater(result["oracle_blocked_value"], 0)
        self.assertFalse(result["midas_active"])
        self.assertIsNotNone(result["midas_killed_week"])
        self.assertGreater(result["weeks_normal"] + result["weeks_defense"] + result["weeks_emergency"] + result["weeks_growth"], 0)


if __name__ == "__main__":
    unittest.main()
