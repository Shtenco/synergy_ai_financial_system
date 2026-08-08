# V15 Status — Stage 2 Solidity Overlay

Base: frozen V13.1 commit `385eaa2e6c811f1f29c504984484d9223b42b1b7`.

V13.1 production contracts remain unchanged. V15 is implemented as a fork-only overlay under `contracts/v15/`.

## Completed

- formal mathematical specification;
- invariant proof notes;
- Python SolvencyBrain reference model;
- 12 mathematical/solvency tests;
- 8-contract Solidity overlay:
  - `V15EconomicLedger`
  - `V15LiabilityRegistry`
  - `V15RiskOracle`
  - `V15SolvencyController`
  - `V15PostRouteGate`
  - `V15AccountingAdapter`
  - `V15Coordinator`
  - `V15RevenueRouter`
- dual frozen-V13.1 ABI compatibility adapter;
- atomic post-route K/STS fail-closed gate;
- loss carry-forward / single-settlement revenue accounting;
- 9 static Solidity-surface tests;
- combined local reference/static result: **21/21 PASS**;
- EVM test suites written for standalone V15 and V15-over-V13.1 integration;
- V15 CI workflow added.

## Hardening already applied

- Economic HardNAV is canonical and unhaircut;
- RiskNAV/K/STS are separate haircut/exit-depth calculations;
- own synthetics can be permanently excluded from HardAssets;
- hard-account re-enable cannot double-count balances;
- risk reporters cannot raise governance haircuts;
- missing stress scenarios fail closed;
- restore/close remain available in emergency modes;
- quote reinvestment is allowed only in expansion-safe modes;
- RevenueRouter cannot settle a period twice;
- prior operating losses must be recovered before later gains become distributable.

## Pending deployment gate

Fresh Solidity compilation and EVM execution are still required.

The current sandbox has no `solc`/`forge`, and its restricted npm registry returns 404 for `solc@0.8.26`. The committed GitHub workflow is therefore the next compiler gate.

No compiler PASS is claimed until bytecode compilation and the V15/V13.1 EVM suites actually complete.

## Explicitly deferred

The 10-managed-pool / 50-external-pool optimizer is not connected yet. It starts only after Stage 2 compilation/EVM gates are green.
