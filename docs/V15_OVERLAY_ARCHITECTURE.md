# SINERGY V15 — Overlay Architecture over frozen V13.1

Status: reference architecture + tested Python solvency model. V13.1 remains frozen.

## 1. Principle

V15 does not replace the V13.1 edge primitive. It places a stricter accounting/risk controller around it.

Frozen V13.1 supplies:

- supply-neutral reserve gradient;
- managed executor-only pools;
- searcher-funded graph execution;
- realized-profit tax;
- exact synthetic restore;
- stateful reinvest/rotate behavior.

V15 adds:

- economic HardNAV ledger;
- separate RiskNAV / exit-depth / haircut ledger;
- generic liability registry;
- K and STS stress controller;
- hysteretic GREEN/YELLOW/ORANGE/RED state machine;
- action classes EXPAND / NEUTRAL / REDUCE / RESTORE;
- robust post-state admissibility;
- capital-flow-adjusted operating PnL;
- hard-revenue-only waterfall;
- multi-synthetic coordinator.

## 2. Critical correction to V13.1 accounting

V13.1 `SystemAccounting.hardAssets1e18()` applies static haircuts and `consolidatedHardNAV1e18()` subtracts only external USDx liability.

That was acceptable as a conservative V13 gate, but it mixes two different concepts:

1. unhaircut Economic HardNAV used for conservation and realized PnL;
2. haircut/stressed RiskNAV used for solvency decisions.

V15 MUST split them.

The future V15 accounting interface should expose at minimum:

- `economicHardAssets1e18()`;
- `economicLiabilities1e18()`;
- `economicHardNAV1e18()`;
- `riskAssets1e18()`;
- `riskLiabilities1e18()`;
- `riskNAV1e18()`;
- `coverageBps()`;
- `stsBps()`;
- account/asset membership methods needed by `GraphArbExecutor`.

`GraphArbExecutor` economic conservation gate must read the UNHAIRCUT economic HardNAV.

`ReserveGradientEngine` / coordinator solvency gate must read RiskNAV/K/STS.

## 3. Compatibility strategy

V15 is a fork, so frozen V13.1 source remains the reference baseline.

Compatibility is preserved by a new V15 accounting adapter implementing the V13.1 interfaces while routing methods correctly:

- `consolidatedHardNAV1e18()` -> V15 economic HardNAV;
- `externalCoverageBps()` -> V15 risk coverage;
- hard-account membership -> V15 unique-account registry;
- protocol synthetic account membership -> V15 supply-partition registry.

This avoids using one haircut number for two incompatible jobs.

## 4. Multi-synthetic topology

One V13.1 `ReserveGradientEngine` has one immutable controlled synthetic. V15 keeps this simple model.

Recommended topology:

- one engine instance for SYNA;
- one engine instance for SYNR;
- each engine controls its own five managed pools;
- a common `V15Coordinator` selects which engine/source/destination/shift may act;
- both engine instances share the same EconomicLedger, RiskLedger, oracle stack, capture accounting and policy controller.

Thus 2 synthetics x 5 quote assets remain 10 internal pools without turning the gradient contract into a monolith.

## 5. V15Coordinator responsibilities

The coordinator is the operator of all V15-managed gradient engines.

Before an EXPAND action it must:

1. snapshot economic HardNAV;
2. snapshot RiskNAV/K/STS and current mode;
3. validate oracle freshness/confidence;
4. validate synthetic supply partitions;
5. evaluate candidate source/destination/shift/route/QE size;
6. reject if robust gain lower bound is below the configured minimum;
7. reject if post-state K/STS floors would fail;
8. initialize the selected V13.1 gradient only after those checks.

After route execution it must accept only a post-state satisfying all invariants.

If no action is admissible, action = HOLD.

## 6. Action classes

### EXPAND

Examples:

- initialize new gradient;
- increase active risk envelope;
- temporary atomic QE/QT.

Requirements:

- positive robust HardNAV gain;
- full mode-specific K/STS floors;
- fresh oracle bounds;
- supply/accounting invariants.

### NEUTRAL

Examples:

- internal hard-asset transfer;
- rotation that does not expand risk.

Requirements:

- non-negative robust HardNAV;
- no worsening of K or STS.

### REDUCE

Examples:

- repay liability;
- hedge;
- reduce bridge exposure;
- forced deleveraging.

May consume a small bounded amount of HardNAV if K/STS strictly improve.

### RESTORE

Examples:

- exact synthetic restore;
- gradient close;
- accounting repair after a failed/aborted opportunity.

May consume a bounded operational cost but may not worsen solvency.

## 7. Hysteretic state machine

