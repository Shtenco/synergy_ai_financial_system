# SynthL1 V13.1 — Supply-Neutral Edge Initiation / HardNAV Audit

## Executive verdict

The intended V12/V13 mechanism is preserved:

`source synthetic burn -> equal destination synthetic mint -> self-created reserve gradient -> external searcher graph route -> realized-profit tax -> exact synthetic restore -> captured-quote reinvestment -> close/rotate -> repeat`

The protocol does **not** require a profitable external arbitrage to exist before it creates the gradient.

However, V13.1 now makes the economic acceptance condition exact:

`ProtocolHardNAV_after - ProtocolHardNAV_before >= MinProtocolGain`

This is checked **after the actual route executes but inside the same transaction**. A self-created gradient may therefore initiate an edge surface first; if the resulting external transfer is not accretive at fresh oracle marks, the whole searcher transaction reverts.

The strongest corrected result is not “an aligned market creates free value.” It does not. The useful regime is:

> a small cycle-consistent external venue basis is below the standalone fee hurdle and therefore not independently arbitrageable; the supply-neutral reserve gradient makes a combined internal/external route executable; realized-profit capture transfers most of that newly executable basis into protocol hard assets.

That is the mathematically defensible form of the edge-initiator thesis.

---

## 1. Production core

The old CORE-buyback/burn monetary core is not the edge initiator. Runtime edge initiation is handled by `ReserveGradientEngine`.

Production contracts remain:

1. `CORE`
2. `USDx`
3. `HardReserveVault`
4. `PriceOracleHub`
5. `MEVCaptureReinvestor`
6. `GraphPool`
7. `GraphArbExecutor`
8. `BridgeVault`
9. `SystemAccounting`
10. `ReserveGradientEngine`

`SafeTransferLib` is a library.

The existing repository outer layer remains useful and separate:

- `GraphPolicy` — timelocked policy/LNAV gate;
- `GraphTreasury` — custody boundary;
- `OrderflowAuction` — solver competition;
- `SecureFlashExecutor` — independent external flash/graph opportunities;
- `TimelockedMultisig` — governance hardening.

---

## 2. Supply-neutral reserve-gradient primitive

For two managed pools sharing controlled synthetic reserve `S`:

`S_source' = S_source - dS`

`S_destination' = S_destination + dS`

and therefore:

`Delta TotalSyntheticSupply = 0`.

For equal initial synthetic reserves `S`, the synthetic-side reserve ratio becomes:

`Gamma = (S + dS) / (S - dS)`.

Examples:

| dS / S | Ratio | Synthetic-side wedge |
|---:|---:|---:|
| 10% | 1.2222x | 22.22% |
| 20% | 1.5000x | 50.00% |
| 40% | 2.3333x | 133.33% |
| 50% | 3.0000x | 200.00% |
| 80% | 9.0000x | 800.00% |

A large wedge is easy to create. **Large wedge is not the objective.** The optimizer must maximize actual post-route HardNAV improvement.

---

## 3. Accounting correction discovered in V13 audit

An earlier V13 stateful model used two different valuation bases:

- external pools were generated from a non-flat `market_multiplier` vector;
- protocol/external balances were still marked using fixed `FAIR_USD`.

That created a false positive.

For the old example vector:

- USDT = 1.000
- USDC = 0.995
- DAI = 1.005
- WPOL = 1.020
- WETH = 0.980

using fixed `FAIR_USD` marks produced approximately:

- protocol delta: `+1.275173 USD`
- external LP delta: `-1.387181 USD`
- solver reward: `+0.112008 USD`
- conservation: approximately zero.

When **the same market vector** is used to mark protocol, external LP and solver balances, the identical state path becomes approximately:

- protocol delta: `-0.364195 USD`
- external LP delta: `+0.254367 USD`
- solver reward: `+0.109827 USD`
- conservation: approximately zero.

Therefore the old `+1.28 USD` result and the wider-dispersion positive result are rejected and are not evidence for V13.1.

The corrected rule is simple:

> one oracle/mark vector must value every hard asset on both sides of the conservation identity.

Venue prices are allowed to differ from that mark vector; that difference is the externally available basis being tested.

---

## 4. Negative controls

### 4.1 Fully aligned market

If oracle marks and external venue prices are aligned, a reserve gradient can still make a **solver-profitable** route appear mechanically.

