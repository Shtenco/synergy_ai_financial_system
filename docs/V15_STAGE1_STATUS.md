# SINERGY V15 Stage 1 Status

Base: frozen V13.1 commit `385eaa2e6c811f1f29c504984484d9223b42b1b7`.

Branch: `v15-math-over-v13-1`.

Stage 1 intentionally changes no frozen V13.1 production contract.

Completed:

- formal V15 mathematical specification;
- invariant proof notes;
- overlay architecture;
- Economic HardNAV / RiskNAV separation;
- generic hard-asset / liability reference balance sheet;
- stress scenarios and STS;
- coverage and hysteretic risk modes;
- EXPAND / NEUTRAL / REDUCE / RESTORE action classes;
- bounded defensive actions in RED/ORANGE;
- synthetic supply-partition invariant;
- capital-flow-adjusted operating PnL;
- hard-revenue waterfall cap;
- V13.1 positive latent-basis fixture;
- aligned-market executable-route negative control;
- local reference suite: 12/12 PASS.

Important V13.1 compatibility correction identified:

`SystemAccounting.consolidatedHardNAV1e18()` currently uses haircut hard assets. V15 must split unhaircut Economic HardNAV from haircut/stressed RiskNAV. Future V15 accounting will preserve V13.1 interfaces through an adapter while routing `consolidatedHardNAV1e18()` to economic accounting and `externalCoverageBps()` to risk accounting.

Next stage (not yet implemented): fork-only Solidity accounting/risk layer, then coordinator wiring over unchanged V13.1 edge primitives.
