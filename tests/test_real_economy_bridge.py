import unittest

from financial_os_v4.real_economy_bridge import (
    FinancialOSRealEconomyOrchestrator,
    GrowthProof,
    InvestmentBankBid,
    MarketplaceObservation,
    ProductiveCapitalAuction,
    ProductiveEscrowPolicy,
    SavingsFundingState,
    TargetedEscrowAuthorization,
)


class RealEconomyBridgeTests(unittest.TestCase):
    def test_local_channel_is_not_domestic_origin(self):
        obs = MarketplaceObservation(
            period="2025",
            delivered_constant_value=100.0,
            saleable_inventory_constant_value=10.0,
            local_channel_share=0.962,
            crossborder_share=0.038,
            domestic_channel_import_content=0.35,
        )
        self.assertAlmostEqual(obs.import_origin_share, 0.3747)
        self.assertAlmostEqual(obs.domestic_origin_goods, 62.53)
        self.assertAlmostEqual(obs.import_origin_goods, 37.47)

    def test_auction_rejects_maturity_mismatch_and_unhedged_fx(self):
        auction = ProductiveCapitalAuction(max_bank_concentration=0.60)
        result = auction.clear(
            requested_private_funding=100.0,
            project_maturity_weeks=20,
            bids=(
                InvestmentBankBid("short", 100.0, 0.10, 0.01, 10, 0.1),
                InvestmentBankBid("fx", 100.0, 0.09, 0.01, 40, 0.1, "CNY", False),
                InvestmentBankBid("ok-a", 60.0, 0.11, 0.01, 40, 0.1),
                InvestmentBankBid("ok-b", 60.0, 0.12, 0.01, 45, 0.1),
            ),
        )
        self.assertTrue(result.fully_funded)
        self.assertAlmostEqual(result.allocated_private_funding, 100.0)
        self.assertEqual([x.bank_id for x in result.allocations], ["ok-a", "ok-b"])

    def test_import_goods_are_haircut_for_monetary_release(self):
        auth = TargetedEscrowAuthorization(
            project_id="import-1",
            authorized_amount=100.0,
            target_goods_increase=100.0,
            target_productive_base_increase=100.0,
            goods_weight=0.60,
            productive_base_weight=0.40,
            import_goods_haircut=0.30,
        )
        decision = ProductiveEscrowPolicy.release(
            auth,
            GrowthProof(
                domestic_goods_increase=0.0,
                import_goods_increase=100.0,
                productive_base_increase=20.0,
                verifier_quorum_ok=True,
            ),
        )
        # goods score = 0.30; base score = 0.20; release = 0.6*0.3 + 0.4*0.2 = 0.26
        self.assertAlmostEqual(decision.release_factor, 0.26)
        self.assertAlmostEqual(decision.released_amount, 26.0)

    def test_orchestrator_cannot_authorize_more_than_savings_and_private_funding(self):
        savings = SavingsFundingState(
            new_financial_savings=1_000.0,
            capture_share=0.50,
            term_eligible_share=0.50,
            bank_transform_cap=0.40,
        )
        auction = ProductiveCapitalAuction(max_bank_concentration=1.0).clear(
            requested_private_funding=500.0,
            project_maturity_weeks=10,
            bids=(InvestmentBankBid("bank", 500.0, 0.1, 0.01, 20, 0.1),),
        )
        result = FinancialOSRealEconomyOrchestrator().authorize(
            requested_targeted_authorization=500.0,
            savings_state=savings,
            auction_result=auction,
            risk_capacity=1_000.0,
            liquidity_capacity=1_000.0,
        )
        self.assertAlmostEqual(savings.maximum_new_productive_funding, 100.0)
        self.assertAlmostEqual(result.private_funding, 100.0)
        self.assertAlmostEqual(result.targeted_authorization, 100.0)


if __name__ == "__main__":
    unittest.main()
