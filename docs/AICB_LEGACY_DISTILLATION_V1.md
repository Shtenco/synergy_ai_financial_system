# AICB V5/V6 Legacy Distillation V1

Audit source: the 2026-09-11 eight-archive SYNERGY legacy corpus.

## Status

`R&D / SCENARIO ENGINE ONLY`

The audited AICB V5 source was independently smoke-run from the distilled tree. A 12-month seeded run completed and produced timeseries, summaries and charts. The longer historical audit also showed meaningful differences versus V4/baseline and strong sensitivity to foreign-demand/high-rate/supply shocks.

This is useful research code, but its coefficients are simulation assumptions rather than econometrically established causal estimates.

## Authority boundary

AICB may produce:

```text
ScenarioEvidence
PolicyProposal
StressResult
ModelDiagnostics
```

AICB must not directly produce or mutate:

```text
AccountingEntry
HardNAV
PaymentSettlement
TreasuryTransfer
ProductionFact
ObservedEconomicData
```

Those belong to their canonical authorities.

## Required promotion gates

1. model source SHA/provenance recorded;
2. deterministic seed and config recorded;
3. observed vs assumed parameters separated;
4. calibration dataset versioned with `effective_time` and `known_at` where relevant;
5. baseline and counterfactuals preserved;
6. stress matrix includes foreign-demand, rates, supply, liquidity and combined shocks;
7. confidence/uncertainty metrics reported;
8. no model output is relabeled as an observed external fact;
9. Financial OS consumes only reconciled external settlement/accounting evidence, never AICB model PnL;
10. Real Economy OS consumes AICB paths only with `status=SCENARIO` until external evidence supersedes them.

## Legacy finding that must become a permanent regression rule

A model can look excellent while receiving value from an implicit internal source. Therefore every yield, QE injection, reserve increase or asset-flow term must identify its counterparty/source and preserve the balance-sheet equation.
