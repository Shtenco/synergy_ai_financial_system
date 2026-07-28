import unittest

from simulation.graph_arbitrage import Pool
from simulation.mev_defense import best_sandwich, sealed_batch_result


class MEVDefenseTest(unittest.TestCase):
    def test_public_route_has_extractable_sandwich_value(self):
        pool = Pool("USDT", "WETH", 3_000_000 * 10**6, 1_000 * 10**6)
        result = best_sandwich(pool, "USDT", 100_000 * 10**6)
        self.assertGreater(result["attacker_profit"], 0)

    def test_sealed_route_removes_modeled_sandwich_and_slashes_expired_bond(self):
        result = sealed_batch_result(expired_solver_bond=10**18)
        self.assertEqual(result["sandwich_profit"], 0)
        self.assertEqual(result["treasury_slash_revenue"], 10**18)


if __name__ == "__main__":
    unittest.main()
