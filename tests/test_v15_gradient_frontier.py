import importlib.util
import pathlib
import sys
import unittest

MODULE = pathlib.Path(__file__).resolve().parents[1] / "simulation" / "v15" / "gradient_frontier.py"
spec = importlib.util.spec_from_file_location("v15_gradient_frontier", MODULE)
m = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = m
spec.loader.exec_module(m)


class GradientFrontierTests(unittest.TestCase):
    def test_small_basis_can_be_nominally_positive_but_not_robust(self):
        r = m.best_gradient(0.004)
        self.assertIsNotNone(r)
        self.assertGreater(r.protocol_hard_gain, 0.0)
        self.assertLess(r.robust_hard_gain, 0.0)

    def test_08pct_basis_prefers_small_gradient_not_max_wedge(self):
        r = m.best_gradient(0.008)
        self.assertIsNotNone(r)
        self.assertGreater(r.robust_hard_gain, 0.0)
        self.assertLessEqual(r.gradient_pct, 20.0)

    def test_optimal_gradient_rises_with_more_external_basis(self):
        r1 = m.best_gradient(0.008)
        r2 = m.best_gradient(0.010)
        r3 = m.best_gradient(0.015)
        self.assertLessEqual(r1.gradient_pct, r2.gradient_pct)
        self.assertLessEqual(r2.gradient_pct, r3.gradient_pct)

    def test_maximum_80pct_gradient_is_not_default_optimum(self):
        for basis in (0.008, 0.010, 0.015, 0.020):
            self.assertNotEqual(m.best_gradient(basis).gradient_pct, 80.0)


if __name__ == "__main__":
    unittest.main()
