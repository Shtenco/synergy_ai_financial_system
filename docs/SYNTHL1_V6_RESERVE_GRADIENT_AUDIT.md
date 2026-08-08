# SynthL1 V6 — Supply-Neutral Reserve Gradient Audit

## Executive result

V6 restores the intended V12/V13 edge-initiation mechanism and removes the V5.2 CORE-buyback/burn monetary core.

Runtime loop:

`source synthetic burn -> equal destination synthetic mint -> self-created graph gradient -> external searcher route -> realized-profit tax -> exact synthetic target restore -> physical tax reinvestment -> repeat`

The synthetic reserve move is supply-neutral. `USDx.totalSupply()` must be identical before and after:

- initial gradient creation;
- every post-searcher gradient restore;
- final gradient close.

## 1. Production core

`RecursiveElasticEngine.sol` was removed and replaced with `ReserveGradientEngine.sol`.

The production set remains exactly ten contracts:

1. CORE
2. USDx
3. HardReserveVault
4. PriceOracleHub
5. MEVCaptureReinvestor
6. GraphPool
7. GraphArbExecutor
8. BridgeVault
9. SystemAccounting
10. ReserveGradientEngine

SafeTransferLib is a library.

## 2. Managed reserve primitive

For source/destination pools with controlled synthetic reserve S:

- source: `S_source' = S_source - dS`
- destination: `S_destination' = S_destination + dS`
- total synthetic supply: unchanged

For equal initial synthetic reserves S and equal-value quote reserves, the initial source/destination price ratio is:

`ratio = (S + dS) / (S - dS)`

Examples:

- dS/S = 10% -> 1.2222x -> 22.22% wedge
- 20% -> 1.5000x -> 50.00%
- 40% -> 2.3333x -> 133.33%
- 50% -> 3.0000x -> 200.00%
- 80% -> 9.0000x -> 800.00%
- 90% -> 19.0000x -> 1800.00%

Unlike the discarded V5 CORE-burn pulse, the edge surface can be restored without destroying CORE inventory.

## 3. Exact repeated-exploitation control

Reference geometry:

- source internal pool: 100 SYN / 100 A
- destination internal pool: 100 SYN / 100 B
- initial supply-neutral shift: 40 SYN
- target reserves after initiation: 60 SYN source / 140 SYN destination
- external A/B pool: 10,000 / 10,000
- internal + external swap fee: 0.30%
- realized-profit tax ceiling: 99%
- absolute solver reward floor: 0.001 B
- captured B reinvested into destination after every exploitation

Result:

- one initiated gradient remained exploitable for 6 stateful cycles;
- after every cycle source/destination synthetic reserves returned exactly to 60 / 140;
- cumulative realized-profit tax captured: ~9.738606 B;
- cumulative solver reward: ~0.100532 B;
- final protocol real-side delta: ~-0.368250 B;
- external LP delta: ~+0.267717 B;
- conservation error: approximately zero.

This aligned-market case is deliberately a negative consolidated-value control. It proves that repeated exploitation and tax recycling do not depend on independent snapshot reuse.

## 4. Gradient-size sweep

With the same aligned external pool and 99% realized-profit tax:

| Shift | Initial wedge | Stateful exploitations | Captured tax | Solver reward | Protocol real-side delta |
|---:|---:|---:|---:|---:|---:|
| 10% | 22.22% | 5 | 0.5797 | 0.0086 | -0.0447 |
| 20% | 50.00% | 6 | 2.3994 | 0.0271 | -0.1212 |
| 30% | 85.71% | 6 | 5.4395 | 0.0574 | -0.2284 |
| 40% | 133.33% | 6 | 9.7386 | 0.1005 | -0.3682 |
| 50% | 200.00% | 7 | 15.4081 | 0.1585 | -0.5457 |
| 60% | 300.00% | 7 | 22.6531 | 0.2315 | -0.7564 |
| 70% | 466.67% | 7 | 31.8551 | 0.3244 | -1.0074 |
| 80% | 800.00% | 7 | 43.7702 | 0.4446 | -1.3064 |
| 90% | 1800.00% | 7 | 60.2882 | 0.6115 | -1.6733 |

The purpose of the sweep is not to maximize the wedge blindly. It establishes the relationship between initiated gradient size, MEV-tax turnover and real-side balance-sheet movement.

## 5. V13-style five-asset stateful graph

Liquid assets:

- USDT
- USDC
- DAI
- WPOL
- WETH

The external graph is complete. Every external pair price is derived from one common vector of market multipliers, so products around an external-only marginal cycle equal one before fees and are below one after fees.

