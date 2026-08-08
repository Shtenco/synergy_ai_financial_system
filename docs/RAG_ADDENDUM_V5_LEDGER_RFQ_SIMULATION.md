# SINERGY RAG Addendum V5 — Ledger / Maturity / RFQ / Unified Simulation

Status: **CANONICAL ADDENDUM** for the feature branch. It extends, not deletes, the architecture center.

## Retrieval priority

For questions involving accounting truth, maturity risk, payment routing or the Grand Unified legacy model, retrieve this addendum together with the central architecture memory.

## A. Canonical ledger truth

The current monetary source of truth is `CanonicalDoubleEntryLedger`.

Every external-value claim must have a balanced journal entry. The portal, token market price, DAO score, AMM mark or simulator score cannot update HardNAV directly.

Canonical external revenue can be received in two economically valid forms:

1. debit to a reconciled external asset, e.g. cash/stable/CBDC settlement;
2. authorised debit/reduction of an external liability, e.g. a MetaPay fee paid by extinguishing a user's SYNT claim.

An internal asset mark or internal income reclassification is zero external value even if a model labels it `revenue`.

## B. FinancialSnapshot V2

`FinancialSnapshotV2` is the current portable audit state for the new branch.

It contains:

- ledger sequence;
- ledger SHA-256 digest;
- HardNAV / LiquidNAV / EconomicNAV;
- hard assets;
- all external liabilities;
- immediate hard liabilities;
- realised external revenue;
- net new capital;
- distributable profit;
- transaction-money coverage;
- 100-week unlock curve;
- 1/4/8/26/100-week unlock totals;
- LCR 1/4/8 weeks;
- policy mode and invariant failures.

The browser is a consumer of this snapshot, not its calculator.

## C. Maturity is part of monetary state

The old idea that vesting is merely a token lock is superseded.

Maturity is a liability schedule and a liquidity constraint.

Canonical questions are:

```text
How much becomes payable in 1 / 4 / 8 / 26 / 100 weeks?
What performing inflows arrive before that date?
What stress buffer is required?
Does LoanMaturity < FundingMaturity hold for every funded loan?
```

## D. MetaPay RFQ / FXP auction

A nominal quote is not a route.

The current MetaPay V2 research path is:

```text
PaymentIntent
  -> executable/compliant Route
  -> RFQ ranking
  -> settlement-provider LiquidityBook check
  -> prefund + NDC reservation
  -> immutable ExecutionPlan
  -> existing live-readiness / provider execution boundary
```

A better price without prefund/NDC headroom is rejected.

A liquidity race between ranking and commit falls through to the next ranked bid. MetaPay must not manufacture liquidity to save the winning quote.

## E. Legacy Grand Unified correction

The historical Grand Unified DAO/AICB model contains a bridge that converts an internal DAO reserve amount into a strategic external reserve by dividing by the FX rate and adding the result to the external reserve basket.

This mechanism is `REJECTED` as a HardNAV source.

Reason:

```text
internal DAO accounting unit / FX quote != externally settled foreign asset
```

Canonical replacement requires settlement/reconciliation evidence before an external-reserve asset can be journalled.

DAO health remains useful only as:

- productive-demand signal;
- credit-risk signal;
- capacity/rating input;
- scenario observation.

It is not cash, reserve, external profit or collateral by itself.

## F. Oracle manipulation

An oracle or verifier claim cannot directly become an asset.

The unified simulation's oracle-attack scenario inflates two verifier values. Robust consensus rejects the evidence set; the attempted nominal overvaluation is recorded only as a blocked diagnostic.

Therefore:

```text
blocked_oracle_value -> diagnostic only
blocked_oracle_value !-> assets
blocked_oracle_value !-> HardNAV
blocked_oracle_value !-> mint capacity
```

## G. Unified simulation success criteria

Do not optimise a single Grand Score.

A scenario is evaluated on a vector:

- trial-balance conservation;
- invariant failures;
- HardNAV / LiquidNAV / EconomicNAV;
- minimum hard coverage;
- minimum LCR;
- NPL/losses;
- realised external operating result;
- productive temporary-liability issuance and QT retirement;
- MetaPay unsettled net flow;
- blocked oracle manipulation;
- MIDAS kill-switch behaviour;
- time spent in GROWTH/NORMAL/DEFENSE/EMERGENCY.

A stress path may have higher HardNAV because it deleverages into cash while simultaneously having lower EconomicNAV and lower external operating result. That is not a contradiction; it is why multiple NAVs are necessary.

## H. Current local reference result

The local pre-integration audit harness produced a useful falsification case at 100 cycles under combined stress:

- external operating result approximately `-950,887`;
- EconomicNAV remained positive;
- MetaPay unsettled amount approximately `3.75m`;
- nominal oracle overvaluation approximately `30.73m` was blocked;
- book conservation gap remained below `1e-6` order of magnitude;
- no invariant failure was recorded in that reference run.

This is a research output, not a forecast or expected return.

## I. Mandatory future regression

Before promotion from draft:

1. actual CI runner must execute the new tests;
2. run 100/250/500 cycles for all integrated scenarios;
3. add Monte Carlo seeds;
4. add explicit provider/rail finality failures;
5. add modelled saver-reward waterfall only after HardNAV buffer tests;
6. add historical/external data replay separately from synthetic simulation;
7. never reintroduce internal-to-external reserve conversion without settlement evidence.
