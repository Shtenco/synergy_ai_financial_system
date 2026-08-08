import importlib.util
import pathlib
import sys
import unittest

MODULE = pathlib.Path(__file__).resolve().parents[1] / "simulation" / "v15" / "portfolio_clusters.py"
spec = importlib.util.spec_from_file_location("v15_portfolio_clusters", MODULE)
m = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = m
spec.loader.exec_module(m)


def portfolio():
    return [
        m.AssetExposure("USDT", 25, ("stablecoin", "centralized-stable")),
        m.AssetExposure("USDC", 25, ("stablecoin", "centralized-stable")),
        m.AssetExposure("DAI", 20, ("stablecoin", "crypto-stable")),
        m.AssetExposure("WETH", 20, ("crypto", "ethereum-beta")),
        m.AssetExposure("WPOL", 10, ("crypto", "polygon-beta")),
    ]


class PortfolioClusterTests(unittest.TestCase):
    def test_single_names_can_look_diversified_while_stablecoin_cluster_is_70pct(self):
        c = m.group_concentrations(portfolio())
        self.assertAlmostEqual(c["stablecoin"], 0.70)
        self.assertLessEqual(max(a.risk_value for a in portfolio()) / m.total_risk_value(portfolio()), 0.25)

    def test_group_limit_catches_hidden_shared_risk(self):
        v = m.group_limit_violations(portfolio(), {"stablecoin": 0.60, "crypto": 0.50})
        self.assertIn("stablecoin", v)
        self.assertNotIn("crypto", v)

    def test_group_shock_applies_once_per_asset_using_largest_relevant_shock(self):
        assets = [m.AssetExposure("USDC", 100, ("stablecoin", "centralized-stable"))]
        loss = m.correlated_group_stress_loss(assets, {"stablecoin": 0.20, "centralized-stable": 0.30})
        self.assertAlmostEqual(loss, 30)

    def test_capacity_to_group_limit_is_zero_when_already_breached(self):
        cap = m.capacity_to_group_limit(portfolio(), ("stablecoin",), {"stablecoin": 0.60})
        self.assertEqual(cap, 0.0)

    def test_capacity_formula_hits_limit(self):
        assets = [
            m.AssetExposure("USDC", 30, ("stablecoin",)),
            m.AssetExposure("WETH", 70, ("crypto",)),
        ]
        cap = m.capacity_to_group_limit(assets, ("stablecoin",), {"stablecoin": 0.50})
        # (30+x)/(100+x)=0.5 -> x=40
        self.assertAlmostEqual(cap, 40.0)


if __name__ == "__main__":
    unittest.main()
