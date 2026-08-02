# SYNERGY V8 — Stateful 10×10 QE/QT Graph Supercycle

## Status

V8 has been restored as normal version-controlled source files. The damaged
`.github/stateful_supercycle_v8_bundle.b64` packaging path is no longer part of
the acceptance process.

The current research branch contains:

- `contracts/supercycle/StatefulSupercycleV8.sol` — stateful acceptance and
  topology layer;
- `contracts/fork/SynergyAtomicQeQtCycleV11.sol` — atomic managed QE → external
  graph → exact buyback → QT execution primitive reused by V8;
- `test/stateful_supercycle_v8_10x10_polygon_fork.js` — pinned Polygon fork
  integration test;
- `simulation/stateful_supercycle_v8_10x10.py` — 100-cycle integer accounting
  shadow;
- `scripts/validate_stateful_supercycle_v8_10x10.py` — independent evidence
  validator;
- `.github/workflows/stateful-supercycle-v8.yml` — direct-source CI workflow.

This is a research acceptance harness, not production deployment code and not a
guarantee of recurring mainnet profit.

## 10 internal permissioned edges

Five assets form an exact ten-edge complete internal graph:

1. SYN/WPOL
2. SYN/USDT
3. SYN/USDC
4. SYN/WETH
5. WPOL/USDT
6. WPOL/USDC
7. WPOL/WETH
8. USDT/USDC
9. USDT/WETH
10. USDC/WETH

All ten pairs are deployed through the permissioned SINERGY DEX. The V8
controller rejects zero addresses, missing bytecode, duplicate internal pools,
duplicate external pools and overlap between the two sets. The resulting 10×10
topology is committed on-chain as `topologyHash`.

## 10 real Polygon external edges

The fork test discovers and validates ten independent QuickSwap V2/V3 pools at
the pinned Polygon state:

1. WPOL/USDT V2
2. WPOL/USDT V3
3. WPOL/USDC
4. WPOL/WETH
5. WPOL/DAI
6. USDT/USDC
7. USDT/WETH
8. USDT/DAI
9. USDC/WETH
10. USDC/DAI

Every external address must contain bytecode and non-zero balances of both pair
assets. The profitable execution contour presently uses the real QuickSwap V3
USDT→WPOL edge and the real QuickSwap V2 WPOL→USDT edge. The remaining external
pools are topology-verified graph edges available for subsequent route-search
expansion; they are not falsely reported as executed hops.

## Managed QE/QT gradient

The atomic accepted cycle is:

```text
TEMPORARY BACKED QE
→ SYN sold into internal SYN/USDT
→ real USDT extracted from the internal pair
→ real QuickSwap V3 USDT→WPOL swap
→ real QuickSwap V2 WPOL→USDT swap
→ exact USDT amount calculated for internal SYN buyback
→ SYN repurchased
→ temporary SYN burned
→ residual USDT transferred to the protocol treasury
→ internal liquid reserve and k checked
→ next stateful cycle
```

QE is temporary protocol inventory. It must be fully closed during the same
atomic transaction. QT burns the exact temporary quantity. The accepted cycle
must satisfy:

- final synthetic supply equals initial synthetic supply;
- `temporaryOutstanding == 0`;
- the touched internal liquid reserve does not decrease;
- the touched pool constant product does not decrease;
- protocol treasury USDT increases;
- executor cumulative profit increases by exactly the same measured treasury
  delta;
- the delta exceeds `minimumProfitPerCycle`;
- replay and unauthorized execution are rejected.

## Where the profit comes from

V8 does **not** label an internally created mark as external profit.

Before each accepted fork cycle, independent external order flow is executed in
the real QuickSwap V2 WPOL/USDT pool. This can create a temporary V3↔V2 market
dislocation. Managed QE then chooses the internal gradient size that can be
fully bought back and burned while capturing that independently caused external
spread.

Therefore the economic roles are distinct:

- external order flow creates the external market opportunity;
- QE sizes and exposes controlled internal inventory to the route;
- the external graph converts the opportunity into real settlement assets;
- QT closes temporary supply;
- V8 accepts the operation only after measured consolidated profit.

If there is no independently profitable external route, the test requires the
system to remain paused. Internal QE alone is not accepted as a source of
external value.

## Consolidated boundary checks

The fork test consolidates the treasury, executor, V8 controller and all ten
protocol-owned internal pools. Across accepted cycles it requires:

- raw protocol WPOL is preserved;
- raw protocol USDC is preserved;
- raw protocol WETH is preserved;
- consolidated protocol USDT increases;
- synthetic supply is restored;
- internal transfer revenue is zero;
- cumulative treasury profit exceeds gas converted to USDT at 274 gwei;
- the main internal pool restores its liquid side and does not reduce `k`.

This boundary prevents a profitable executor wallet from hiding a larger loss
inside protocol-owned LP.

## Two acceptance surfaces

### Integer shadow

The deterministic shadow executes 100 persistent cycles with integer CPMM
arithmetic. It checks exact 10+10 topology, closed temporary supply, positive
external profit, zero internal-transfer revenue and non-decreasing internal `k`.
The external multiplier in the shadow explicitly represents independently
caused order flow.

### Polygon fork

The EVM suite runs against Polygon block `90,790,000`, checks real token,
factory, router, quoter and pool bytecode, executes multiple consecutive cycles
without resetting the fixture and writes full JSON evidence.

The independent validator rejects the run unless both the shadow and Polygon
fork evidence pass all accounting and topology gates.

## Current limitations

- The current profitable route executes two of the ten validated external graph
  edges. A later graph optimizer should search and atomically prove arbitrary
  adjacent routes across all ten external pools.
- The route uses temporary protocol QE inventory; the current fork test does not
  borrow the QE quantity from Aave.
- Donor-pool impersonation is used only to provision fork test signers and create
  independent test order flow. It is not a production funding mechanism.
- A pinned historical fork proves execution for that state only. It cannot prove
  that a profitable dislocation exists continuously on live mainnet.
- Production still requires trusted-oracle integration, private execution or
  robust MEV protection, timelocked governance, hostile-token tests and an
  independent security/economic audit.

## Acceptance interpretation

A PASS means:

> At the pinned Polygon state, real QuickSwap contracts and real pool reserves
> can participate in a stateful managed QE/QT cycle where temporary supply is
> closed, the touched internal LP is restored, gas is covered and the
> consolidated protocol receives positive real USDT.

A PASS does not mean:

- guaranteed profit;
- continuous mainnet availability;
- value creation from internal repricing alone;
- production safety;
- legal or regulatory approval.
