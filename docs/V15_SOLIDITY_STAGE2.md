# SINERGY V15 — Solidity Stage 2

Status: **fork-only solvency overlay over frozen V13.1**.

Base/frozen V13.1 commit:

`385eaa2e6c811f1f29c504984484d9223b42b1b7`

No `contracts/synthl1/*` production source is modified by this stage.

## 1. Eight-contract V15 overlay

Exactly eight contracts are introduced under `contracts/v15/`:

1. `V15EconomicLedger` — unhaircut canonical Economic HardNAV;
2. `V15LiabilityRegistry` — generic externally enforceable liabilities;
3. `V15RiskOracle` — `min(canonical, TWAP, exit-depth)`, governance haircuts and finite stress scenarios;
4. `V15SolvencyController` — K/STS state machine with hysteresis;
5. `V15PostRouteGate` — fail-closed post-route K/STS assertion;
6. `V15AccountingAdapter` — one compatibility address for both frozen V13.1 executor and gradient engine;
7. `V15Coordinator` — solvency-gated operator over frozen V13.1 engine instances;
8. `V15RevenueRouter` — capital-flow-adjusted hard-profit distribution with loss carry-forward.

## 2. Economic/Risk accounting split

V13.1 `SystemAccounting` intentionally used haircut asset values in `consolidatedHardNAV1e18()`.
V15 does not reuse that value as Economic HardNAV.

`V15EconomicLedger` uses canonical unhaircut marks:

`EconomicHardNAV = canonical hard assets - canonical external liabilities`.

Own synthetics must be permanently excluded from the hard-asset set.

`V15RiskOracle + V15SolvencyController` separately compute conservative capacity:

`RiskPrice_i = min(Canonical_i, TWAP_i, Exit_i)`

`RiskAssets = sum RiskPrice_i * Haircut_i * Balance_i`

`K = RiskAssets / RiskLiabilities`

`STS = min_s StressAssets_s / StressLiabilities_s`.

Haircuts are owner/timelock policy parameters. Risk reporters may update TWAP/exit data but cannot raise a haircut themselves.

## 3. Dual-ABI compatibility constraint

Frozen `ReserveGradientEngine._requireManagedPool()` requires its `accounting` address to equal the frozen `GraphArbExecutor.navAccounting()` address.

Therefore V15 cannot use one accounting address for the engine and another for the executor.

`V15AccountingAdapter` is the single shared compatibility object and implements both frozen interfaces:

### Executor-facing

- `consolidatedHardNAV1e18()`
- `isHardAccount(token, account)`
- `isHardAsset(token)`
- `markValue1e18(token, amount)`
- `isProtocolUSDxAccount(account)`

### Gradient-engine-facing

- `externalCoverageBps()`
- `isProtocolUSDxAccount(account)`
- `isProtocolUSDxPoolAccount(account)`
- `protocolLiquidityOwner()`

The `USDx` names are retained solely for frozen ABI compatibility; V15 treats these mappings generically as own-synthetic protocol inventory/pool registries.

## 4. Atomic post-route K/STS gate

Frozen V13.1 executor already reads `consolidatedHardNAV1e18()` before and after a searcher route.

V15 uses this hook without modifying the executor:

`GraphArbExecutor -> V15AccountingAdapter -> V15PostRouteGate -> V15SolvencyController`.

`V15AccountingAdapter.consolidatedHardNAV1e18()` first calls `V15PostRouteGate.assertRouteState()`.

If post-route K/STS is unsafe, this view call reverts. Because it occurs inside the same V13.1 `executeCycle()` transaction, all pool swaps, the tax transfer and the route revert atomically.

If the state is solvent, the adapter returns the **Economic HardNAV** from `V15EconomicLedger`; the frozen executor then applies its existing post-trade HardNAV gain/oracle-turnover check.

Thus both conditions are required:

1. Economic HardNAV gain survives the V13.1 postcondition;
2. post-route K/STS survives the V15 solvency postcondition.

## 5. Solvency modes

Default controller state is RED.

Reference thresholds are policy defaults, not economic theorems:

