import unittest

from simulation.orderflow_revenue import Epoch, run_epochs


class OrderflowRevenueTest(unittest.TestCase):
    def test_external_solvers_create_voluntary_pol_revenue(self):
        result = run_epochs((Epoch((0.1, 0.3, 0.2), 50), Epoch((0.05, 0.08), 20)))
        self.assertAlmostEqual(result["auction_revenue_pol"], 0.38)
        self.assertEqual(result["route_profit_usdt"], 70)

    def test_pool_draining_route_is_not_counted_as_profit(self):
        result = Epoch((1.0,), external_route_profit_usdt=50, protocol_pool_loss_usdt=60).settle()
        self.assertEqual(result["route_profit_usdt"], 0)
        self.assertEqual(result["pool_loss_usdt"], 0)


if __name__ == "__main__":
    unittest.main()