But after measuring protocol hard assets at the same marks, that route is self-funded. V13.1 finds no HardNAV-positive rotation and the on-chain `GraphArbExecutor` HardNAV guard rejects it.

### 4.2 Non-flat vector, same marks and venue prices

Even if USDT/USDC/DAI/WPOL/WETH have different absolute marks, using the same non-flat vector for both external venues and accounting again produces no HardNAV-positive rotation.

This is the regression test for the old V13 valuation bug.

### 4.3 External-only cycle control

The external graph is generated from one internally consistent venue-price vector. Marginal products around any external-only simple cycle are <= 1 before costs and < 1 after the 0.30% pool fees.

Thus the positive V13.1 test does not insert a free external cyclic-arbitrage loop.

---

## 5. The useful regime: activate a sub-threshold latent basis

Corrected reference marks:

- USDT: 1.000 x base mark
- USDC: 1.000 x base mark
- DAI: 1.000 x base mark
- WPOL: 1.000 x base mark
- WETH: 1.000 x base mark

Cycle-consistent external venue multipliers:

- USDT: `1.000`
- USDC: `0.998`
- DAI: `1.002`
- WPOL: `1.003`
- WETH: `0.997`

The maximum pair displacement is only about 0.6%.

The combined internal/external route has multiple 0.30% fee legs, so the corrected baseline scan finds:

`profitable no-gradient route = NONE`.

The external complete graph also has no standalone profitable marginal cycle.

After a supply-neutral gradient is introduced and source/destination/shift/principal/path are optimized against **post-trade HardNAV**, previously sub-threshold basis becomes executable.

Independent deterministic regression with:

- 5 internal managed pools;
- complete external graph;
- external side value = 100,000 USD per token side;
- 99% realized-profit tax ceiling;
- absolute solver reward floor = 0.001 USD;
- shift candidates = 5/10/15/20/25/30/40/50 synthetic units;
- state carried forward after every route;
- gradient closed/rotated before the next optimizer pass;

produced four HardNAV-positive rotations:

| # | Source | Destination | Shift | Protocol HardNAV increment |
|---:|---|---|---:|---:|
| 1 | WPOL | WETH | 50 | +0.117404 USD |
| 2 | DAI | WETH | 50 | +0.056396 USD |
| 3 | WPOL | USDC | 50 | +0.019019 USD |
| 4 | DAI | USDC | 50 | +0.011868 USD |

Final cumulative result:

- protocol HardNAV: **+0.204687 USD**
- external LP HardNAV: **-0.221851 USD**
- solver retained reward: **+0.017164 USD**
- maximum conservation error: approximately `3.1e-11 USD`

Conservation closes:

`Delta Protocol + Delta ExternalLP + SolverReward ~= 0`.

This is the key corrected evidence:

> the gradient is an edge initiator because it can make a small latent cross-venue basis executable even when that basis cannot clear the fee hurdle without the gradient.

It is not evidence that a perfectly aligned external market can be harvested for positive hard value.

---

## 6. Gradient size is an optimizer variable, not a target

A larger gradient creates a larger synthetic price discontinuity, but it also changes how much protocol quote inventory the route gives up before external settlement.

In the two-asset sensitivity model, the approximate minimum external A/B basis that admitted a HardNAV-positive route increased with a fixed larger shift:

| Shift / synthetic reserve | Approx. minimum basis |
|---:|---:|
| 10% | 0.40% |
| 20% | 0.50% |
| 30% | 0.60% |
| 40% | 0.71% |
| 50% | 0.81% |
| 60% | 0.91% |
| 70% | 1.01% |

So the controller objective must be:

`argmax(source, destination, dS, principal, route) Delta ProtocolHardNAV`

not:

`argmax dS` or `argmax wedge`.

The optimizer should stop when no candidate survives the post-trade HardNAV gate.

---

## 7. On-chain HardNAV acceptance gate

`GraphArbExecutor` now supports an optional atomic `SystemAccounting` guard.

Sequence:

1. snapshot `HardNAV_before`;
2. receive searcher principal;
3. execute the full internal/external route;
4. compute **realized** base-token profit;
5. transfer protocol tax physically to `MEVCaptureReinvestor`;
6. read `HardNAV_after` from `SystemAccounting` using fresh `PriceOracleHub` marks;
7. require:

