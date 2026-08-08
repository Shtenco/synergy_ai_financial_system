import importlib.util
import pathlib
import sys
import unittest

MODULE = pathlib.Path(__file__).resolve().parents[1] / "simulation" / "v15" / "governor_stress.py"
OPT = MODULE.parent / "robust_optimizer.py"

spec_opt = importlib.util.spec_from_file_location("robust_optimizer", OPT)
opt = importlib.util.module_from_spec(spec_opt)
sys.modules[spec_opt.name] = opt
spec_opt.loader.exec_module(opt)

spec = importlib.util.spec_from_file_location("v15_governor_stress", MODULE)
m = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = m
spec.loader.exec_module(m)


class GovernorStressTests(unittest.TestCase):
    def test_deterministic_10k_stress_has_zero_accepted_constraint_violations(self):
        s = m.run_stress(10_000, 42)
        self.assertEqual(s.generated, 10_000)
        self.assertGreater(s.accepted, 0)
        self.assertEqual(s.violations, 0)
        self.assertIn("coverage-floor", s.reasons)
        self.assertIn("sts-floor", s.reasons)
        self.assertIn("concentration-limit", s.reasons)


if __name__ == "__main__":
    unittest.main()