For 0.30% fee, the best two-edge infinitesimal external-only cycle upper bound is approximately:

`0.997^2 = 0.994009x < 1`

Therefore the test does not insert a standalone profitable external cycle.

### Aligned graph

All market multipliers = 1.0.

- selected initiated pair: WPOL -> WETH
- stateful exploitations: 6
- cumulative captured tax: ~9.772578 USD
- protocol real-side delta: ~-0.339367 USD
- external LP delta: ~+0.238570 USD
- solver cumulative reward: ~0.100797 USD
- conservation error: ~1.9e-11 USD

### Cycle-consistent graph with market multipliers within +/-2%

Multipliers:

- USDT 1.000
- USDC 0.995
- DAI 1.005
- WPOL 1.020
- WETH 0.980

The external graph still has no standalone marginal arbitrage cycle because all pair prices are generated from the same multiplier vector.

After the protocol self-initiates the synthetic reserve gradient:

- selected initiated pair: WPOL -> WETH
- stateful exploitations: 7
- cumulative captured realized-profit tax: ~10.893924 USD
- protocol real-side delta: **+1.281041 USD**
- external LP delta: ~-1.394148 USD
- solver cumulative reward: ~0.113107 USD
- conservation error: ~-7.1e-12 USD

This is the useful V13 distinction: the external graph itself need not contain a profitable closed cycle. The self-created internal reserve geometry can open a combined internal/external route that transfers value through the graph and can be repeatedly restored/exploited.

### Wider consistent multiplier dispersion

With multipliers USDT 1.00 / USDC 0.99 / DAI 1.01 / WPOL 1.05 / WETH 0.95:

- stateful exploitations: 6
- cumulative tax: ~12.774395 USD
- protocol real-side delta: **+4.003169 USD**
- external LP delta: ~-4.134090 USD
- solver reward: ~0.130922 USD
- conservation error: ~1e-12 USD

These are deterministic model scenarios, not a live-market yield claim.

## 6. Solidity hardening added during the audit

### GraphPool

- managed token0 reserve controller;
- controller cannot administratively withdraw token1;
- `gradientDebitToken0()`;
- `syncManagedReserves()`;
- LP-provider restriction / anti-dust-grief gate;
- executor-only managed closing direction.

### ReserveGradientEngine

- exact total-supply invariant on every synthetic shift;
- source/destination 100% protocol LP requirement;
- exact target reserve restoration after every searcher route;
- configurable maximum gradient shift;
- protocol coverage gate;
- physical captured-quote reinvestment;
- exact reverse shift on gradient close.

### GraphArbExecutor

- realized-profit tax, max 99%;
- absolute solver reward floor;
- actual balance-delta settlement;
- multi-asset allowed settlement-token gates per target;
- allowlisted venue/spender pairs.

### USDx

A deployment deadlock was found and fixed. Managed LPs need synthetic inventory before the runtime engine can be installed. V6 adds `bootstrapMint()` only before any engine is set; installing the engine permanently closes bootstrap minting.

### PriceOracleHub / SystemAccounting

The previous single-hard-token accounting was insufficient for V13. V6 supports multiple real assets with:

- 1e18 USD price per token;
- per-asset haircut;
- explicit protocol account lists;
- protocol-owned USDx inventory exclusion only under 100% LP ownership;
- consolidated hard NAV = haircut real assets - external USDx liabilities.

Third-party external pools must never be registered as protocol hard accounts.

## 7. EVM integration test

`test/synthl1_reserve_gradient_v6.js` wires the full local atomic sequence:

`bootstrap -> 40% supply-neutral gradient -> solver B->USDx->A->external A/B->B -> 99% realized-profit tax -> restore gradient -> reinvest captured B -> close gradient`

Assertions include:

- total USDx supply unchanged through gradient operations;
- exact 60/140 target restoration after searcher exploitation;
- physical tax balance in MEVCaptureReinvestor;
- captured B reinvests into destination reserve;
- final synthetic reserves return to 100/100;
- third-party external pool is excluded from SystemAccounting.

The test is now in CI, but a fresh EVM compiler result depends on the GitHub runner actually starting.

## 8. Evidence boundary

Historical project evidence already established:

- V12 pinned Polygon fork: self-created gradient without external shock;
- V11 pinned Polygon fork: atomic QE -> external graph -> exact buyback -> QT;
- V13 smoke: multi-source/multi-destination managed gradient with a positive consolidated candidate.

V6 integrates the same reserve-gradient principle with newer realized-profit MEV taxation, physical reinvestment and stricter accounting. The new deterministic simulations are reproducible. A fresh live/fork V6 run remains a separate gate.
