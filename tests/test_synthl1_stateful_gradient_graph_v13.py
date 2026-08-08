import importlib.util
import pathlib
import unittest

MODULE = pathlib.Path(__file__).resolve().parents[1] / "simulation" / "synthl1" / "stateful_gradient_graph_v13.py"
spec = importlib.util.spec_from_file_location("synthl1_stateful_v13", MODULE)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


class SynthL1StatefulGradientGraphV13Tests(unittest.TestCase):
    def setUp(self):
        self.aligned = {t: 1.0 for t in mod.TOKENS}
        self.latent = {
            "USDT": 1.000,
            "USDC": 0.998,
            "DAI": 1.002,
            "WPOL": 1.003,
            "WETH": 0.997,
        }

    def test_cycle_consistent_external_graph_has_no_standalone_marginal_cycle(self):
        venue = mod.price_vector(self.latent)
        external = mod.make_external(venue)
        self.assertLess(mod.external_cycle_upper_bound(external), 1.0)

    def test_aligned_mark_and_venue_vector_rejects_self_funded_hardnav_profit(self):
        rows, cycle_bound = mod.run_rotation(
            mark_multiplier=self.aligned,
            venue_multiplier=self.aligned,
            cycles=3,
            principal_steps=40,
            shifts=(10, 25, 40, 50),
        )
        self.assertLess(cycle_bound, 1.0)
        self.assertEqual(rows, [])

    def test_nonflat_market_vector_is_not_profit_when_marks_match_the_same_market(self):
        # Regression for the old V13 valuation bug: previously the external graph
        # used this non-flat vector while protocol NAV was still marked at BASE_USD.
        market = {
            "USDT": 1.000,
            "USDC": 0.995,
            "DAI": 1.005,
            "WPOL": 1.020,
            "WETH": 0.980,
        }
        rows, cycle_bound = mod.run_rotation(
            mark_multiplier=market,
            venue_multiplier=market,
            cycles=3,
            principal_steps=40,
            shifts=(10, 25, 40, 50),
        )
        self.assertLess(cycle_bound, 1.0)
        self.assertEqual(rows, [])

    def test_subthreshold_basis_has_no_profitable_route_before_gradient(self):
        marks = mod.price_vector(self.aligned)
        venue = mod.price_vector(self.latent)
        baseline = mod.best_no_gradient_route(
            mod.make_internal(marks),
            mod.make_external(venue),
            marks,
            principal_steps=60,
        )
        self.assertIsNone(baseline)

    def test_gradient_rotation_unlocks_positive_hardnav_from_subthreshold_basis(self):
        rows, cycle_bound = mod.run_rotation(
            mark_multiplier=self.aligned,
            venue_multiplier=self.latent,
            external_side_value_usd=100_000.0,
            cycles=8,
            principal_steps=60,
            shifts=(5, 10, 15, 20, 25, 30, 40, 50),
        )
        self.assertLess(cycle_bound, 1.0)
        self.assertGreaterEqual(len(rows), 3)
        self.assertGreater(rows[-1].protocol_cumulative_usd, 0.0)
        self.assertLess(rows[-1].external_cumulative_usd, 0.0)
        self.assertGreater(rows[-1].solver_cumulative_usd, 0.0)
        self.assertLess(max(abs(r.conservation_error_usd) for r in rows), 1e-6)
        self.assertTrue(all(r.protocol_increment_usd > 0.0 for r in rows))

    def test_rotation_carries_state_forward(self):
        rows, _ = mod.run_rotation(
            mark_multiplier=self.aligned,
            venue_multiplier=self.latent,
            cycles=4,
            principal_steps=50,
            shifts=(5, 15, 25, 40, 50),
        )
        self.assertGreaterEqual(len(rows), 2)
        self.assertGreater(rows[1].protocol_cumulative_usd, rows[0].protocol_cumulative_usd)
        self.assertNotEqual(rows[0].source + rows[0].destination, "")
        self.assertGreater(rows[1].solver_cumulative_usd, rows[0].solver_cumulative_usd)


if __name__ == "__main__":
    unittest.main()
