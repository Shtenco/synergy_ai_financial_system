from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
import json
import random

from financial_os_v4.accounting import (
    AccountClass, AccountSpec, CanonicalDoubleEntryLedger, FlowType, JournalLine,
)
from financial_os_v4.core import Constitution, MonetaryState
from financial_os_v4.maturity import MaturityBook, MaturityClaim
from financial_os_v4.money import SegregatedTripleMoneyLedger
from financial_os_v4.productive_credit import (
    ProductiveCreditRequest, VerificationPolicy, VerifierAttestation,
)
from financial_os_v4.snapshot_v2 import FinancialSnapshotV2

D = Decimal
EPS = 1e-9


def dec(x: float) -> Decimal:
    return D(str(round(max(0.0, x), 6)))


@dataclass(frozen=True)
class Scenario:
    name: str = "base"
    bear: bool = False
    mass_withdrawal: bool = False
    credit_stress: bool = False
    bridge_failure: bool = False
    midas_crash: bool = False
    insurance_catastrophe: bool = False
    oracle_attack: bool = False
    adversarial_flow: bool = False


@dataclass(frozen=True)
class Config:
    participants: int = 200
    weekly_income: float = 100_000.0
    savings_min: float = 0.02
    savings_max: float = 0.05
    initial_capital: float = 25_000_000.0
    initial_synt: float = 20_000_000.0
    p2p_cap: float = 0.45
    p2p_default: float = 0.009
    productive_default: float = 0.020
    metapay_prefund: float = 7_500_000.0
    metapay_netting: float = 0.82
    metapay_fee: float = 0.0015
    metapay_cost: float = 0.0005
    reserve_yield_weekly: float = 0.04 / 52.0
    insurance_initial: float = 4_000_000.0
    general_initial: float = 5_000_000.0
    sponsor_first_loss: float = 5_000_000.0
    midas_kill_dd: float = 0.08


@dataclass
class Funding:
    claim_id: str
    amount: float
    due_week: int
    committed: float = 0.0

    @property
    def available(self) -> float:
        return max(0.0, self.amount - self.committed)


@dataclass
class P2PLoan:
    loan_id: int
    principal: float
    start: int
    due: int
    rate: float
    funding: list[tuple[str, float]]


@dataclass
class ProductiveLoan:
    loan_id: int
    principal: float
    start: int
    due: int
    rate: float


