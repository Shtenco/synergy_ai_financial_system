# SynthL1 V13.1 — supply-neutral edge-initiation engine

This module restores the V12/V13 monetary core and combines it with V5 realized-profit MEV capture plus a post-trade consolidated HardNAV gate.

## Exact recursive cycle

1. `ReserveGradientEngine.initializeGradient(source, destination, shift)` moves controlled synthetic reserve from a 100% protocol-owned source pool to a destination pool by burn + equal mint.
2. `USDx.totalSupply()` is unchanged, but internal cross-pool price geometry changes.
3. A searcher supplies its own base-token principal and executes through `GraphArbExecutor`:
   - quote-B -> USDx in destination;
   - USDx -> quote-A in source;
   - quote-A -> ... -> quote-B through external venues.
4. `GraphArbExecutor` measures actual returned base-token balance and taxes only realized route profit.
5. If enabled, the executor reads `SystemAccounting.consolidatedHardNAV1e18()` before and after the actual route and requires a configured positive minimum gain. A self-funded aligned-market edge therefore reverts atomically.
6. `ReserveGradientEngine.restoreGradient()` supply-neutrally returns source/destination synthetic reserves to their configured target.
7. Physically captured quote assets in `MEVCaptureReinvestor` can be reinvested into managed pools.
8. The gradient can be closed and rotated to the next source/destination selected by the optimizer. State is carried forward after every route.

Runtime objective:

`argmax(source, destination, shift, principal, route) Delta ProtocolHardNAV`

not `argmax wedge`.

The system does **not** wait for a pre-existing profitable external arbitrage. The corrected V13.1 model shows a useful regime where a supply-neutral gradient makes a small cross-venue basis executable even though the same basis is below the no-gradient multi-leg fee hurdle.

## Corrected economic evidence

The old V13 result that valued external venues with one multiplier vector but protocol assets with fixed `FAIR_USD` was rejected as a mark-to-market artifact.

Corrected tests use one oracle mark vector for protocol, external LP and solver valuation, while external venue prices may differ from those marks.

Reference latent-basis scenario:

- true mark multipliers: all `1.000`;
- external venue multipliers: USDT `1.000`, USDC `0.998`, DAI `1.002`, WPOL `1.003`, WETH `0.997`;
- complete external graph is cycle-consistent;
- no profitable no-gradient route is found;
- 99% realized-profit tax ceiling;
- 0.001 USD solver reward floor;
- gradient closed/rotated after every accepted route.

Deterministic stateful regression:

- 4 HardNAV-positive rotations;
- cumulative protocol HardNAV: **+0.204687 USD**;
- external LP delta: **-0.221851 USD**;
- solver reward: **+0.017164 USD**;
- conservation error: approximately zero.

Aligned mark==venue markets produce zero accepted HardNAV-positive rotations.

See `docs/SYNTHL1_V6_RESERVE_GRADIENT_AUDIT.md` for the full audit.

## Managed-pool invariants

A gradient pool must:

- use controlled synthetic `USDx` as `token0`;
- be 100% LP-owned by `protocolLiquidityOwner`;
- reject third-party LP additions;
- set `gradientController` to `ReserveGradientEngine`;
- register as a protocol USDx pool in `SystemAccounting`;
- use a non-zero `GraphArbExecutor`;
- gate **both** swap directions through that executor;
- share the same executor with the paired gradient pool.

The all-direction executor gate prevents direct-swap grief of the exact post-route restoration invariant and prevents realized-profit-tax bypass.

`ReserveGradientEngine` can move only controlled synthetic `token0`. It has no administrative function that withdraws real pool `token1` reserves.

## GraphArbExecutor invariants

- searcher funds its own principal;
- allowlisted target/spender pairs;
- exact full-output chaining between legs;
- exact input-token consumption per leg;
- deadline and per-leg minimum output;
- maximum 99% tax on **realized profit**;
- absolute solver reward floor;
- optional post-trade `SystemAccounting` HardNAV minimum-gain gate;
- transient executor must not be registered as a protocol hard-asset or protocol USDx account.

## Ten production contracts

1. `CORE.sol`
2. `USDx.sol`
3. `HardReserveVault.sol`
4. `PriceOracleHub.sol`
5. `MEVCaptureReinvestor.sol`
6. `GraphPool.sol`
7. `GraphArbExecutor.sol`
8. `BridgeVault.sol`
9. `SystemAccounting.sol`
10. `ReserveGradientEngine.sol`

`SafeTransferLib.sol` is a library, not an eleventh production contract.

## Tests / models

```bash
npm run sim:synthl1:gradient
npm run sim:synthl1:v13
npm run test:synthl1
npm run test:synthl1:evm
```

`test/synthl1_v13_nav_guard.js` contains both mandatory economic EVM cases:

- fair external market: raw solver edge exists but protocol HardNAV falls -> revert;
- latent external basis: gradient opens route and protocol HardNAV rises -> execute.

## Evidence boundary

Corrected Python economic/invariant regressions were executed locally and pass. The fresh Solidity compile/EVM suite is committed but has not yet produced compiler output because the current GitHub Actions runner fails before checkout (`steps = null`) and the local sandbox does not have the pinned Solidity toolchain. A fresh compile/EVM/fork run remains mandatory before deployment.
