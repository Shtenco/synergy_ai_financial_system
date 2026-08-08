# SynthL1 V5 module

This directory contains the recursive QE, buyback/burn, graph-routing and fee-reinvestment prototype.

## Cycle

1. `RecursiveElasticEngine.initializeQE()` creates the initial USDx pulse.
2. USDx is swapped for CORE in a selected protocol pool.
3. Received CORE is burned.
4. The price difference across connected `GraphPool` instances creates an arbitrage opportunity.
5. External searchers may execute profitable routes through `GraphArbExecutor` using their own principal.
6. Configured directional pool fees are transferred to `MEVCaptureReinvestor`.
7. `reinvestCaptured()` can reuse only the USDx physically held by that contract.
8. The reused USDx performs the next CORE buyback/burn pulse.
9. The process repeats without a new USDx mint in reinvestment steps.

`Pulse[n+1] = capturedFee[n]`

unless a separately accounted external revenue source is added.

## Production contracts

1. `CORE.sol`
2. `USDx.sol`
3. `HardReserveVault.sol`
4. `PriceOracleHub.sol`
5. `MEVCaptureReinvestor.sol`
6. `GraphPool.sol`
7. `GraphArbExecutor.sol`
8. `BridgeVault.sol`
9. `SystemAccounting.sol`
10. `RecursiveElasticEngine.sol`

`SafeTransferLib.sol` is a library.

## Fit with the existing repository

The existing root-level contracts remain the outer policy and security layer:

- `GraphPolicy.sol` can gate parameter and execution changes.
- `GraphTreasury.sol` remains a custody boundary.
- `OrderflowAuction.sol` can coordinate external solver participation.
- `SecureFlashExecutor.sol` remains useful for independent external graph opportunities.
- `TimelockedMultisig.sol` remains useful for governance hardening.

The SynthL1 contracts keep only `owner` and `operator` roles so these existing modules can control them without creating compile-time coupling.

## Accounting

`SystemAccounting` separates hard external assets, external USDx liabilities, protocol-held USDx and recycled fee turnover. Reusing the same fee balance multiple times is turnover, not new hard profit.

Status: architecture and economic-model stage. Mainnet use requires compiler tests, contract tests, fork tests, oracle/bridge hardening and external review.
