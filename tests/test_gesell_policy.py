import unittest

from financial_os_v4.gesell import GesellTransactionPolicy


class GesellPolicyTests(unittest.TestCase):
    def test_protected_everyday_balance_has_no_charge(self):
        policy = GesellTransactionPolicy(
            protected_balance=100_000,
            annual_demurrage_rate=0.052,
        )
        self.assertEqual(policy.charge(80_000, idle_weeks=52), 0)
        self.assertEqual(policy.charge(100_000, idle_weeks=52), 0)

    def test_only_excess_transaction_money_is_charged(self):
        policy = GesellTransactionPolicy(
            protected_balance=100_000,
            annual_demurrage_rate=0.052,
        )
        charge = policy.charge(200_000, idle_weeks=52)
        self.assertAlmostEqual(charge, 5_200, places=6)

    def test_zero_policy_rate_is_zero_cost(self):
        policy = GesellTransactionPolicy(
            protected_balance=0,
            annual_demurrage_rate=0,
        )
        self.assertEqual(policy.charge(1_000_000, idle_weeks=100), 0)

    def test_demurrage_waterfall_is_conservative(self):
        policy = GesellTransactionPolicy(
            annual_demurrage_rate=0.02,
            qt_share=0.40,
            insurance_share=0.30,
            reserve_share=0.30,
        )
        allocation = policy.allocate(10_000)
        self.assertEqual(allocation.qt, 4_000)
        self.assertEqual(allocation.insurance, 3_000)
        self.assertEqual(allocation.reserve, 3_000)
        self.assertEqual(allocation.allocated_total, 10_000)

    def test_rate_is_hard_bounded(self):
        with self.assertRaises(ValueError):
            GesellTransactionPolicy(annual_demurrage_rate=0.25)


if __name__ == "__main__":
    unittest.main()