class IntegratedFinancialOSSimulation:
    def __init__(self, cycles: int, seed: int, scenario: Scenario, config: Config | None = None):
        if cycles not in (100, 250, 500):
            raise ValueError("cycles must be one of 100, 250, 500")
        self.cycles = cycles
        self.rng = random.Random(seed)
        self.scenario = scenario
        self.cfg = config or Config()
        self.ledger = self._ledger()
        self.maturity = MaturityBook()
        self.constitution = Constitution()
        self.verification = VerificationPolicy()
        self.funding: list[Funding] = []
        self.p2p: list[P2PLoan] = []
        self.productive: list[ProductiveLoan] = []
        self.week = 0
        self.next_id = 1
        self.insurance = self.cfg.insurance_initial
        self.general = self.cfg.general_initial
        self.first_loss = self.cfg.sponsor_first_loss
        self.midas_nav = 1.0
        self.midas_hwm = 1.0
        self.midas_active = True
        self.midas_killed_week: int | None = None
        self.cum = {k: 0.0 for k in (
            "p2p_interest", "productive_interest", "credit_losses", "productive_losses",
            "metapay_fee", "metapay_cost", "metapay_unsettled", "midas_pnl",
            "reserve_income", "insurance_catastrophe", "qe_issued", "qt_retired",
            "oracle_blocked", "adversarial_cost",
        )}
        self.invariant_failures = 0
        self.mode_counts = {"GROWTH": 0, "NORMAL": 0, "DEFENSE": 0, "EMERGENCY": 0}
        self.history: list[dict[str, float | int | str | bool | None]] = []
        self.previous_snapshot_sequence = self.ledger.sequence
        self.previous_hard_nav = self.ledger.balance_sheet().hard_nav

    def _ledger(self) -> CanonicalDoubleEntryLedger:
        c = self.cfg
        l = CanonicalDoubleEntryLedger("KZT")
        l.register_account(AccountSpec("cash", "External cash", AccountClass.ASSET, 1.0, 1.0, 1.0))
        l.register_account(AccountSpec("p2p", "Performing P2P", AccountClass.ASSET, 0.0, 0.35, 0.90))
        l.register_account(AccountSpec("productive", "Verified productive credit", AccountClass.ASSET, 0.0, 0.10, 0.75))
        l.register_account(AccountSpec("savings", "Term savings", AccountClass.LIABILITY))
        l.register_account(AccountSpec("synt", "SYNT immediate", AccountClass.LIABILITY, immediate_liability=True))
        l.register_account(AccountSpec("escrow", "Productive temporary SYNT", AccountClass.LIABILITY))
        l.register_account(AccountSpec("capital", "Sponsor equity", AccountClass.EQUITY))
        l.register_account(AccountSpec("income", "External income", AccountClass.INCOME))
        l.register_account(AccountSpec("expense", "External losses and costs", AccountClass.EXPENSE))
        l.post(reference="initial-capital", flow_type=FlowType.EXTERNAL_CAPITAL, lines=(
            JournalLine("cash", debit=dec(c.initial_capital)), JournalLine("capital", credit=dec(c.initial_capital)),
        ))
        l.post(reference="initial-synt", flow_type=FlowType.LIABILITY_ISSUANCE, lines=(
            JournalLine("cash", debit=dec(c.initial_synt)), JournalLine("synt", credit=dec(c.initial_synt)),
        ))
        return l

    def bal(self, account: str) -> float:
        return float(self.ledger.balance(account))

    def _window(self, width: int) -> bool:
        start = max(10, self.cycles // 2)
        return start <= self.week < min(self.cycles, start + width)

    def _post_income(self, reference: str, amount: float) -> None:
        if amount <= EPS:
            return
        self.ledger.post(reference=reference, flow_type=FlowType.EXTERNAL_REVENUE, lines=(
            JournalLine("cash", debit=dec(amount)), JournalLine("income", credit=dec(amount)),
        ))

    def _post_expense(self, reference: str, amount: float) -> None:
        amount = min(amount, self.bal("cash"))
        if amount <= EPS:
            return
        self.ledger.post(reference=reference, flow_type=FlowType.EXTERNAL_EXPENSE, lines=(
            JournalLine("expense", debit=dec(amount)), JournalLine("cash", credit=dec(amount)),
        ))

    def _absorb_designation(self, loss: float, insurance_eligible: bool) -> None:
        remaining = loss
        if insurance_eligible:
            take = min(self.insurance, remaining); self.insurance -= take; remaining -= take
        take = min(self.general, remaining); self.general -= take; remaining -= take
        take = min(self.first_loss, remaining); self.first_loss -= take; remaining -= take
        if remaining > 1e-6:
            self.invariant_failures += 1

    def _savings(self) -> None:
        c = self.cfg
        inflow_factor = 0.35 if (self.scenario.mass_withdrawal and self._window(16)) else (0.8 if self.scenario.bear else 1.0)
        amount = c.participants * c.weekly_income * self.rng.uniform(c.savings_min, c.savings_max) * inflow_factor
        self.ledger.post(reference=f"sav-in-{self.week}", flow_type=FlowType.LIABILITY_ISSUANCE, lines=(
            JournalLine("cash", debit=dec(amount)), JournalLine("savings", credit=dec(amount)),
        ))
        for part in range(5):
            piece = amount / 5.0
            due = self.week + self.rng.randint(4, 100)
            claim_id = f"sav-{self.week}-{part}"
            self.maturity.add(MaturityClaim(claim_id, piece, due, "term-savings"))
            self.funding.append(Funding(claim_id, piece, due))

    def _maturities(self) -> None:
        withdrawal = 0.90 if (self.scenario.mass_withdrawal and self._window(16)) else 0.30
        for f in list(self.funding):
            if f.due_week > self.week:
                continue
            if f.committed > 1e-5:
                self.invariant_failures += 1
                f.due_week += 1
                continue
            requested = f.amount * withdrawal
            paid = min(requested, self.bal("cash"), self.bal("savings"))
            if paid > EPS:
                self.ledger.post(reference=f"sav-out-{self.week}-{f.claim_id}", flow_type=FlowType.LIABILITY_REDEMPTION, lines=(
                    JournalLine("savings", debit=dec(paid)), JournalLine("cash", credit=dec(paid)),
                ))
            if paid + 1e-5 < requested:
                self.invariant_failures += 1
                f.amount -= paid
                f.due_week += 1
                continue
            rollover = f.amount - paid
            self.maturity.remove(f.claim_id)
            self.funding.remove(f)
            if rollover > EPS:
                due = self.week + self.rng.randint(12, 100)
                cid = f"roll-{self.week}-{self.next_id}"; self.next_id += 1
                self.maturity.add(MaturityClaim(cid, rollover, due, "term-savings-rollover"))
                self.funding.append(Funding(cid, rollover, due))

    def _p2p_due(self) -> None:
        default_p = self.cfg.p2p_default * (5.0 if self.scenario.credit_stress and self._window(24) else 1.0) * (1.3 if self.scenario.bear else 1.0)
        by_id = {x.claim_id: x for x in self.funding}
        for loan in list(self.p2p):
            if loan.due > self.week:
                continue
            if self.rng.random() < default_p:
                recovery = loan.principal * self.rng.uniform(0.35, 0.75)
                loss = loan.principal - recovery
                self.ledger.post(reference=f"p2p-rec-{loan.loan_id}", flow_type=FlowType.CREDIT_REPAYMENT, lines=(
                    JournalLine("cash", debit=dec(recovery)), JournalLine("p2p", credit=dec(recovery)),
                ))
                self.ledger.post(reference=f"p2p-loss-{loan.loan_id}", flow_type=FlowType.CREDIT_LOSS, lines=(
                    JournalLine("expense", debit=dec(loss)), JournalLine("p2p", credit=dec(loss)),
                ))
                self.cum["credit_losses"] += loss
                self._absorb_designation(loss, False)
            else:
                self.ledger.post(reference=f"p2p-pr-{loan.loan_id}", flow_type=FlowType.CREDIT_REPAYMENT, lines=(
                    JournalLine("cash", debit=dec(loan.principal)), JournalLine("p2p", credit=dec(loan.principal)),
                ))
                interest = loan.principal * loan.rate * (loan.due - loan.start) / 52.0
                self._post_income(f"p2p-int-{loan.loan_id}", interest)
                self.cum["p2p_interest"] += interest
            for claim_id, amount in loan.funding:
                if claim_id in by_id:
                    by_id[claim_id].committed = max(0.0, by_id[claim_id].committed - amount)
            self.p2p.remove(loan)

    def _p2p_originate(self, cap: float) -> None:
        savings = self.bal("savings")
        headroom = max(0.0, savings * min(cap, self.cfg.p2p_cap) - self.bal("p2p"))
        cash_headroom = max(0.0, self.bal("cash") - 1.15 * self._immediate_due())
        amount = min(headroom, cash_headroom, savings * self.rng.uniform(0.01, 0.035))
        if amount < 10_000:
            return
        maturity = self.rng.randint(4, 20); due = self.week + maturity
        eligible = sorted((f for f in self.funding if f.due_week > due and f.available > EPS), key=lambda x: x.due_week, reverse=True)
        left = amount; used: list[tuple[str, float]] = []
        for f in eligible:
            take = min(left, f.available); f.committed += take; used.append((f.claim_id, take)); left -= take
            if left <= EPS: break
        principal = amount - left
        if principal < 10_000:
            for cid, take in used:
                for f in self.funding:
                    if f.claim_id == cid: f.committed -= take
            return
        self.ledger.post(reference=f"p2p-orig-{self.next_id}", flow_type=FlowType.CREDIT_ORIGINATION, lines=(
            JournalLine("p2p", debit=dec(principal)), JournalLine("cash", credit=dec(principal)),
        ))
        self.p2p.append(P2PLoan(self.next_id, principal, self.week, due, self.rng.uniform(0.12, 0.24), used))
        self.next_id += 1

    def _productive_due(self) -> None:
        p = self.cfg.productive_default * (3.5 if self.scenario.credit_stress and self._window(24) else 1.0) * (1.35 if self.scenario.bear else 1.0)
        for loan in list(self.productive):
            if loan.due > self.week:
                continue
            if self.rng.random() < p:
                recovery = loan.principal * self.rng.uniform(0.10, 0.45)
                loss = loan.principal - recovery
                if recovery > EPS:
                    self.ledger.post(reference=f"prod-rec-{loan.loan_id}", flow_type=FlowType.CREDIT_REPAYMENT, lines=(
                        JournalLine("escrow", debit=dec(recovery)), JournalLine("productive", credit=dec(recovery)),
                    ))
                    self.cum["qt_retired"] += recovery
                self.ledger.post(reference=f"prod-loss-{loan.loan_id}", flow_type=FlowType.CREDIT_LOSS, lines=(
                    JournalLine("expense", debit=dec(loss)), JournalLine("productive", credit=dec(loss)),
                ))
                self.cum["productive_losses"] += loss
                self._absorb_designation(loss, False)
            else:
                self.ledger.post(reference=f"prod-pr-{loan.loan_id}", flow_type=FlowType.CREDIT_REPAYMENT, lines=(
                    JournalLine("escrow", debit=dec(loan.principal)), JournalLine("productive", credit=dec(loan.principal)),
                ))
                self.cum["qt_retired"] += loan.principal
                interest = loan.principal * loan.rate * (loan.due - loan.start) / 52.0
                self._post_income(f"prod-int-{loan.loan_id}", interest)
                self.cum["productive_interest"] += interest
            self.productive.remove(loan)

    def _productive_originate(self, qe_ratio: float) -> None:
        if qe_ratio <= EPS:
            return
        base = max(100_000.0, self.rng.gauss(1_000_000.0 * (0.85 if self.scenario.bear else 1.0), 120_000.0))
        values = [base * self.rng.uniform(0.93, 1.07) for _ in range(7)]
        if self.scenario.oracle_attack and self._window(8):
            values[0] *= 8.0; values[1] *= 5.0
            self.cum["oracle_blocked"] += values[0] + values[1] - 2 * base
        req = ProductiveCreditRequest(
            f"project-{self.week}",
            requested_credit=1_000_000.0,
            attestations=tuple(VerifierAttestation(f"v{i}", v, 10_000.0) for i, v in enumerate(values)),
        )
        try:
            cap = self.verification.capacity(
                req,
                reserve_capacity=max(0.0, (self.general + self.first_loss) * 0.30),
                liquidity_capacity=max(0.0, self.bal("cash") - 1.20 * self._immediate_due()),
                risk_capacity=max(0.0, self._economic_nav() * qe_ratio),
            )
        except RuntimeError:
            return
        amount = min(cap.approved_credit, max(0.0, self._economic_nav()) * qe_ratio)
        if amount < 25_000:
            return
        self.ledger.post(reference=f"prod-orig-{self.next_id}", flow_type=FlowType.LIABILITY_ISSUANCE, lines=(
            JournalLine("productive", debit=dec(amount)), JournalLine("escrow", credit=dec(amount)),
        ))
        self.productive.append(ProductiveLoan(self.next_id, amount, self.week, self.week + self.rng.randint(8, 26), self.rng.uniform(0.06, 0.14)))
        self.next_id += 1; self.cum["qe_issued"] += amount

    def _retire_credit_hole(self) -> None:
        hole = max(0.0, self.bal("escrow") - self.bal("productive"))
        hard_surplus = max(0.0, min(self.bal("cash"), self._hard_nav()))
        amount = min(hole, hard_surplus * 0.05)
        if amount > EPS:
            self.ledger.post(reference=f"qt-hole-{self.week}", flow_type=FlowType.LIABILITY_REDEMPTION, lines=(
                JournalLine("escrow", debit=dec(amount)), JournalLine("cash", credit=dec(amount)),
            ))
            self.cum["qt_retired"] += amount

    def _metapay(self) -> None:
        gross = self.bal("synt") * 0.20 * self.rng.uniform(0.75, 1.25)
        eff = min(0.95, max(0.50, self.rng.gauss(self.cfg.metapay_netting, 0.04)))
        net = gross * (1.0 - eff)
        cap = self.cfg.metapay_prefund * (0.12 if self.scenario.bridge_failure and self._window(12) else 1.0)
        settled = min(net, cap); unsettled = max(0.0, net - settled)
        fill = 0.0 if net <= EPS else settled / net
        fee = min(self.bal("synt"), gross * fill * self.cfg.metapay_fee)
        if fee > EPS:
            self.ledger.post(reference=f"metapay-fee-{self.week}", flow_type=FlowType.EXTERNAL_REVENUE, lines=(
                JournalLine("synt", debit=dec(fee)), JournalLine("income", credit=dec(fee)),
            ))
        cost = settled * self.cfg.metapay_cost
        if self.scenario.adversarial_flow and self._window(12):
            extra = settled * 0.0015; cost += extra; self.cum["adversarial_cost"] += extra
        self._post_expense(f"metapay-cost-{self.week}", cost)
        self.cum["metapay_fee"] += fee; self.cum["metapay_cost"] += cost; self.cum["metapay_unsettled"] += unsettled

    def _midas(self, cap_ratio: float) -> float:
        if not self.midas_active or cap_ratio <= EPS:
            return 0.0
        sleeve = max(0.0, self._economic_nav()) * min(0.10, cap_ratio)
        crash = self.scenario.midas_crash and self.week == max(10, self.cycles // 2)
        mean = -0.0002 if self.scenario.bear else 0.0006
        ret = -0.11 if crash else self.rng.gauss(mean, 0.010)
        pnl = sleeve * ret
        if pnl >= 0: self._post_income(f"midas-{self.week}", pnl)
        else: self._post_expense(f"midas-{self.week}", -pnl)
        self.cum["midas_pnl"] += pnl
        self.midas_nav = max(0.01, self.midas_nav * (1.0 + ret)); self.midas_hwm = max(self.midas_hwm, self.midas_nav)
        dd = 1.0 - self.midas_nav / self.midas_hwm
        if dd >= self.cfg.midas_kill_dd:
            self.midas_active = False; self.midas_killed_week = self.week
        return dd

    def _reserve_income(self) -> None:
        base = min(self.bal("cash"), self.insurance + self.general)
        income = base * self.cfg.reserve_yield_weekly
        self._post_income(f"reserve-income-{self.week}", income); self.cum["reserve_income"] += income

    def _catastrophe(self) -> None:
        if not (self.scenario.insurance_catastrophe and self.week == max(10, self.cycles // 2)):
            return
        loss = min(self.bal("cash"), 0.12 * self.bal("synt"))
        self._post_expense(f"catastrophe-{self.week}", loss)
        self.cum["insurance_catastrophe"] += loss; self._absorb_designation(loss, True)

    def _hard_nav(self) -> float:
        return self.ledger.balance_sheet().hard_nav

    def _liquid_nav(self) -> float:
        return self.ledger.balance_sheet().liquid_nav

    def _economic_nav(self) -> float:
        return self.ledger.balance_sheet().economic_nav

    def _immediate_due(self) -> float:
        return self.bal("synt") + self.maturity.due_through(self.week, 1)

    def _lcr(self, horizon: int) -> float:
        due = self.maturity.due_through(self.week, horizon) + 0.05 * self.bal("synt")
        if due <= EPS: return 99.0
        expected = sum(x.principal for x in self.p2p if self.week < x.due <= self.week + horizon) * 0.90
        return (self.bal("cash") + expected) / due

    def _npl(self) -> float:
        losses = self.cum["credit_losses"] + self.cum["productive_losses"]
        originated = max(EPS, self.cum["qe_issued"] + self.bal("p2p") + losses)
        return min(1.0, losses / originated)

    def _policy(self, midas_dd: float) -> tuple[str, float, float, float, object]:
        immediate = self._immediate_due(); hard_ratio = 99.0 if immediate <= EPS else self.bal("cash") / immediate
        savings = max(EPS, self.bal("savings")); unlock8 = self.maturity.due_through(self.week, 8) / savings
        state = MonetaryState(
            inflation=0.035 if self.scenario.bear else 0.02,
            output_gap=-0.04 if self.scenario.bear else 0.0,
            unemployment_gap=0.03 if self.scenario.bear else 0.0,
            velocity_gap=-0.05 if self.scenario.bear else 0.0,
            hard_nav_ratio=hard_ratio,
            liquidity_coverage_ratio=self._lcr(8),
            nonperforming_loan_ratio=self._npl(),
            reserve_coverage_ratio=max(0.0, (self.insurance + self.general + self.first_loss) / max(EPS, self.bal("synt"))),
            upcoming_unlock_ratio_8w=unlock8,
            external_pnl_ratio=0.0,
        )
        guarded_dd = midas_dd if self.midas_active else 0.0
        decision = self.constitution.decide(state, midas_drawdown=guarded_dd, unbacked_mint=0.0, flash_debt_at_commit=0.0)
        a = decision.bounded
        return decision.mode, a.credit_cap_ratio, a.productive_qe_ratio, a.midas_cap_ratio, decision

    def _snapshot(self, decision: object) -> FinancialSnapshotV2:
        immediate = self.bal("synt")
        money = SegregatedTripleMoneyLedger(synt_money_units=immediate, synt_hard_reserve=min(immediate, self.bal("cash")))
        snap = FinancialSnapshotV2.capture(
            ledger=self.ledger,
            previous_ledger_sequence=self.previous_snapshot_sequence,
            previous_hard_nav=self.previous_hard_nav,
            money=money,
            maturity=self.maturity,
            policy=decision,
            current_week=self.week,
            liquid_reserve=self.bal("cash"),
            expected_inflows_8w=sum(x.principal for x in self.p2p if self.week < x.due <= self.week + 8) * 0.90,
            stress_buffer_8w=0.05 * self.bal("synt"),
        )
        self.previous_snapshot_sequence = self.ledger.sequence; self.previous_hard_nav = snap.hard_nav
        return snap

    def step(self) -> None:
        self.week += 1
        self._maturities(); self._p2p_due(); self._productive_due(); self._catastrophe(); self._savings()
        midas_dd = 1.0 - self.midas_nav / max(EPS, self.midas_hwm)
        mode, p2p_cap, qe, midas_cap, decision = self._policy(midas_dd)
        self.mode_counts[mode] += 1
        self._p2p_originate(p2p_cap); self._productive_originate(qe); self._metapay(); self._midas(midas_cap)
        self._reserve_income(); self._retire_credit_hole(); self.ledger.assert_balanced()
        snap = self._snapshot(decision)
        if snap.hard_coverage_ratio is not None and snap.hard_coverage_ratio < 1.0: self.invariant_failures += 1
        if snap.lcr_8w is not None and snap.lcr_8w < 1.0: self.invariant_failures += 1
        self.history.append({
            "week": self.week, "mode": mode, "hard_nav": snap.hard_nav, "liquid_nav": snap.liquid_nav,
            "economic_nav": snap.economic_nav, "hard_coverage": snap.hard_coverage_ratio or 99.0,
            "lcr_8w": snap.lcr_8w or 99.0, "npl": self._npl(), "ledger_sequence": snap.ledger_sequence,
            "ledger_digest": snap.ledger_digest_sha256, "snapshot_digest": snap.digest_sha256,
        })

    def run(self) -> dict[str, object]:
        for _ in range(self.cycles): self.step()
        h = self.history[-1]
        net_external = (
            self.cum["p2p_interest"] + self.cum["productive_interest"] + self.cum["metapay_fee"]
            + self.cum["midas_pnl"] + self.cum["reserve_income"] - self.cum["metapay_cost"]
            - self.cum["credit_losses"] - self.cum["productive_losses"] - self.cum["insurance_catastrophe"]
        )
        return {
            "scenario": self.scenario.name, "cycles": self.cycles, "final_mode": h["mode"],
            "final_hard_nav": h["hard_nav"], "final_liquid_nav": h["liquid_nav"], "final_economic_nav": h["economic_nav"],
            "min_hard_coverage": min(float(x["hard_coverage"]) for x in self.history),
            "min_lcr_8w": min(float(x["lcr_8w"]) for x in self.history), "final_npl": h["npl"],
            "net_external_operating_result": net_external, "qe_issued": self.cum["qe_issued"], "qt_retired": self.cum["qt_retired"],
            "qt_retirement_ratio": 0.0 if self.cum["qe_issued"] <= EPS else self.cum["qt_retired"] / self.cum["qe_issued"],
            "metapay_unsettled": self.cum["metapay_unsettled"], "oracle_blocked_value": self.cum["oracle_blocked"],
            "midas_active": self.midas_active, "midas_killed_week": self.midas_killed_week,
            "invariant_failures": self.invariant_failures, "ledger_sequence": self.ledger.sequence,
            "ledger_digest_sha256": self.ledger.digest_sha256, "snapshot_digest_sha256": h["snapshot_digest"],
            **{f"weeks_{k.lower()}": v for k, v in self.mode_counts.items()},
        }


def run_matrix(seed: int = 20260809) -> list[dict[str, object]]:
    scenarios = (
        Scenario("base"),
        Scenario("bear", bear=True),
        Scenario("liquidity_run", mass_withdrawal=True, bridge_failure=True),
        Scenario("credit_wave", credit_stress=True, bear=True),
        Scenario("oracle_mev", oracle_attack=True, adversarial_flow=True),
        Scenario("combined_adversarial", bear=True, mass_withdrawal=True, credit_stress=True, bridge_failure=True,
                 midas_crash=True, insurance_catastrophe=True, oracle_attack=True, adversarial_flow=True),
    )
    rows: list[dict[str, object]] = []
    for cycles in (100, 250, 500):
        for scenario in scenarios:
            rows.append(IntegratedFinancialOSSimulation(cycles, seed + cycles * 10, scenario).run())
    return rows


if __name__ == "__main__":
    print(json.dumps(run_matrix(), ensure_ascii=False, indent=2))
