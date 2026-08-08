import unittest

from financial_os_v4.core import MonetaryResidual, MonetaryState
from financial_os_v4.rl_env import ConstrainedMonetaryEnv


def healthy_state() -> MonetaryState:
    return MonetaryState(
        inflation=0.02,
        output_gap=0.0,
        unemployment_gap=0.0,
        velocity_gap=0.0,
        hard_nav_ratio=1.20,
        liquidity_coverage_ratio=2.20,
        nonperforming_loan_ratio=0.03,
        reserve_coverage_ratio=1.60,
        upcoming_unlock_ratio_8w=0.10,
        external_pnl_ratio=0.01,
    )


class ConstrainedMonetaryEnvTests(unittest.TestCase):
    def test_unsafe_transition_is_shielded_and_heavily_penalized(self):
        env = ConstrainedMonetaryEnv()
        transition = env.evaluate_transition(
            healthy_state(),
            MonetaryResidual(credit_cap_ratio=10, midas_cap_ratio=10),
            healthy_state(),
            unbacked_mint=1,
        )
        self.assertEqual(transition.decision.mode, "EMERGENCY")
        self.assertEqual(transition.decision.bounded.credit_cap_ratio, 0)
        self.assertEqual(transition.decision.bounded.midas_cap_ratio, 0)
        self.assertLess(transition.reward, -99)

    def test_large_rl_residual_cannot_escape_bounds(self):
        env = ConstrainedMonetaryEnv()
        transition = env.evaluate_transition(
            healthy_state(),
            MonetaryResidual(
                demurrage_rate=10,
                credit_cap_ratio=10,
                productive_qe_ratio=10,
                midas_cap_ratio=10,
            ),
            healthy_state(),
        )
        action = transition.decision.bounded
        self.assertLessEqual(action.demurrage_rate, 0.06)
        self.assertLessEqual(action.credit_cap_ratio, 0.60)
        self.assertLessEqual(action.productive_qe_ratio, 0.10)
        self.assertLessEqual(action.midas_cap_ratio, 0.15)


if __name__ == "__main__":
    unittest.main()
