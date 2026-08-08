import unittest

from financial_os_v4.precision import exact_split, money
from simulation.financial_os_v5_1_hardened import (
    HardenedFinancialOSSimulation,
    Scenario,
)


class MoneyPrecisionTests(unittest.TestCase):
    def test_negative_money_is_not_silently_clamped(self):
        with self.assertRaises(ValueError):
            money(-1.0)

    def test_exact_split_closes_to_quantized_total(self):
        first, second = exact_split("100.000001", "33.3333334")
        self.assertEqual(first + second, money("100.000001"))


class HardenedSimulationTests(unittest.TestCase):
    def test_base_100_cycle_runner_keeps_nonnegative_balances(self):
        sim = HardenedFinancialOSSimulation(100, 20261809, Scenario("base"))
        result = sim.run()
        sim.ledger.assert_balanced()
        self.assertGreater(result["final_economic_nav"], 0)
        self.assertGreater(result["min_hard_coverage"], 1.0)
        for account in ("cash", "p2p", "productive", "savings", "synt", "escrow"):
            self.assertGreaterEqual(sim.bal(account), 0.0)

    def test_combined_stress_does_not_capitalise_oracle_outliers(self):
        sim = HardenedFinancialOSSimulation(
            100,
            20261809,
            Scenario(
                "combined",
                bear=True,
                mass_withdrawal=True,
                credit_stress=True,
                bridge_failure=True,
                midas_crash=True,
                insurance_catastrophe=True,
                oracle_attack=True,
                adversarial_flow=True,
            ),
        )
        result = sim.run()
        sim.ledger.assert_balanced()
        self.assertGreater(result["oracle_blocked_value"], 0)
        self.assertGreaterEqual(result["metapay_unsettled"], 0)
        self.assertEqual(len(result["ledger_digest_sha256"]), 64)


if __name__ == "__main__":
    unittest.main()
