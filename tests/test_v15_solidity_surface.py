import pathlib
import re
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
V15 = ROOT / "contracts" / "v15"


class V15SoliditySurfaceTests(unittest.TestCase):
    def test_exact_eight_overlay_contracts(self):
        files = sorted(x.name for x in V15.glob("*.sol"))
        self.assertEqual(files, sorted([
            "V15EconomicLedger.sol",
            "V15LiabilityRegistry.sol",
            "V15RiskOracle.sol",
            "V15SolvencyController.sol",
            "V15PostRouteGate.sol",
            "V15AccountingAdapter.sol",
            "V15Coordinator.sol",
            "V15RevenueRouter.sol",
        ]))

    def test_sources_have_balanced_braces_and_one_contract_each(self):
        for p in V15.glob("*.sol"):
            text = p.read_text()
            self.assertEqual(text.count("{"), text.count("}"), p.name)
            self.assertEqual(len(re.findall(r"\bcontract\s+V15\w+", text)), 1, p.name)

    def test_economic_ledger_has_no_risk_haircut(self):
        text = (V15 / "V15EconomicLedger.sol").read_text()
        self.assertNotIn("haircutBps", text)
        self.assertIn("permanentlyExcludedAsset", text)
        self.assertIn("hardNAV1e18", text)
        self.assertIn("everHardAccount", text)

    def test_risk_oracle_separates_reporter_marks_from_owner_haircut(self):
        text = (V15 / "V15RiskOracle.sol").read_text()
        self.assertRegex(text, r"function setHaircut\([^)]*\) external onlyOwner")
        self.assertRegex(text, r"function setRiskData\([^)]*\) external onlyReporter")
        self.assertIn("canonical < uint256(r.twap1e18)", text)
        self.assertIn("p < uint256(r.exit1e18)", text)

    def test_adapter_satisfies_both_frozen_v13_abis(self):
        text = (V15 / "V15AccountingAdapter.sol").read_text()
        for name in [
            "consolidatedHardNAV1e18", "isHardAccount", "isHardAsset", "markValue1e18",
            "externalCoverageBps", "isProtocolUSDxAccount", "isProtocolUSDxPoolAccount",
        ]:
            self.assertRegex(text, rf"function {name}\b")
        self.assertRegex(text, r"address public immutable protocolLiquidityOwner")
        self.assertIn("gate.assertRouteState();", text)

    def test_post_route_gate_is_fail_closed(self):
        text = (V15 / "V15PostRouteGate.sol").read_text()
        self.assertIn("if (!IV15SolvencyRouteGate(controller).routeSolvent()) revert", text)

    def test_revenue_has_single_settlement_and_loss_carryforward(self):
        text = (V15 / "V15RevenueRouter.sol").read_text()
        self.assertIn("lossCarryforward1e18", text)
        self.assertIn("periodSettled", text)
        self.assertIn("if (!periodOpen || periodSettled", text)
        self.assertIn("if (!periodOpen || !periodSettled)", text)

    def test_restore_and_close_remain_available_in_emergency(self):
        text = (V15 / "V15Coordinator.sol").read_text()
        restore = re.search(r"function restoreGradient[\s\S]*?function closeGradient", text)
        self.assertIsNotNone(restore)
        self.assertNotIn("controller.canExpand", restore.group(0))

    def test_only_revenue_router_imports_v13_library_not_v13_contract_logic(self):
        imports = {}
        for p in V15.glob("*.sol"):
            vals = re.findall(r'import\s+"([^"]+)"', p.read_text())
            imports[p.name] = vals
        self.assertEqual(imports["V15RevenueRouter.sol"], ["../synthl1/SafeTransferLib.sol"])
        for name, vals in imports.items():
            if name != "V15RevenueRouter.sol":
                self.assertEqual(vals, [], name)


if __name__ == "__main__":
    unittest.main()
