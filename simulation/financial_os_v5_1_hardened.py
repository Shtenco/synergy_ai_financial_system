from __future__ import annotations

from financial_os_v4.accounting import FlowType, JournalLine
from financial_os_v4.precision import exact_split, money
from financial_os_v4.productive_credit import (
    ProductiveCreditRequest,
    VerifierAttestation,
)
from simulation.financial_os_v5_integrated import (
    EPS,
    Funding,
    IntegratedFinancialOSSimulation,
    P2PLoan,
    ProductiveLoan,
    Scenario,
)


class HardenedFinancialOSSimulation(IntegratedFinancialOSSimulation):
    """Precision-hardened successor to the first integrated V5 harness.

    V5 remains untouched as research history. V5.1 makes the monetary quantum
    explicit and stores originated principal at the exact journal precision so a
    recovery plus write-off always closes the corresponding asset to zero.
    """

    def _assert_nonnegative_state(self) -> None:
        for account in ("cash", "p2p", "productive", "savings", "synt", "escrow"):
            if self.bal(account) < -1e-9:
                raise RuntimeError(f"negative canonical ledger balance: {account}")
        for funding in self.funding:
            if funding.amount < -1e-9 or funding.committed < -1e-9:
                raise RuntimeError("negative funding state")
            if funding.committed > funding.amount + 1e-6:
                raise RuntimeError("funding over-commitment")

    def _p2p_originate(self, cap: float) -> None:
        savings = self.bal("savings")
        headroom = max(0.0, savings * min(cap, self.cfg.p2p_cap) - self.bal("p2p"))
        cash_headroom = max(0.0, self.bal("cash") - 1.15 * self._immediate_due())
        requested = min(
            headroom,
            cash_headroom,
            savings * self.rng.uniform(0.01, 0.035),
        )
        if requested < 10_000:
            return

        maturity_weeks = self.rng.randint(4, 20)
        due = self.week + maturity_weeks
        eligible = sorted(
            (
                funding
                for funding in self.funding
                if funding.due_week > due and funding.available > EPS
            ),
            key=lambda item: item.due_week,
            reverse=True,
        )
        left = requested
        used: list[tuple[str, float]] = []
        for funding in eligible:
            take = min(left, funding.available)
            funding.committed += take
            used.append((funding.claim_id, take))
            left -= take
            if left <= EPS:
                break

        principal = float(money(requested - left))
        if principal < 10_000:
            for claim_id, amount in used:
                for funding in self.funding:
                    if funding.claim_id == claim_id:
                        funding.committed -= amount
            return

        # Align the funding commitment exactly with the posted principal.
        excess = (requested - left) - principal
        if excess > EPS and used:
            claim_id, amount = used[-1]
            release = min(excess, amount)
            used[-1] = (claim_id, amount - release)
            for funding in self.funding:
                if funding.claim_id == claim_id:
                    funding.committed -= release
                    break

        principal_d = money(principal)
        self.ledger.post(
            reference=f"p2p-orig-v51-{self.next_id}",
            flow_type=FlowType.CREDIT_ORIGINATION,
            lines=(
                JournalLine("p2p", debit=principal_d),
                JournalLine("cash", credit=principal_d),
            ),
        )
        self.p2p.append(
            P2PLoan(
                self.next_id,
                principal,
                self.week,
                due,
                self.rng.uniform(0.12, 0.24),
                [(claim_id, amount) for claim_id, amount in used if amount > EPS],
            )
        )
        self.next_id += 1

    def _p2p_due(self) -> None:
        default_probability = self.cfg.p2p_default
        if self.scenario.credit_stress and self._window(24):
            default_probability *= 5.0
        if self.scenario.bear:
            default_probability *= 1.3

        funding_by_id = {item.claim_id: item for item in self.funding}
        for loan in list(self.p2p):
            if loan.due > self.week:
                continue

            principal_d = money(loan.principal)
            if self.rng.random() < default_probability:
                proposed_recovery = loan.principal * self.rng.uniform(0.35, 0.75)
                recovery_d, loss_d = exact_split(principal_d, proposed_recovery)
                if recovery_d > 0:
                    self.ledger.post(
                        reference=f"p2p-rec-v51-{loan.loan_id}",
                        flow_type=FlowType.CREDIT_REPAYMENT,
                        lines=(
                            JournalLine("cash", debit=recovery_d),
                            JournalLine("p2p", credit=recovery_d),
                        ),
                    )
                if loss_d > 0:
                    self.ledger.post(
                        reference=f"p2p-loss-v51-{loan.loan_id}",
                        flow_type=FlowType.CREDIT_LOSS,
                        lines=(
                            JournalLine("expense", debit=loss_d),
                            JournalLine("p2p", credit=loss_d),
                        ),
                    )
                    loss = float(loss_d)
                    self.cum["credit_losses"] += loss
                    self._absorb_designation(loss, False)
            else:
                self.ledger.post(
                    reference=f"p2p-pr-v51-{loan.loan_id}",
                    flow_type=FlowType.CREDIT_REPAYMENT,
                    lines=(
                        JournalLine("cash", debit=principal_d),
                        JournalLine("p2p", credit=principal_d),
                    ),
                )
                interest = (
                    loan.principal
                    * loan.rate
                    * (loan.due - loan.start)
                    / 52.0
                )
                self._post_income(f"p2p-int-v51-{loan.loan_id}", interest)
                self.cum["p2p_interest"] += interest

            for claim_id, amount in loan.funding:
                funding = funding_by_id.get(claim_id)
                if funding is not None:
                    funding.committed = max(0.0, funding.committed - amount)
            self.p2p.remove(loan)

    def _productive_originate(self, qe_ratio: float) -> None:
        if qe_ratio <= EPS:
            return
        base = max(
            100_000.0,
            self.rng.gauss(
                1_000_000.0 * (0.85 if self.scenario.bear else 1.0),
                120_000.0,
            ),
        )
        values = [base * self.rng.uniform(0.93, 1.07) for _ in range(7)]
        if self.scenario.oracle_attack and self._window(8):
            values[0] *= 8.0
            values[1] *= 5.0
            self.cum["oracle_blocked"] += values[0] + values[1] - 2 * base

        request = ProductiveCreditRequest(
            f"project-v51-{self.week}",
            requested_credit=1_000_000.0,
            attestations=tuple(
                VerifierAttestation(f"v{i}", value, 10_000.0)
                for i, value in enumerate(values)
            ),
        )
        try:
            capacity = self.verification.capacity(
                request,
                reserve_capacity=max(0.0, (self.general + self.first_loss) * 0.30),
                liquidity_capacity=max(
                    0.0,
                    self.bal("cash") - 1.20 * self._immediate_due(),
                ),
                risk_capacity=max(0.0, self._economic_nav() * qe_ratio),
            )
        except RuntimeError:
            return

        amount = float(
            money(
                min(
                    capacity.approved_credit,
                    max(0.0, self._economic_nav()) * qe_ratio,
                )
            )
        )
        if amount < 25_000:
            return
        amount_d = money(amount)
        self.ledger.post(
            reference=f"prod-orig-v51-{self.next_id}",
            flow_type=FlowType.LIABILITY_ISSUANCE,
            lines=(
                JournalLine("productive", debit=amount_d),
                JournalLine("escrow", credit=amount_d),
            ),
        )
        self.productive.append(
            ProductiveLoan(
                self.next_id,
                amount,
                self.week,
                self.week + self.rng.randint(8, 26),
                self.rng.uniform(0.06, 0.14),
            )
        )
        self.next_id += 1
        self.cum["qe_issued"] += amount

    def _productive_due(self) -> None:
        default_probability = self.cfg.productive_default
        if self.scenario.credit_stress and self._window(24):
            default_probability *= 3.5
        if self.scenario.bear:
            default_probability *= 1.35

        for loan in list(self.productive):
            if loan.due > self.week:
                continue
            principal_d = money(loan.principal)
            if self.rng.random() < default_probability:
                recovery_d, loss_d = exact_split(
                    principal_d,
                    loan.principal * self.rng.uniform(0.10, 0.45),
                )
                if recovery_d > 0:
                    self.ledger.post(
                        reference=f"prod-rec-v51-{loan.loan_id}",
                        flow_type=FlowType.CREDIT_REPAYMENT,
                        lines=(
                            JournalLine("escrow", debit=recovery_d),
                            JournalLine("productive", credit=recovery_d),
                        ),
                    )
                    self.cum["qt_retired"] += float(recovery_d)
                if loss_d > 0:
                    self.ledger.post(
                        reference=f"prod-loss-v51-{loan.loan_id}",
                        flow_type=FlowType.CREDIT_LOSS,
                        lines=(
                            JournalLine("expense", debit=loss_d),
                            JournalLine("productive", credit=loss_d),
                        ),
                    )
                    loss = float(loss_d)
                    self.cum["productive_losses"] += loss
                    self._absorb_designation(loss, False)
            else:
                self.ledger.post(
                    reference=f"prod-pr-v51-{loan.loan_id}",
                    flow_type=FlowType.CREDIT_REPAYMENT,
                    lines=(
                        JournalLine("escrow", debit=principal_d),
                        JournalLine("productive", credit=principal_d),
                    ),
                )
                self.cum["qt_retired"] += loan.principal
                interest = (
                    loan.principal
                    * loan.rate
                    * (loan.due - loan.start)
                    / 52.0
                )
                self._post_income(f"prod-int-v51-{loan.loan_id}", interest)
                self.cum["productive_interest"] += interest
            self.productive.remove(loan)

    def step(self) -> None:
        self._assert_nonnegative_state()
        super().step()
        self._assert_nonnegative_state()
        self.ledger.assert_balanced()


def run_hardened_matrix(seed: int = 20260809) -> list[dict[str, object]]:
    scenarios = (
        Scenario("base"),
        Scenario("bear", bear=True),
        Scenario("liquidity_run", mass_withdrawal=True, bridge_failure=True),
        Scenario("credit_wave", credit_stress=True, bear=True),
        Scenario("oracle_mev", oracle_attack=True, adversarial_flow=True),
        Scenario(
            "combined_adversarial",
            bear=True,
            mass_withdrawal=True,
            credit_stress=True,
            bridge_failure=True,
            midas_crash=True,
            insurance_catastrophe=True,
            oracle_attack=True,
            adversarial_flow=True,
        ),
    )
    rows: list[dict[str, object]] = []
    for cycles in (100, 250, 500):
        for scenario in scenarios:
            result = HardenedFinancialOSSimulation(
                cycles,
                seed + cycles * 10,
                scenario,
            ).run()
            result["simulation_version"] = "5.1-hardened"
            rows.append(result)
    return rows
