import importlib.util
import pathlib
import unittest

MODULE = pathlib.Path(__file__).resolve().parents[1] / "simulation" / "synthl1" / "v13_10x50_stress.py"
spec = importlib.util.spec_from_file_location("synthl1_v13_10x50", MODULE)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


class SynthL1V1310x50StressTests(unittest.TestCase):
    def test_default_basis_is_below_three_leg_fee_hurdle(self):
        self.assertGreater(mod.three_leg_break_even_basis_pct(), 0.90)
        self.assertLess(0.80, mod.three_leg_break_even_basis_pct())

    def test_external_50_pool_graph_has_no_profitable_marginal_crossvenue_roundtrip(self):
        self.assertLess(mod.max_external_crossvenue_roundtrip(mod.default_layers()), 1.0)

    def test_stateful_rotation_is_protocol_hardnav_positive(self):
        rows = mod.run(principal_steps=40, max_cycles=25)
        self.assertGreaterEqual(len(rows), 10)
        self.assertGreater(rows[-1].protocol_cumulative_usd, 0.70)
        self.assertGreater(rows[-1].solver_cumulative_usd, 0.0)
        self.assertTrue(all(r.protocol_increment_usd > 0.0 for r in rows))
        self.assertLess(max(abs(r.conservation_error_usd) for r in rows), 1e-9)

    def test_grid_refinement_does_not_destroy_positive_result(self):
        coarse = mod.run(principal_steps=40, max_cycles=25)
        refined = mod.run(principal_steps=60, max_cycles=25)
        self.assertGreater(coarse[-1].protocol_cumulative_usd, 0.70)
        self.assertGreater(refined[-1].protocol_cumulative_usd, 0.70)
        # We do not require monotonic convergence, only that the result remains
        # economically material rather than disappearing under a denser grid.
        self.assertLess(
            abs(refined[-1].protocol_cumulative_usd - coarse[-1].protocol_cumulative_usd),
            0.10,
        )


if __name__ == "__main__":
    unittest.main()
