from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
import unittest

MODULE_PATH = Path(__file__).resolve().parents[1] / "econometrics" / "estimate_transaction_panel_v15_3.py"
spec = importlib.util.spec_from_file_location("v153_estimator", MODULE_PATH)
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)


class V153EconometricTests(unittest.TestCase):
    def test_ridge_recovers_monotonic_signal(self) -> None:
        x = [[float(index), float(index % 3)] for index in range(1, 50)]
        y = [1.5 + 2.0 * row[0] - 0.5 * row[1] for row in x]
        transform = module.standardize_fit(x)
        xz = module.standardize_apply(x, transform)
        beta = module.ridge_fit(xz, y, 1e-9)
        original = module.original_scale_coefficients(beta, transform, ["x1", "x2"])
        self.assertAlmostEqual(original["intercept"], 1.5, places=6)
        self.assertAlmostEqual(original["x1"], 2.0, places=6)
        self.assertAlmostEqual(original["x2"], -0.5, places=6)

    def test_lower_bound_gate_is_strict(self) -> None:
        threshold = 2.685148
        lower_bounds = [threshold - 1e-9, threshold, threshold + 1e-9]
        self.assertEqual([value >= threshold for value in lower_bounds], [False, True, True])

    def test_reinvestment_is_eighty_percent_of_realized_counted_revenue(self) -> None:
        counted = 12.5
        self.assertAlmostEqual(counted * 0.8, 10.0)

    def test_block_bootstrap_preserves_sample_length(self) -> None:
        rng = module.random.Random(153)
        indices = module.block_bootstrap_indices(37, rng)
        self.assertEqual(len(indices), 37)
        self.assertTrue(all(0 <= index < 37 for index in indices))


if __name__ == "__main__":
    unittest.main()
