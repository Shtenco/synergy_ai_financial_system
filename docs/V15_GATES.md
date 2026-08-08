# V15 Mandatory Gates

V15 remains a draft overlay. The full 10×50 optimizer stays disconnected until every execution gate below is green.

## G0 — Frozen-base integrity — PASS

- merge base is exactly V13.1 freeze commit `385eaa2e6c811f1f29c504984484d9223b42b1b7`;
- branch comparison is ahead-only (`behind=0`);
- no frozen `contracts/synthl1/*` production source is modified by the V15 overlay.

Verified again after the current hardening pass.

## G1 — Mathematical/reference invariants — IMPLEMENTED

Required invariants:

- Economic HardNAV excludes own synthetics;
- Economic HardNAV and RiskNAV/K/STS are separate;
- supply-neutral gradient invariant;
- protocol + external LP + solver conservation identity;
- capital-flow-adjusted PnL;
- robust/maximin candidate selection;
- absolute risk-capital and concentration limits;
- HOLD when no safe action exists;
- RED/ORANGE defensive behavior;
- winner's-curse/model-risk penalty before large graph search;
- recapitalization is capital contribution, not revenue.

`npm run test:v15` now discovers every `tests/test_v15_*.py` file instead of maintaining a fragile hand-written list.

Reference suites passed in prior local runs. The current GitHub head still requires a clean rerun once an execution environment is available.

## G2 — Solidity surface / fail-closed wiring — IMPLEMENTED, EXECUTION PENDING

Production overlay remains exactly 8 top-level V15 contracts.

Current hardening includes:

- `V15EconomicLedger`: own-synthetic exclusion; lower-of-two Economic oracle; one-way validation freeze; `price1e18()` validated-anchor ABI;
- `V15LiabilityRegistry`: generic liabilities; stale manual liabilities fail closed; outstanding liabilities cannot be disabled;
- `V15RiskOracle`: TWAP/exit/haircut risk marks plus one-way frozen validated canonical anchor;
- `V15SolvencyController`: K/STS, absolute risk-assets floor, concentration limit, GREEN/YELLOW/ORANGE/RED, guardian stop;
- `V15PostRouteGate`: frozen V13.1 searcher route allowed only in GREEN/YELLOW and only when the controller permits expansion;
- `V15AccountingAdapter`: frozen V13.1 compatibility plus validated-accounting registration gate;
- `V15Coordinator`: new gradient/reinvestment only under expansion permission; restore/close remain emergency-callable;
- `V15RevenueRouter`: physical revenue evidence, HWM/loss carry-forward, capital-flow adjustment and solvency-limited distribution.

## G3 — Solidity compiler — INFRA-BLOCKED

Command:

`npm ci && npm run compile`

Required result: zero Solidity compile errors.

Current local environment has no `solc`, `forge`, `hardhat`, Docker or Podman, and its restricted npm registry does not provide `solc@0.8.26`.

Latest GitHub Actions `V15 Overlay CI` run creates the job but the runner never starts: the job reports `steps=null`. Therefore the GitHub red status is **not a compiler result**.

Do not mark G3 PASS or FAIL until an actual compiler process runs.

## G4 — V15 EVM overlay — TESTS CURRENT, EXECUTION INFRA-BLOCKED

Command:

`npm run test:v15:evm`

Current gate suite intentionally contains only current-API tests:

1. `test/v15_stage3_hardening.js`
   - lower-of-two Economic feed;
   - stale Economic validator fail-closed;
   - stale liability fail-closed;
   - outstanding liability cannot disappear.
2. `test/v15_guardian.js`
   - guardian can stop immediately;
   - guardian cannot restart;
   - validated Economic + validated Risk anchor wiring.
3. `test/v15_revenue_evidence.js`
   - physically evidenced hard revenue;
   - raw donation is not revenue;
   - capital contribution is not revenue;
   - prior loss must be recovered before distribution.
4. `test/v15_v13_integration.js`
   - frozen V13.1 latent-basis route through V15;
   - Economic HardNAV + post-route K/STS gate;
   - ORANGE blocks new searcher exploitation;
   - RED restores and closes an already-active gradient;
   - RiskOracle is frozen on the validated Economic ledger.

The stale pre-evidence `test/v15_overlay.js` was removed from the branch rather than kept as dead legacy.

## G5 — Frozen V13.1 EVM regression — EXECUTION INFRA-BLOCKED

Command:

`npm run test:synthl1:evm`

V15 may not progress if any frozen V13.1 EVM guard regresses.

The workflow is wired, but the current GitHub runner also fails before its first step.

## G6 — Emergency execution sub-gates — TESTED IN CODE, EXECUTION PENDING

Must execute successfully before fork testing:

- RED: no new searcher exploitation;
- RED: exact `restoreGradient()` remains callable;
- RED: `closeGradient()` remains callable;
- guardian: emergency stop works immediately;
- guardian: cannot unpause/restart risk;
- validated RiskOracle anchor is frozen and cannot silently fall back during monetary expansion.

## G7 — Polygon archival fork — LOCKED UNTIL G3-G6

Required:

- pinned Polygon archival block;
- current real venue contracts and token addresses;
- external quote/oracle freshness checks;
- depeg and stale-data scenarios;
- bridge-unavailable scenario if bridge path is enabled;
- realistic gas + solver reservation floor;
- owner/capture/pool/accounting reconciliation;
- no private keys or secrets in source/logs.

No archival fork result is claimed yet.

## G8 — Full 10×50 optimizer — HARD LOCK

Only after G0-G7 are genuinely green may the full:

`2 synthetics × 5 internal pools + 50 external venues`

optimizer be connected to execution.

The optimizer must never bypass:

- Economic HardNAV;
- generic liabilities;
- validated Economic + Risk oracle anchors;
- K/STS;
- absolute risk-capital floor;
- asset/cluster concentration policy;
- drawdown budget;
- model/selection uncertainty;
- solver reservation economics;
- supply-neutrality and exact-restore postconditions.

**No compile/EVM/fork evidence = no 10×50 execution.**