- GREEN: K and STS >= 130%; bounded expansion permitted;
- YELLOW: K and STS >= 115%; smaller gradient envelope;
- ORANGE: K and STS >= 105%; no new risk expansion;
- RED: below the ORANGE floor, negative minimum HardNAV, stale/missing risk data, or no enabled stress scenario -> fail closed.

Mode recovery is hysteretic: repeated `pokeMode()` calls can only climb to a safer mode after buffered re-entry thresholds are met.

`V15Coordinator` permits new gradients and captured-quote reinvestment only when `canExpand()` is true. `restoreGradient()` and `closeGradient()` remain callable in every mode, including RED, so emergency recovery cannot be blocked by the expansion gate.

## 6. Revenue integrity

`V15RevenueRouter` measures:

`OperatingPnL = NAV_end - NAV_start - Contributions + Withdrawals`.

A period is settled once. Capital-flow reports are frozen after settlement.

Negative operating PnL is accumulated into `lossCarryforward1e18`. Later positive PnL must first recover this carry-forward; only value above prior unrecovered loss can become distributable.

This prevents a loss period from being closed and a later recovery from being relabeled as fresh profit.

Every distribution must satisfy the settled budget and `distributionAllowed()` both before and after the token transfer; an unsafe post-transfer state reverts atomically.

## 7. Intended multi-synthetic deployment

Frozen V13.1 has one `gradientEngine` pointer per `GraphArbExecutor`, and `MEVCaptureReinvestor` has one controller.

Therefore the clean V15 deployment for two independent synthetic families is:

- one frozen V13.1 `ReserveGradientEngine` instance per synthetic family;
- one frozen V13.1 `GraphArbExecutor` per synthetic family;
- one capture/reinvestor per family if controller ownership is required;
- all families share the same V15 EconomicLedger, LiabilityRegistry, RiskOracle and SolvencyController through their V15 accounting adapters/coordinator.

The V15 coordinator may allowlist both engine instances and choose which family/pair is permitted by the current risk state.

## 8. Test gates

### Executed locally

`npm run test:v15` equivalent local discovery currently covers:

- 12 mathematical/solvency reference tests;
- 9 static Solidity-surface/compatibility tests;
- total: **21/21 PASS**.

The static suite asserts, among other things:

- exactly eight V15 overlay contracts;
- EconomicLedger contains no haircut accounting;
- own-synthetic permanent exclusion exists;
- RiskOracle reporter/haircut authority is separated;
- AccountingAdapter exposes both frozen V13.1 ABIs;
- post-route gate is fail closed;
- restore/close are not expansion-gated;
- RevenueRouter has single settlement and loss carry-forward;
- V15 does not import V13.1 contract logic directly (except reusing `SafeTransferLib`).

### Implemented, pending compiler/EVM execution

`test/v15_overlay.js`:

- canonical HardNAV vs risk K/STS separation;
- no double counting after hard-account disable/re-enable;
- liability shock -> fail-closed adapter;
- contribution-adjusted PnL;
- hard-profit distribution budget;
- loss carry-forward.

`test/v15_v13_integration.js`:

- V15 adapter/controller wired into actual frozen V13.1 GraphPool / ReserveGradientEngine / GraphArbExecutor;
- known latent-basis route passes when Economic HardNAV and post-route K/STS both pass;
- same Economic-HardNAV-positive route is forced to revert when a conservative risk haircut makes post-route K/STS cross the GREEN floor.

The current local sandbox has no `solc` or `forge`. Attempting to install `solc@0.8.26` from the sandbox npm registry returns 404. Therefore no fresh Solidity compiler/EVM result is claimed locally.

`.github/workflows/v15-overlay-ci.yml` runs:

`npm ci -> hardhat compile -> V15 Python/static tests -> V15 EVM tests -> frozen V13.1 EVM guards`.

## 9. Stage boundary

The 10-internal-pool / 50-external-pool optimizer is intentionally **not** part of Stage 2.

Stage 2 is complete only when the eight-contract solvency overlay compiles and its EVM integration tests pass. Only after that gate should the full graph optimizer be connected.
