# V15 Mandatory Gates

V15 remains a draft overlay until every gate below passes.

## G0 — Frozen-base integrity

- merge base is exactly V13.1 freeze commit `385eaa2e6c811f1f29c504984484d9223b42b1b7`;
- no frozen `contracts/synthl1/*` production source is modified by V15 Stage 2.

## G1 — Mathematical/reference invariants

- Economic HardNAV excludes own synthetics;
- Economic HardNAV and RiskNAV/K/STS are separate;
- supply-neutral gradient invariant;
- conservation identity;
- capital-flow-adjusted PnL;
- HOLD when no safe action exists;
- RED/ORANGE defensive behavior.

Current local result: **12/12 PASS**.

## G2 — Solidity surface/integration invariants

- exactly 8 V15 overlay contracts;
- EconomicLedger contains no haircut valuation;
- own synthetics can be permanently excluded;
- RiskOracle reporter cannot change governance haircuts;
- AccountingAdapter implements both frozen V13.1 accounting interfaces;
- post-route K/STS gate is fail closed;
- restore/close remain emergency-callable;
- revenue has single settlement and loss carry-forward;
- no frozen V13.1 contract logic is imported into V15 overlay, except shared `SafeTransferLib`.

Current local result: **9/9 PASS**.

Combined local Python/static result: **21/21 PASS**.

## G3 — Solidity compiler

`npm ci && npm run compile`

Required result: zero Solidity compile errors.

Current local status: **NOT EXECUTED**. The sandbox has no `solc`/`forge`, and its restricted npm registry returns 404 for `solc@0.8.26`.

## G4 — V15 EVM overlay tests

`npm run test:v15:evm`

Must prove:

1. canonical Economic HardNAV remains distinct from K/STS risk accounting;
2. liability shock makes adapter fail closed;
3. contribution cannot become operating revenue;
4. revenue distribution cannot exceed settled hard PnL;
5. prior losses must be recovered before later PnL is distributable;
6. known V13.1 latent-basis route passes through V15 when HardNAV and post-route K/STS pass;
7. the same Economic-HardNAV-positive route reverts atomically when post-route K/STS breaches the active mode floor.

Current status: **tests implemented, execution pending compiler/runtime**.

## G5 — Frozen V13.1 regression

`npm run test:synthl1:evm`

V15 must not break the frozen V13.1 EVM guards.

## G6 — Fork gate

After G0-G5 are green:

- pinned Polygon archival fork;
- current real venue contracts;
- no private keys in source/logs;
- oracle freshness / depeg / stale-data scenarios;
- bridge unavailable scenario;
- gas spike / solver reward floor;
- owner/capture/pool/accounting balance reconciliation.

## G7 — 10×50 optimizer

Only after G0-G6 pass may the full `2 synthetics × 5 internal pools + 50 external venues` optimizer be connected.

The optimizer is not allowed to bypass V15 Economic HardNAV, K/STS, oracle uncertainty, liability completeness or supply-partition postconditions.
