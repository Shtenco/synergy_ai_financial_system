import importlib.util
import pathlib
import unittest

MODULE = pathlib.Path(__file__).resolve().parents[1] / "simulation" / "synthl1" / "stateful_gradient_graph_v13.py"
spec = importlib.util.spec_from_file_location("synthl1_stateful_v13", MODULE)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


class SynthL1StatefulGradientGraphV13Tests(unittest.TestCase):
    def test_consistent_external_graph_has_no_standalone_marginal_cycle(self):
        multipliers = {
            "USDT": 1.000,
            "USDC": 0.995,
            "DAI": 1.005,
            "WPOL": 1.020,
            "WETH": 0.980,
        }
        external = mod.make_external(multipliers)
        self.assertLess(mod.external_cycle_upper_bound(external), 1.0)

    def test_aligned_graph_is_negative_control_but_multi_exploitable(self):
        rows, _, _, cycle_bound = mod.run_stateful({t: 1.0 for t in mod.TOKENS})
        self.assertLess(cycle_bound, 1.0)
        self.assertGreaterEqual(len(rows), 5)
        self.assertLess(rows[-1].protocol_real_delta_usd, 0.0)
        self.assertLess(abs(rows[-1].conservation_error_usd), 1e-6)

    def test_self_created_gradient_unlocks_positive_protocol_delta_in_consistent_basis_graph(self):
        multipliers = {
            "USDT": 1.000,
            "USDC": 0.995,
            "DAI": 1.005,
            "WPOL": 1.020,
            "WETH": 0.980,
        }
        rows, source, destination, cycle_bound = mod.run_stateful(multipliers)
        self.assertLess(cycle_bound, 1.0)  # no standalone external marginal arb cycle
        self.assertGreaterEqual(len(rows), 5)
        self.assertNotEqual(source, destination)
        self.assertGreater(rows[-1].protocol_real_delta_usd, 0.0)
        self.assertGreater(sum(x.protocol_tax_usd for x in rows), 0.0)
        self.assertLess(abs(rows[-1].conservation_error_usd), 1e-6)

    def test_state_is_carried_forward_not_independent_snapshots(self):
        multipliers = {
            "USDT": 1.000,
            "USDC": 0.995,
            "DAI": 1.005,
            "WPOL": 1.020,
            "WETH": 0.980,
        }
        rows, _, _, _ = mod.run_stateful(multipliers)
        self.assertGreaterEqual(len(rows), 2)
        # External LP delta and cumulative solver reward must evolve between cycles.
        self.assertNotEqual(rows[0].external_lp_delta_usd, rows[1].external_lp_delta_usd)
        self.assertGreater(rows[1].solver_cumulative_usd, rows[0].solver_cumulative_usd)


if __name__ == "__main__":
    unittest.main()
