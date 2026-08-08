import unittest

from financial_os_v4.risk import LossEvent, LossWaterfall


class LossWaterfallTests(unittest.TestCase):
    def test_insured_credit_event_uses_expected_loss_then_insurance(self):
        waterfall = LossWaterfall(
            expected_loss_reserve=10_000,
            insurance_reserve=20_000,
            general_reserve=30_000,
            sponsor_first_loss=40_000,
        )
        allocation = waterfall.absorb(
            LossEvent(
                event_id="credit-default-1",
                gross_loss=50_000,
                collateral_recovery=5_000,
                expected_loss_reserve_eligible=True,
                insurance_eligible=True,
            )
        )
        self.assertEqual(allocation.expected_loss_reserve, 10_000)
        self.assertEqual(allocation.insurance, 20_000)
        self.assertEqual(allocation.general_reserve, 15_000)
        self.assertEqual(allocation.sponsor_first_loss, 0)
        self.assertEqual(allocation.saver_residual_loss, 0)
        self.assertEqual(allocation.absorbed_total, 50_000)

    def test_normal_midas_drawdown_cannot_use_insurance(self):
        waterfall = LossWaterfall(
            expected_loss_reserve=10_000,
            insurance_reserve=100_000,
            general_reserve=20_000,
            sponsor_first_loss=20_000,
        )
        allocation = waterfall.absorb(
            LossEvent(
                event_id="midas-market-dd",
                gross_loss=30_000,
                insurance_eligible=False,
                expected_loss_reserve_eligible=False,
            )
        )
        self.assertEqual(allocation.insurance, 0)
        self.assertEqual(allocation.expected_loss_reserve, 0)
        self.assertEqual(allocation.general_reserve, 20_000)
        self.assertEqual(allocation.sponsor_first_loss, 10_000)
        self.assertEqual(waterfall.insurance_reserve, 100_000)

    def test_savers_absorb_only_residual_after_all_eligible_buffers(self):
        waterfall = LossWaterfall(
            expected_loss_reserve=5_000,
            insurance_reserve=5_000,
            general_reserve=5_000,
            sponsor_first_loss=5_000,
        )
        allocation = waterfall.absorb(
            LossEvent(
                event_id="catastrophe",
                gross_loss=30_000,
                expected_loss_reserve_eligible=True,
                insurance_eligible=True,
            )
        )
        self.assertEqual(allocation.saver_residual_loss, 10_000)
        self.assertEqual(allocation.absorbed_total, 30_000)


if __name__ == "__main__":
    unittest.main()