`HardNAV_after - HardNAV_before >= minProtocolNavGain1e18`;

8. only then return searcher principal + retained reward.

If the condition fails, the entire route, tax transfer and pool state changes revert atomically.

The transient `GraphArbExecutor` is forbidden from being registered as a protocol hard-asset account or protocol USDx account. Otherwise solver principal could contaminate the NAV snapshot.

Each route leg now also requires:

- exact full-output chaining;
- exact input-token consumption;
- allowlisted target/spender;
- configured base-token gate;
- deadline;
- minimum output;
- minimum retained solver profit.

---

## 8. Managed-pool anti-bypass / anti-grief rules

A V13 gradient pool is accepted by `ReserveGradientEngine` only if:

- token0 is the controlled synthetic;
- 100% of LP shares belong to `protocolLiquidityOwner`;
- third-party LP additions are blocked;
- `gradientController` is the engine;
- **both swap directions are executor-only**;
- source and destination use the same non-zero `GraphArbExecutor`;
- the pool is registered correctly in `SystemAccounting`;
- the capture vault is registered correctly;
- external USDx coverage floor is satisfied.

The all-direction executor gate closes a grief vector in which a third party could directly buy synthetic from the destination pool between searcher execution and `restoreGradient()` and destroy the exact restoration invariant.

External DEX venues are not gated by this rule.

---

## 9. EVM tests

### `test/synthl1_reserve_gradient_v6.js`

Mechanical supply-neutral path:

`bootstrap -> gradient -> solver cycle -> realized-profit tax -> restore -> captured quote reinvest -> close`

Asserts:

- unchanged synthetic total supply across gradient operations;
- exact target reserve restoration;
- physical captured-token balance;
- managed executor-only swaps;
- final synthetic reserve baseline restored.

### `test/synthl1_v13_nav_guard.js`

Two economic cases are encoded:

**Negative case**

- external A/B = 10,000 / 10,000;
- 40% gradient creates a raw solver-profit route;
- protocol HardNAV would decline;
- `executeCycle()` must revert;
- pool/NAV state is unchanged by the reverted transaction.

**Positive latent-basis case**

- oracle marks A = B = 1 USD;
- external venue = 10,000 A / 10,100 B;
- 40% gradient;
- principal = 39.8 B;
- 99% realized-profit tax;
- solver reward floor = 0.001 B;
- minimum required protocol NAV gain = 0.05 USD.

The matching exact-number reference calculation is approximately:

- gross searcher arbitrage profit: `0.109498 B`
- protocol tax: `0.108403 B`
- solver retained reward: `0.001095 B`
- protocol HardNAV delta: **+0.117919 USD**
- external LP delta: `-0.119014 USD`
- conservation error: approximately zero.

The EVM test requires the positive case to pass and the aligned case to revert.

---

## 10. Evidence boundary

### Executed locally in the available Python runtime

- corrected mark-to-market regression: PASS;
- aligned negative control: PASS;
- non-flat mark==venue valuation regression: PASS;
- sub-threshold no-gradient control: PASS;
- stateful gradient rotation: PASS;
- conservation identity: PASS.

### Implemented but not yet freshly executed by a Solidity compiler in the current environment

- Solidity V13.1 contracts;
- EVM HardNAV guard tests;
- managed all-direction executor gate tests.

The GitHub Actions job is currently failing before checkout/steps start (`steps = null`), so that infrastructure failure is not a Solidity compiler result. A fresh compiler/EVM/fork run remains a mandatory deployment gate.

---

## Bottom line

V13.1 is **not** “wait for an external edge.”

Its runtime logic is:

`SELF-CREATED SUPPLY-NEUTRAL GRADIENT`

`-> SEARCH CURRENT INTERNAL + EXTERNAL GRAPH`

`-> EXECUTE ONLY IF ACTUAL POST-TRADE HARDNAV INCREASES`

`-> REALIZED-PROFIT MEV CAPTURE`

`-> RESTORE / REINVEST / ROTATE`

`-> REPEAT UNTIL NO HARDNAV-POSITIVE ROUTE EXISTS`.

The gradient itself creates the executable discontinuity. External price geometry supplies the hard-value counterparty. The corrected tests show that the system can activate **sub-threshold latent basis** that is not independently profitable before the gradient, while rejecting self-funded aligned-market cycles.
