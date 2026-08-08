import unittest

from financial_os_v4.p2p import DurationFundingBook, LoanRequest


class DurationFundingBookTests(unittest.TestCase):
    def test_loan_cannot_outlive_funding(self):
        book = DurationFundingBook(max_credit_share=0.60)
        book.add_funding("saver-a", 100_000, unlock_week=20)
        request = LoanRequest(
            borrower_id="borrower-a",
            principal=10_000,
            start_week=10,
            maturity_weeks=10,
            annual_rate=0.20,
        )
        with self.assertRaises(RuntimeError):
            book.originate(request)

    def test_same_funding_is_not_double_counted(self):
        book = DurationFundingBook(max_credit_share=1.0)
        book.add_funding("saver-a", 100_000, unlock_week=100)
        first = book.originate(
            LoanRequest("b1", 70_000, start_week=1, maturity_weeks=20, annual_rate=0.20)
        )
        self.assertEqual(first.outstanding_principal, 70_000)
        with self.assertRaises(RuntimeError):
            book.originate(
                LoanRequest(
                    "b2",
                    40_000,
                    start_week=1,
                    maturity_weeks=20,
                    annual_rate=0.20,
                )
            )

    def test_interest_is_realized_only_when_paid(self):
        book = DurationFundingBook(max_credit_share=1.0)
        book.add_funding("saver-a", 100_000, unlock_week=100)
        loan = book.originate(
            LoanRequest("b1", 50_000, start_week=1, maturity_weeks=26, annual_rate=0.24)
        )
        self.assertEqual(book.realized_interest_income, 0)
        self.assertGreater(loan.request.contractual_interest, 0)
        book.repay(loan.loan_id, principal=50_000, interest=6_000)
        self.assertEqual(book.realized_interest_income, 6_000)
        self.assertEqual(book.net_realized_credit_result, 6_000)

    def test_default_impairs_new_credit_until_loss_is_covered(self):
        book = DurationFundingBook(max_credit_share=0.50)
        book.add_funding("saver-a", 100_000, unlock_week=100)
        loan = book.originate(
            LoanRequest("b1", 50_000, start_week=1, maturity_weeks=20, annual_rate=0.20)
        )
        book.write_off(loan.loan_id, 50_000)
        self.assertEqual(book.uncovered_credit_loss, 50_000)
        self.assertEqual(book.credit_cap(2), 0)

        with self.assertRaises(RuntimeError):
            book.originate(
                LoanRequest(
                    "b2",
                    1_000,
                    start_week=2,
                    maturity_weeks=10,
                    annual_rate=0.20,
                )
            )

        self.assertEqual(book.cover_credit_loss(20_000), 20_000)
        self.assertEqual(book.credit_cap(2), 20_000)
        replacement = book.originate(
            LoanRequest("b2", 20_000, start_week=2, maturity_weeks=10, annual_rate=0.20)
        )
        self.assertEqual(replacement.outstanding_principal, 20_000)


if __name__ == "__main__":
    unittest.main()
