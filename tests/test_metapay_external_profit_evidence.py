from decimal import Decimal
import unittest

from simulation.metapay_external_profit_evidence import (
    DexExternalProfitEvidence,
    assert_external_profit_invariants,
)

D = Decimal


class DexExternalProfitEvidenceTests(unittest.TestCase):
    def test_positive_realized_delta_is_admissible_after_remaining_costs(self):
        evidence = DexExternalProfitEvidence(
            evidence_id="dex-1",
            route_id="route-1",
            settlement_asset="USDT",
            pre_external_balance=D("1000"),
            post_external_balance=D("1010"),
            external_costs_remaining=D("1"),
            flash_premium_remaining=D("0.9"),
            flash_principal_repaid=True,
            settlement_realized=True,
            independent_external_counterparty=True,
            chain_id=137,
            tx_hash="0xabc",
            block_number=123,
            provider_references=("quickswap:pool", "flash:lender"),
        )
        assert_external_profit_invariants(evidence)
        self.assertEqual(evidence.external_cash_delta, D("10"))
        self.assertEqual(evidence.candidate_external_pnl, D("8.1"))
        self.assertTrue(evidence.admissible)
        payload = evidence.to_metapay_payload()
        self.assertEqual(payload["input_amount"], "0")
        self.assertEqual(payload["settled_output"], "10")
        self.assertEqual(payload["external_costs"], "1")
        self.assertEqual(payload["flash_premium"], "0.9")

    def test_internal_mint_and_mark_do_not_change_external_cash_delta(self):
        evidence = DexExternalProfitEvidence(
            evidence_id="dex-internal",
            route_id="route-internal",
            settlement_asset="USDT",
            pre_external_balance=D("100"),
            post_external_balance=D("100"),
            settlement_realized=True,
            independent_external_counterparty=True,
            tx_hash="0xdef",
            block_number=456,
            internal_mint_quantity=D("1000000000"),
            internal_mark_delta=D("999999999"),
        )
        self.assertEqual(evidence.external_cash_delta, D("0"))
        self.assertEqual(evidence.candidate_external_pnl, D("0"))
        self.assertFalse(evidence.admissible)

    def test_missing_chain_settlement_evidence_fails_closed(self):
        evidence = DexExternalProfitEvidence(
            evidence_id="dex-missing-proof",
            route_id="route-missing-proof",
            settlement_asset="USDT",
            pre_external_balance=D("100"),
            post_external_balance=D("120"),
            settlement_realized=True,
            independent_external_counterparty=True,
        )
        with self.assertRaisesRegex(ValueError, "tx hash"):
            assert_external_profit_invariants(evidence)

    def test_flash_principal_not_repaid_is_not_admissible(self):
        evidence = DexExternalProfitEvidence(
            evidence_id="dex-flash-bad",
            route_id="route-flash-bad",
            settlement_asset="USDT",
            pre_external_balance=D("100"),
            post_external_balance=D("120"),
            settlement_realized=True,
            independent_external_counterparty=True,
            flash_principal_repaid=False,
            tx_hash="0x123",
            block_number=789,
        )
        self.assertFalse(evidence.admissible)

    def test_internal_protocol_transfer_must_be_consolidated(self):
        evidence = DexExternalProfitEvidence(
            evidence_id="dex-consolidated",
            route_id="route-tax",
            settlement_asset="USDT",
            pre_external_balance=D("1000"),
            post_external_balance=D("1007"),
            settlement_realized=True,
            independent_external_counterparty=True,
            tx_hash="0x999",
            block_number=999,
            provider_references=("executor", "treasury"),
        )
        self.assertEqual(evidence.candidate_external_pnl, D("7"))
        self.assertTrue(evidence.admissible)


if __name__ == "__main__":
    unittest.main()
