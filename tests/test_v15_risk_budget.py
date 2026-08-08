import importlib.util
import pathlib
import sys
import unittest

MODULE = pathlib.Path(__file__).resolve().parents[1] / "simulation" / "v15" / "risk_budget.py"
spec = importlib.util.spec_from_file_location("v15_risk_budget", MODULE)
m = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = m
spec.loader.exec_module(m)


def state(nav, daily_used=1):
    return m.RiskState(
        hard_nav=nav,
        high_water_nav=100,
        solvency_loss_headroom=20,
        daily_loss_used=daily_used,
        daily_loss_limit=5,
        max_hwm_drawdown=.10,
        turnover_remaining=50,
    )


class RiskBudgetTests(unittest.TestCase):
    def test_drawdown_consumes_available_loss_budget(self):
        self.assertGreater(state(100).action_loss_budget, state(95).action_loss_budget)
        self.assertGreater(state(95).action_loss_budget, state(92).action_loss_budget)
        self.assertEqual(state(90).action_loss_budget, 0.0)

    def test_daily_loss_limit_can_be_binding(self):
        self.assertAlmostEqual(state(100, daily_used=4.5).action_loss_budget, 0.5)

    def test_turnover_limit_can_bind_notional(self):
        r = m.ActionRisk(worst_case_loss_rate=.01, hard_turnover_per_notional=2.5)
        self.assertAlmostEqual(m.max_notional(state(100), r), 20.0)  # 50 / 2.5

    def test_notional_decreases_with_drawdown_instead_of_martingaling(self):
        r = m.ActionRisk(.02, 1.0)
        n0 = m.scaled_max_notional(state(100), r, .03, .10)
        n1 = m.scaled_max_notional(state(95), r, .03, .10)
        n2 = m.scaled_max_notional(state(98), r, .03, .10)
        self.assertGreaterEqual(n0, n2)
        self.assertGreater(n2, n1)

    def test_hard_drawdown_stops_new_risk(self):
        r = m.ActionRisk(.02, 1.0)
        self.assertEqual(m.scaled_max_notional(state(90), r, .03, .10), 0.0)

    def test_expected_log_growth_is_only_secondary_rejection_filter(self):
        self.assertTrue(m.accept_expected_log_growth(100, 10, .70, .02, .01))
        self.assertFalse(m.accept_expected_log_growth(100, 10, .10, .01, .05))


if __name__ == "__main__":
    unittest.main()
