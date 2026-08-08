# SynthL1 V5 repository integration review

## Verdict

The existing `ai_financial_system` repository is a useful host for SynthL1 V5 because it already separates policy, custody, solver competition, execution and simulation. The new recursive monetary engine is therefore added as a module instead of replacing the current root contracts.

## Reused as outer infrastructure

### `GraphPolicy.sol`
Useful as a timelocked policy gate. It already requires `expectedLnav > baselineLnav` before a queued action can be consumed. For SynthL1 it should govern changes to pulse limits, allowed pools, oracle/risk bounds and activation of external execution.

### `GraphTreasury.sol`
Useful as an asset-custody boundary. SynthL1's monetary contracts should not bypass custody controls for hard assets.

### `OrderflowAuction.sol`
Useful for solver competition. The recursive internal wedge may be exposed to external searchers, while independent external graph opportunities can also be auctioned. Auction revenue must remain separate from recycled USDx turnover in accounting.

### `SecureFlashExecutor.sol`
Useful for external graph opportunities that benefit from flash liquidity. Its real-balance profit check is aligned with the SynthL1 rule that an execution must not manufacture PnL through internal marks.

### `TimelockedMultisig.sol`
Useful for production governance and emergency administration.

## Retained as research / legacy context

The older growth-cycle, internal market and MEV simulations remain valuable as counterfactual experiments, but their metrics must not be silently mixed with SynthL1 hard NAV.

In particular, the new module does not treat the following as external profit:

- CORE market-cap growth;
- internal price changes caused by QE;
- cumulative recycled USDx fee turnover;
- protocol-owned LP markups without an external settlement value;
- repeated movement of the same asset among protocol accounts.

## New module layout

```text
contracts/synthl1/
  CORE.sol
  USDx.sol
  HardReserveVault.sol
  PriceOracleHub.sol
  MEVCaptureReinvestor.sol
  GraphPool.sol
  GraphArbExecutor.sol
  BridgeVault.sol
  SystemAccounting.sol
  RecursiveElasticEngine.sol
  SafeTransferLib.sol
  README.md

simulation/synthl1/
  recursive_qe_mev.py

solver/synthl1/
  market-graph.example.json

tests/
  test_synthl1_recursive_qe_mev.py
```

## Exact economic loop

```text
initial QE USDx
  -> buy CORE in selected internal GraphPool
  -> burn received CORE
  -> create price gradient across the graph
  -> external searcher closes a profitable route with its own principal
  -> configured USDx fee is physically transferred to MEVCaptureReinvestor
  -> RecursiveElasticEngine pulls only that real captured balance
  -> next CORE buyback + burn pulse
  -> repeat
```

Only the first pulse mints fresh USDx. The strict reinvestment relation is:

`Pulse[n+1] = CapturedUSDxFee[n]`

unless a separately identified external revenue stream is added.

## Accounting rule

`SystemAccounting` must be the economic boundary:

`Hard NAV = hard external assets - external USDx liabilities`

Protocol-held USDx can be cancelled against supply only when the registered account is fully protocol-owned. A pool with public LP ownership cannot have its entire USDx reserve treated as protocol treasury stock.

## Solver graph

`solver/synthl1/market-graph.example.json` preserves the 15-market Polygon discovery concept. Aggregator output is only route discovery. Execution remains subject to target allowlisting, minimum outputs and actual token balance deltas.

## Recommended control wiring

Production wiring should be layered rather than circular:

```text
TimelockedMultisig / Guardian
        |
    GraphPolicy
        |
 policy-controlled operator
        |
RecursiveElasticEngine ---- MEVCaptureReinvestor
        |                         ^
     GraphPool[] -----------------|
        ^
GraphArbExecutor <--- external searchers / OrderflowAuction
        ^
SecureFlashExecutor for independent external opportunities
```

`GraphPolicy` and the auction are intentionally not imported directly by `RecursiveElasticEngine`; this avoids hard coupling and keeps policy upgrades separate from the monetary state machine.

## Test interpretation

The focused Python tests assert:

1. an initializing pulse creates a large graph wedge;
2. a positive searcher incentive remains;
3. the next pulse equals the physically captured fee rather than a new mint;
4. the closed recursive loop does not create hard NAV by itself;
5. an external top-up can prevent pulse decay, but is explicitly external value.

This distinction is central: SynthL1 V5 is a recursive liquidity/MEV recycling engine. A growing hard-NAV loop additionally requires independent external revenue.

## Production blockers

Before mainnet or L1 launch:

- compile all SynthL1 contracts with the repository Hardhat toolchain;
- add Solidity unit tests for role wiring and pool accounting;
- run fork tests for every external venue adapter;
- replace the bridge relayer MVP with validator/light-client verification;
- use signed/multi-source oracle updates;
- define protocol-owned versus public LP accounting precisely;
- audit the directional fee mechanism and searcher incentive bounds;
- run a full external smart-contract audit.
