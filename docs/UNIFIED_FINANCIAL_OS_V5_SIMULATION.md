# SINERGY Financial OS V5 — unified 100–500 cycle simulation

Status: **research / draft / non-production**.

The simulator in `simulation/financial_os_v5_integrated.py` is the first single stateful harness in this branch that connects the new canonical components instead of evaluating them as independent examples.

## One cycle

One cycle is one research week:

```text
maturities/unlocks
  -> P2P repayments/defaults
  -> productive-credit repayments/defaults + QT
  -> insured catastrophe events
  -> new voluntary 2–5% savings
  -> Monetary Constitution decision
  -> duration-matched P2P origination
  -> 7-verifier productive-credit gate / temporary SYNT
  -> MetaPay clearing / settlement economics
  -> capped MIDAS sleeve
  -> reserve income
  -> bad-credit-liability retirement from hard surplus
  -> double-entry reconciliation
  -> FinancialSnapshot V2 + digest
```

## Source of truth

The simulator posts all monetary events to `CanonicalDoubleEntryLedger`.

The final accounting truth is therefore not a token price or a synthetic score. It is:

- `HardNAV`;
- `LiquidNAV`;
- `EconomicNAV`;
- external liabilities;
- ledger trial balance;
- 1–100 week unlock curve;
- LCR;
- realised external income and external losses.

`FinancialSnapshotV2` carries both the ledger sequence and SHA-256 ledger digest so a portal cannot recompute a more attractive balance from browser prices.

## Savings / P2P

The reference population is 200 participants. Weekly voluntary saving is randomly sampled inside 2–5% of model income.

Each saving inflow is split into maturity claims between 4 and 100 weeks.

P2P credit can use only tranches where:

```text
LoanDueWeek < FundingUnlockWeek
```

A maturity arriving with still-committed funding is an invariant failure rather than an automatic rollover hidden from the user.

## Productive credit / temporary money

Every productive-credit request passes seven bonded verifier attestations.

The approved amount is bounded by the same four-way minimum used in the canonical productive-credit component:

```text
min(
  requested credit,
  verified productive value after haircut,
  reserve capacity,
  liquidity capacity,
  risk/policy capacity
)
```

Normal principal repayment cancels the productive asset and the associated temporary-SYNT liability. Only externally paid interest becomes income.

A default removes the impaired asset but leaves the unmatched temporary liability until actual hard surplus retires it. There is no automatic 'debt disappearance' from an unrealised asset mark.

## Oracle attack

In the oracle-attack scenario two of the seven reported productive values are inflated by large factors.

The robust verifier-consensus gate rejects the evidence set. The attempted inflated nominal value is recorded as `oracle_blocked_value` for diagnostics but **never enters the journal, HardNAV, reserves or mint capacity**.

## MetaPay

The simulation uses multilateral-netting economics and a finite prefund capacity. During bridge failure, settlement capacity is sharply reduced and unfilled net settlement is recorded explicitly.

MetaPay economics distinguish:

- user fee / external liability extinguishment;
- hard settlement cost;
- adversarial-flow/MEV leakage;
- unsettled amount.

Gross routed value is not revenue.

The production-side MetaPay V2 implementation has a separate `RFQAuction` that uses `LiquidityBook` prefund + net-debit-cap reservations before creating an immutable `ExecutionPlan`.

## MIDAS

MIDAS is a capped risk sleeve. The simulator uses a maximum 10% exposure and an 8% drawdown kill rule. A crash becomes a real hard expense, not an insurance claim.

## Policy modes

The same `Constitution` used by the branch determines:

- `GROWTH`;
- `NORMAL`;
- `DEFENSE`;
- `EMERGENCY`.

The controller sees hard coverage, LCR, NPL, reserve coverage, upcoming unlock pressure and MIDAS drawdown. Any unsafe action is clipped by the constitution before the simulated execution stage.

## Scenario matrix

The integrated file defines:

1. `base`;
2. `bear`;
3. `liquidity_run` — mass withdrawal + bridge failure;
4. `credit_wave` — bear + credit defaults;
5. `oracle_mev` — verifier manipulation + adversarial payment flow;
6. `combined_adversarial` — all major shocks together.

Each scenario is designed for 100, 250 and 500 cycles.

This is intentionally wider than the old one-score model. A scenario can have higher HardNAV simply because it deleverages and holds more cash while having lower EconomicNAV or lower external operating result. Those trade-offs are the point of the model.

## Local reference audit

Before the repository-level integration file was committed, a deterministic standalone harness implementing the same conservation rules was run at 100, 250 and 500 cycles.

The reference file is `simulation/reference_results_v5.json` and is explicitly tagged `LOCAL_REFERENCE_NOT_CI`.

Key observations:

- all nine reference runs had `invariant_failures = 0`;
- maximum book-conservation error remained about `2.13e-6` or lower;
- 100-cycle combined adversarial stress produced **negative external operating result**, approximately `-950,887`, while preserving positive EconomicNAV;
- the same 100-cycle stress generated about `3.75m` unsettled MetaPay flow;
- attempted oracle overvaluation of about `30.73m` was recorded as blocked nominal value and was not capitalised;
- in the 500-cycle combined stress, the policy spent time in `GROWTH`, `NORMAL`, `DEFENSE` and `EMERGENCY` rather than remaining permanently optimistic;
- temporary productive liabilities were progressively retired by QT/principal settlement; reference retirement ratios were roughly 0.82–0.97 depending on horizon/stress.

These numbers are **not forecasts, APY estimates or investment claims**. They are deterministic outputs of the current research assumptions and are expected to change as the simulator is hardened.

## Current validation limitation

A feature-only GitHub Actions workflow was added for compile and unit tests. GitHub created the runs but did not start a runner because the account currently has a billing/spending-limit restriction. Therefore a red workflow badge at this stage is infrastructure status, not evidence of a Python test failure.

The branch and PR must remain draft until an actual runner executes the full suite.
