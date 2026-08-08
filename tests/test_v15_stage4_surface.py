import pathlib
import re
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
V15 = ROOT / "contracts" / "v15"


class V15Stage4SurfaceTests(unittest.TestCase):
    def test_production_overlay_stays_exactly_eight_top_level_contracts(self):
        self.assertEqual(len(list(V15.glob("*.sol"))), 8)

    def test_economic_ledger_has_frozen_independent_validator_and_lower_mark(self):
        text = (V15 / "V15EconomicLedger.sol").read_text()
        for needle in [
            "validationOracle",
            "validationOracleFrozen",
            "oracleValidationReady",
            "oracleValidationCoversAllAssets",
            "canonicalPrice1e18",
            "primary < secondary ? primary : secondary",
        ]:
            self.assertIn(needle, text)
        self.assertIn("if (validationOracleFrozen) revert Frozen()", text)
        self.assertIn("validator == oracle", text)

    def test_engine_registration_requires_complete_validated_accounting(self):
        text = (V15 / "V15AccountingAdapter.sol").read_text()
        self.assertIn("ledger.oracleValidationReady()", text)
        self.assertIn("ledger.oracleValidationCoversAllAssets()", text)
        self.assertIn("ledger.hardNAV1e18();", text)
        self.assertIn("ledger.permanentlyExcludedAsset(synthetic)", text)

    def test_revenue_source_requires_contract_and_monotonic_evidence(self):
        text = (V15 / "V15RevenueRouter.sol").read_text()
        self.assertIn("source.code.length == 0", text)
        self.assertIn("cumulativeEvidenceSelector", text)
        self.assertIn("recognizedRevenueUnits", text)
        self.assertIn("_cumulativeRevenueEvidence", text)
        self.assertIn("amount > cumulative - recognized", text)
        self.assertIn("recognizedRevenueUnits[from][token] = recognized + amount", text)

    def test_raw_balance_is_not_the_revenue_proof(self):
        text = (V15 / "V15RevenueRouter.sol").read_text()
        evidence_pos = text.index("_cumulativeRevenueEvidence")
        transfer_pos = text.index("token.safeTransferFrom(from, address(this), amount)", evidence_pos)
        self.assertLess(evidence_pos, transfer_pos)

    def test_test_only_revenue_source_is_not_top_level_production_contract(self):
        mock = V15 / "test" / "MockV15RevenueSource.sol"
        self.assertTrue(mock.exists())
        self.assertFalse((V15 / "MockV15RevenueSource.sol").exists())


if __name__ == "__main__":
    unittest.main()
