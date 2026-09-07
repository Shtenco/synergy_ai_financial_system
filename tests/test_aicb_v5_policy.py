import unittest

from ai_centrobank.productive_v5_policy import AICBPolicyV5, EconomicSnapshotV5


class AICBV5PolicyTests(unittest.TestCase):
    def base(self, **overrides):
        data = dict(
            period_id="2026-09",
            monthly_inflation=0.004,
            target_monthly_inflation=0.004,
            inflation_tolerance=0.010,
            reserve_cover=0.45,
            min_reserve_cover=0.22,
            target_reserve_cover=0.45,
            goods_growth=0.010,
            capacity_growth=0.010,
            employment_rate=0.95,
            money_to_goods=1.00,
            target_money_to_goods=1.05,
            available_matching_capital=850.0,
            required_match_ratio=0.85,
            max_period_emission=850.0,
            physical_consistency_gap=0.0,
            supply_accounting_gap=0.0,
        )
        data.update(overrides)
        return EconomicSnapshotV5(**data)

    def test_policy_is_bounded_by_matching_capital(self):
        proposal = AICBPolicyV5.evaluate(
            self.base(available_matching_capital=85.0, required_match_ratio=0.85)
        )
        self.assertLessEqual(proposal.requested_emission, 100.0)
        self.assertFalse(proposal.blocked)

    def test_physical_gap_fails_closed(self):
        proposal = AICBPolicyV5.evaluate(self.base(physical_consistency_gap=0.01))
        self.assertEqual(proposal.requested_emission, 0.0)
        self.assertEqual(proposal.block_reason, "PHYSICAL_CONSISTENCY_GAP")

    def test_supply_accounting_gap_fails_closed(self):
        proposal = AICBPolicyV5.evaluate(self.base(supply_accounting_gap=0.1))
        self.assertEqual(proposal.requested_emission, 0.0)
        self.assertEqual(proposal.block_reason, "SUPPLY_ACCOUNTING_GAP")

    def test_inflation_and_reserve_stress_reduce_target(self):
        healthy = AICBPolicyV5.evaluate(self.base())
        stressed = AICBPolicyV5.evaluate(
            self.base(monthly_inflation=0.03, reserve_cover=0.10, money_to_goods=1.55)
        )
        self.assertLess(stressed.requested_emission, healthy.requested_emission)

    def test_policy_does_not_exceed_hard_period_cap(self):
        proposal = AICBPolicyV5.evaluate(
            self.base(available_matching_capital=10_000.0, max_period_emission=500.0)
        )
        self.assertLessEqual(proposal.requested_emission, 500.0)


if __name__ == "__main__":
    unittest.main()