Reference thresholds are policy parameters, not mathematical constants.

GREEN:

- full bounded EXPAND allowed.

YELLOW:

- EXPAND allowed only inside reduced envelope.

ORANGE:

- no EXPAND;
- only NEUTRAL/REDUCE/RESTORE.

RED:

- only REDUCE/RESTORE;
- no new edge initiation.

Re-entry into safer states requires a buffer above the entry threshold to prevent oracle flicker / mode oscillation.

## 8. Oracle stack

V13.1 `PriceOracleHub` provides freshness and reporter-based canonical prices but is not by itself a complete V15 solvency oracle.

V15 RiskMark for hard asset i is:

`pRisk_i = min(pCanonical_i, pTWAP_i, pExit_i(stressSize_i))`.

The future implementation should separate:

- canonical price used for Economic HardNAV conservation;
- TWAP;
- executable exit-depth mark;
- confidence/error bound;
- stale-data state.

An own synthetic oracle price is never added to Economic HardAssets.

## 9. Generic liabilities

V13.1 tracks external USDx liabilities. V15 needs a generic liability registry.

Examples:

- externally redeemable USDx;
- bridge claims;
- permanent hard-backed debt if ever enabled;
- accrued unpaid hard rewards;
- withdrawal claims;
- insurance obligations.

Every externally enforceable claim must be counted exactly once.

Temporary atomic QE that is fully burned before transaction end is not a surviving liability, but its neutrality must be proven transaction-by-transaction.

## 10. Stress set

Minimum V15 stress suite should include correlated scenarios rather than isolated haircuts only:

- stablecoin depeg;
- WETH drawdown;
- WPOL drawdown;
- external depth collapse;
- bridge unavailable;
- gas spike;
- oracle stale/deviation event;
- solver unavailable;
- combined stablecoin + depth shock.

`STS = min_s STS_s`.

The controller uses the worst admissible scenario, not the average scenario.

## 11. Revenue boundary

V15 recognizes operating revenue only through capital-flow-adjusted Economic HardNAV:

`OperatingPnL = HardNAV_after - HardNAV_before - Contributions + Withdrawals`.

Not revenue:

- own-token mint;
- own-token burn;
- synthetic price increase;
- gradient initiation;
- internal transfer;
- owner deposit;
- protocol-funded wash volume.

Only positive realized hard operating PnL surviving reserve/K/STS requirements may enter the waterfall.

## 12. V13.1 acceptance refined by V15

V13.1 already proves the key accounting identity in the closed route universe:

`DeltaProtocol + DeltaExternal + SolverReward ~= 0`.

V15 adds a stronger acceptance requirement:

`RobustGain = DeltaEconomicHardNAV - OracleUncertainty - SystemCost`.

For EXPAND:

`RobustGain >= MinGain > 0`.

For defensive REDUCE/RESTORE, a small bounded negative robust gain may be accepted only when solvency improves or invariants are restored.

## 13. Reference-model status

`simulation/v15/solvency_brain.py` implements the accounting/risk separation and policy state machine.

`tests/test_v15_solvency_brain.py` currently covers:

- own synthetic excluded from HardNAV;
- HardNAV/RiskNAV separation;
- supply-neutral gradient;
- V13.1 latent-basis conservation fixture;
- aligned-market executable-route negative control;
- robust uncertainty/cost rejection;
- HOLD when no admissible candidate exists;
- stress-driven RED mode;
- capital-flow-adjusted PnL;
- hard-revenue waterfall cap;
- ORANGE expansion freeze + unwind allowance;
- RED bounded defensive action allowance.

Local reference result at creation: 12/12 tests PASS.

## 14. Next implementation layer

Do not modify frozen V13.1 history.

The next V15 implementation step should add new fork-only contracts/interfaces in this order:

1. `V15EconomicLedger`;
2. `V15LiabilityRegistry`;
3. `V15RiskOracle` / exit-depth adapters;
4. `V15SolvencyController`;
5. `V15AccountingAdapter` for V13.1 compatibility;
6. `V15Coordinator` controlling SYNA/SYNR engine instances;
7. fork-only extension of `GraphArbExecutor` with post-route K/STS validation;
8. `V15RevenueRouter`.

Only after the accounting/risk layer compiles and passes invariant tests should the V13.1 route optimizer be wired into it.

## Bottom line

V15 should be understood as:

`V13.1 Edge Engine + Economic Ledger + Risk Ledger + Solvency Controller + Multi-Synthetic Coordinator`.

The gradient remains the edge initiator. The solvency layer decides whether the protocol is allowed to use that edge and how large the action may be. No own-token repricing can manufacture Economic HardNAV.
