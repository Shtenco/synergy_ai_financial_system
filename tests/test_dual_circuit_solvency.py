import unittest

from simulation.dual_circuit_solvency import Circuit, experiment


POL = 10**18


class DualCircuitSolvencyTest(unittest.TestCase):
    def test_400_percent_internal_reprice_creates_no_external_lnav(self):
        state = Circuit(wallet_pol=100 * POL).bridge_in(60 * POL)
        before = state.external_lnav
        state = state.internal_reprice(40_000)
        self.assertEqual(state.external_lnav, before)

    def test_backed_bridge_round_trip_only_loses_gas(self):
        state = Circuit(wallet_pol=100 * POL)
        state = state.bridge_in(60 * POL, gas=POL // 100)
        state = state.internal_reprice(40_000)
        state = state.bridge_out(60 * POL, gas=POL // 100)
        self.assertEqual(state.wallet_pol, 100 * POL - 2 * (POL // 100))
        self.assertEqual(state.bridge_surplus, 0)

    def test_unbacked_qe_cannot_be_redeemed(self):
        state = Circuit(wallet_pol=10 * POL).bridge_in(10 * POL).unbacked_qe(30 * POL)
        self.assertEqual(state.bridge_surplus, -30 * POL)
        with self.assertRaisesRegex(ValueError, "insolvent"):
            state.bridge_out(40 * POL)

    def test_quickswap_pump_round_trip_is_negative_before_slippage(self):
        state = Circuit(wallet_pol=100 * POL)
        result = state.quickswap_round_trip(50 * POL, gas=POL // 100)
        self.assertLess(result.external_lnav, state.external_lnav)

    def test_positive_lnav_requires_explicit_external_revenue(self):
        state = Circuit(wallet_pol=10 * POL)
        result = state.receive_external_revenue(25 * POL)
        self.assertEqual(result.external_lnav - state.external_lnav, 25 * POL)
        self.assertEqual(result.external_revenue_pol, 25 * POL)

    def test_unsafe_mechanisms_attribute_apparent_profit(self):
        result = experiment()
        # A 4x ledger mark inflates the dashboard but not realizable assets.
        self.assertGreater(
            result["marked_lnav_after_4x_reprice"],
            result["external_lnav_after_4x_reprice"],
        )
        self.assertEqual(result["external_lnav_after_4x_reprice"], 100 * POL)
        # Privileged extraction moves existing POL and creates a bridge deficit.
        self.assertEqual(result["external_lnav_after_privileged_extract"], 100 * POL)
        self.assertEqual(result["bridge_surplus_after_privileged_extract"], -240 * POL)
        # Self-pumping loses value; only buyers' 25 POL reverse part of that loss.
        self.assertLess(result["external_lnav_after_quickswap_pump"], 100 * POL)
        self.assertEqual(result["external_buyer_inflow"], 25 * POL)
        self.assertEqual(
            result["external_lnav_after_external_buyers"]
            - result["external_lnav_after_quickswap_pump"],
            25 * POL,
        )


if __name__ == "__main__":
    unittest.main()
