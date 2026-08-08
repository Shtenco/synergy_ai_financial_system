import importlib.util
import pathlib
import sys
import unittest

MODULE = pathlib.Path(__file__).resolve().parents[1] / "simulation" / "v15" / "model_risk.py"
spec = importlib.util.spec_from_file_location("v15_model_risk", MODULE)
m = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = m
spec.loader.exec_module(m)


class ModelRiskTests(unittest.TestCase):
    def test_selection_penalty_increases_with_search_space(self):
        p1 = m.search_space_penalty(0.01, 1)
        p2 = m.search_space_penalty(0.01, 100)
        p3 = m.search_space_penalty(0.01, 100_000)
        self.assertLess(p1, p2)
        self.assertLess(p2, p3)

    def test_zero_sigma_has_zero_selection_penalty(self):
        self.assertEqual(m.search_space_penalty(0.0, 100_000), 0.0)

    def test_empirical_buffer_is_one_sided(self):
        b = m.empirical_overstatement_buffer([-1.0, -0.1, 0.0, 0.2, 0.3], 0.8)
        self.assertGreaterEqual(b, 0.2)

    def test_small_sample_edge_is_shrunk_toward_zero(self):
        small = m.shrink_to_zero(0.10, 5, 50)
        large = m.shrink_to_zero(0.10, 500, 50)
        self.assertLess(small, large)
        self.assertLess(large, 0.10)

    def test_multiple_testing_can_reject_nominally_attractive_candidate(self):
        errors = [0.001, 0.002, 0.004, 0.003, -0.001] * 30
        one = m.build_model_risk_budget(errors, 0.004, 1)
        huge = m.build_model_risk_budget(errors, 0.004, 100_000)
        self.assertLess(one.total, huge.total)
        # Numerical sanity for this fixture:
        # one-candidate robust gain ~= 0.01986; 100k-search robust gain ~= 0.00929.
        self.assertTrue(m.accepted_after_model_risk(0.040, 0.002, 0.002, one, 0.010))
        self.assertFalse(m.accepted_after_model_risk(0.040, 0.002, 0.002, huge, 0.010))


if __name__ == "__main__":
    unittest.main()
