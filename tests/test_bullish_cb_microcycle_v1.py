from __future__ import annotations

import unittest

from simulation.bullish_cb_microcycle_v1 import Config, Experiment, Pool


class BullishCbMicrocycleTests(unittest.TestCase):
    def test_exact_150_block_schedule(self):
        result = Experiment(Config(cycles=15, gas_usdt_per_cycle=0.004)).run()
        self.assertEqual(result["completed_cycles"], 15)
        self.assertEqual(result["covered_blocks"], 150)
        self.assertEqual(result["trades"], 105)

    def test_hard_nav_loses_only_external_gas(self):
        result = Experiment(Config(cycles=15, gas_usdt_per_cycle=0.004)).run()
        self.assertAlmostEqual(result["hard_nav_change_usdt"], -0.06, places=12)
        self.assertEqual(result["organic_external_tvl_change_usdt"], 0.0)
        self.assertEqual(result["strict_verdict"], "FAIL_NO_EXTERNAL_VALUE")

    def test_bullish_mark_can_rise_while_hard_nav_does_not(self):
        result = Experiment(Config(cycles=15, gas_usdt_per_cycle=0.0)).run()
        self.assertGreater(result["price_multiple"], 1.0)
        self.assertGreater(result["gross_tvl_change_usdt"], 0.0)
        self.assertAlmostEqual(result["hard_nav_change_usdt"], 0.0, places=12)
        self.assertGreater(result["spot_nav_change_usdt"], 0.0)

    def test_burns_exceed_mints(self):
        result = Experiment(Config(cycles=15)).run()
        self.assertLess(result["supply_change_pct"], 0.0)
        self.assertGreater(result["burned"], result["minted"])

    def test_zero_price_rejected(self):
        with self.assertRaises(RuntimeError):
            _ = Pool(0.0, 1.0, 0.003).price


if __name__ == "__main__":
    unittest.main()
