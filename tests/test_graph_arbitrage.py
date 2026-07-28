import unittest

from simulation.graph_arbitrage import (
    Pool, MarketGraph, polygon_contour, qe_external_cost, run_no_burn_experiment,
)


M = 10**6
SIZES = (10*M, 50*M, 100*M, 500*M, 1_000*M)


class GraphArbitrageTest(unittest.TestCase):
    def test_connected_contour_never_executes_nonpositive_route(self):
        graph = polygon_contour()
        opportunity = graph.best_usdt_cycle(SIZES)
        if opportunity is not None:
            self.assertGreater(opportunity.profit, 0)

    def test_no_burn_contour_realizes_profit_then_stops(self):
        result = run_no_burn_experiment()
        self.assertEqual(result["transfer_burn_bps"], 0)
        self.assertGreater(result["executions"], 0)
        self.assertGreater(result["cumulative_profit_usdt"], 0)
        self.assertLess(result["executions"], 100)
        self.assertGreaterEqual(result["token_count"], 12)

    def test_external_mispricing_produces_realized_usdt_growth(self):
        graph = MarketGraph([
            Pool("WPOL", "USDT", 1_000_000*M, 400_000*M),
            Pool("SYNA", "WPOL", 1_000_000*M, 10_000*M),
            Pool("SYNA", "USDT", 1_000_000*M, 20_000*M),
        ])
        lnav = 0
        executions = 0
        for _ in range(20):
            opportunity = graph.best_usdt_cycle(SIZES)
            if opportunity is None:
                break
            previous_lnav = lnav
            graph, output = graph.execute(opportunity.route, opportunity.amount_in)
            lnav += output - opportunity.amount_in - opportunity.flash_fee
            self.assertGreater(lnav, previous_lnav)
            executions += 1
        self.assertGreater(executions, 0)

    def test_40_percent_transfer_burn_blocks_false_triangle_profit(self):
        taxed = polygon_contour(4_000, 4_000).best_usdt_cycle(SIZES)
        untaxed = polygon_contour().best_usdt_cycle(SIZES)
        taxed_profit = 0 if taxed is None else taxed.profit
        untaxed_profit = 0 if untaxed is None else untaxed.profit
        self.assertLessEqual(taxed_profit, untaxed_profit)

    def test_qe_does_not_book_minted_token_as_external_lnav(self):
        self.assertEqual(qe_external_cost("SYNA", 1_000_000*M, 10_000*M), 10_000*M)
        self.assertEqual(qe_external_cost("SYNR", 1_000_000*M, 0), 0)
        self.assertEqual(qe_external_cost("USDT", 10_000*M, 0), 10_000*M)


if __name__ == "__main__":
    unittest.main()
