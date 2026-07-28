import unittest

from simulation.amm_growth_cycle import State, amount_out, cycle


class ExactV2ModelTest(unittest.TestCase):
    def test_known_uniswap_v2_output(self):
        self.assertEqual(amount_out(1_000, 100_000, 200_000), 1_974)

    def test_cycle_is_solvent_but_eventually_exhausts_lp_and_creates_no_external_value(self):
        state = State(1_000_000_000, 1_000_000_000, 1_000_000, 500_000)
        initial_external_lnav = state.reserve_lnav_quote()
        executed = 0
        for _ in range(100):
            previous_product = state.base_reserve * state.quote_reserve
            previous_supply = state.lp_supply
            try:
                state = cycle(state)
            except ValueError as error:
                self.assertIn("exhausted", str(error))
                break
            executed += 1
            self.assertGreater(state.base_reserve, 0)
            self.assertGreater(state.quote_reserve, 0)
            # Compare k per LP squared: removal legitimately reduces raw k.
            self.assertGreaterEqual(
                state.base_reserve * state.quote_reserve * previous_supply**2,
                previous_product * state.lp_supply**2,
            )
        self.assertEqual(state.reserve_lnav_quote(), initial_external_lnav)
        self.assertGreater(state.dead_lp, 0)
        self.assertLess(executed, 100)


if __name__ == "__main__":
    unittest.main()
