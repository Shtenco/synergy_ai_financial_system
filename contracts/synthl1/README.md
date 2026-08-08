# SynthL1 V6 — supply-neutral edge-initiation engine

This module restores the V12/V13 monetary core and combines it with the strongest V5 MEV-capture and accounting controls.

## Exact recursive cycle

1. `ReserveGradientEngine.initializeGradient(source, destination, shift)` debits controlled synthetic `USDx` reserve from a 100% protocol-owned source pool.
2. The engine burns that USDx and mints **the exact same amount** directly into the destination pool.
3. `USDx.totalSupply()` is unchanged, but the cross-pool implied price geometry changes sharply.
4. An external searcher supplies its own quote-token principal and executes a route through `GraphArbExecutor`:
   - quote-B -> USDx in destination;
   - USDx -> quote-A in source;
   - quote-A -> ... -> quote-B through the external graph.
5. `GraphArbExecutor` computes actual realized base-token profit after every leg and charges an adaptive protocol tax only on that realized profit.
6. `ReserveGradientEngine.restoreGradient()` removes the searcher-returned USDx excess from source, burns it and remints it into destination. The same target gradient is restored with unchanged total supply.
7. Captured quote assets physically held by `MEVCaptureReinvestor` can be reinvested into a selected managed pool with `reinvestCapturedQuote()`.
8. The restored/repriced gradient can be exploited again. State is carried forward after every cycle.
9. The engine may later `closeGradient()` by reversing the original supply-neutral synthetic shift.

The system therefore implements:

`self-created reserve gradient -> repeated graph exploitation -> realized-profit MEV capture -> physical reinvestment -> restore/rotate gradient -> repeat`

It does **not** require waiting for a pre-existing profitable external cycle before initiating the gradient.

## Managed-pool invariants

A gradient pool must:

- use USDx as `token0`;
- be 100% LP-owned by the configured protocol liquidity owner;
- reject third-party LP additions through the liquidity-manager gate;
- set `gradientController` to `ReserveGradientEngine`;
- register as a protocol USDx pool in `SystemAccounting`;
- normally gate its USDx->quote closing direction through `GraphArbExecutor` so realized-profit tax cannot be bypassed.

`ReserveGradientEngine` can administratively move only controlled synthetic `token0`. It has no function that withdraws a pool's real `token1` reserve.

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

## Tests / reference models

- `simulation/synthl1/reserve_gradient_v6.py`
  - exact supply-neutral gradient;
  - repeated exploitation of one initiated edge;
  - exact synthetic-target restoration;
  - realized-profit tax and physical reinvestment;
  - conservation identity;
  - aligned-market negative control.

- `simulation/synthl1/stateful_gradient_graph_v13.py`
  - five quote assets;
  - complete external graph;
  - source/destination selection;
  - up to three external hops;
  - stateful, not independent-snapshot, repeated exploitation;
  - external graph built cycle-consistently so it has no standalone marginal arbitrage cycle;
  - protocol source/destination real-side value + captured tax is measured after every cycle.

Commands:

```bash
npm run sim:synthl1:gradient
npm run sim:synthl1:v13
npm run test:synthl1
```

## Existing repository outer layer

The root contracts remain useful rather than being duplicated:

- `GraphPolicy.sol` — timelocked policy/LNAV gate;
- `GraphTreasury.sol` — custody boundary;
- `OrderflowAuction.sol` — solver competition / access auction;
- `SecureFlashExecutor.sol` — flash/external graph execution;
- `TimelockedMultisig.sol` — governance hardening.

## Current evidence boundary

Historical V12/V13 material in the project showed the exact same supply-neutral burn/mint reserve-gradient design and stateful consolidated accounting. The new V6 reference tests reproduce that mechanism and add V5 realized-profit taxation/reinvestment. Live/fork recompilation of this new integrated branch is still required before deployment claims.
