import unittest

from financial_os_v4.investment_bank import BankUnderwritingPolicy, UnderwritingScenario


class InvestmentBankPolicyTests(unittest.TestCase):
    def test_base_case_barely_passes_before_other_costs(self):
        scenario = UnderwritingScenario(
            success_probability=0.88,
            loss_given_default=0.30,
            duration_weeks=14,
            annual_project_yield=0.16,
        )
        decision = BankUnderwritingPolicy().decide(scenario)
        self.assertTrue(decision.approved)
        self.assertAlmostEqual(decision.break_even_annual_yield, 0.1519480519, places=8)

    def test_stress_case_returns_no_action(self):
        scenario = UnderwritingScenario(
            success_probability=0.88 * 0.82,
            loss_given_default=0.30 * 1.25,
            duration_weeks=14,
            annual_project_yield=0.16,
        )
        decision = BankUnderwritingPolicy().decide(scenario)
        self.assertFalse(decision.approved)
        self.assertAlmostEqual(decision.break_even_annual_yield, 0.5373772569, places=8)
        self.assertGreater(decision.required_additional_first_loss_share, 0.07)

    def test_external_first_loss_can_be_modelled_but_not_mint(self):
        scenario = UnderwritingScenario(
            success_probability=0.88 * 0.82,
            loss_given_default=0.30 * 1.25,
            duration_weeks=14,
            annual_project_yield=0.16,
            external_first_loss_share=0.08,
        )
        self.assertTrue(BankUnderwritingPolicy().decide(scenario).approved)


if __name__ == "__main__":
    unittest.main()
