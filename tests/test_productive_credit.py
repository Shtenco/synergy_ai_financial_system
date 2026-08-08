import unittest

from financial_os_v4.productive_credit import (
    ProductiveCreditRequest,
    VerificationPolicy,
    VerifierAttestation,
)


def attestations(values):
    return tuple(
        VerifierAttestation(
            verifier_id=f"v{index}",
            measured_output_value=value,
            bond_value=20_000,
        )
        for index, value in enumerate(values, start=1)
    )


class ProductiveCreditTests(unittest.TestCase):
    def test_credit_is_capped_by_weakest_capacity(self):
        request = ProductiveCreditRequest(
            project_id="factory-a",
            requested_credit=1_000_000,
            attestations=attestations(
                [1_000_000, 1_020_000, 990_000, 1_010_000, 995_000, 1_005_000, 1_015_000]
            ),
        )
        capacity = VerificationPolicy().capacity(
            request,
            reserve_capacity=900_000,
            liquidity_capacity=700_000,
            risk_capacity=400_000,
        )
        self.assertEqual(capacity.approved_credit, 400_000)
        self.assertGreater(capacity.verified_output_value, 0)

    def test_outlier_does_not_create_fake_productive_capacity(self):
        request = ProductiveCreditRequest(
            project_id="farm-a",
            requested_credit=2_000_000,
            attestations=attestations(
                [500_000, 505_000, 495_000, 510_000, 490_000, 500_000, 50_000_000, 498_000]
            ),
        )
        capacity = VerificationPolicy().capacity(
            request,
            reserve_capacity=2_000_000,
            liquidity_capacity=2_000_000,
            risk_capacity=2_000_000,
        )
        self.assertLess(capacity.verified_output_value, 600_000)
        self.assertLess(capacity.approved_credit, 300_000)

    def test_duplicate_verifier_identity_is_rejected(self):
        duplicate = (
            VerifierAttestation("same", 100_000, 20_000),
            VerifierAttestation("same", 100_000, 20_000),
        ) + attestations([100_000] * 6)
        request = ProductiveCreditRequest("project", 100_000, duplicate)
        with self.assertRaises(ValueError):
            VerificationPolicy().verified_output_value(request)

    def test_low_bond_does_not_count_toward_quorum(self):
        low_bond = tuple(
            VerifierAttestation(f"v{i}", 100_000, 1)
            for i in range(1, 8)
        )
        request = ProductiveCreditRequest("project", 100_000, low_bond)
        with self.assertRaises(RuntimeError):
            VerificationPolicy().verified_output_value(request)


if __name__ == "__main__":
    unittest.main()
