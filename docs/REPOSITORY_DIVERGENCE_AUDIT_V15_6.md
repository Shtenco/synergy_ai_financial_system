# SYNERGY repository divergence audit — V15.6 recovery

## Root cause

The research history diverged at commit `927a5e4d0046e377c78fed7f1a033ea0e3abc9c6`.

The `audit/stateful-supercycle-v8` branch continued for 161 commits, while the later `audit/synergy-qe-polygon-fork` branch added 15 commits containing the direct-source V11 atomic QE/QT executor and V12 managed-gradient probe. Because PR #8 was created from the earlier merge base, those later V11/V12 files were absent from its head even though V8 documentation and tests referenced them.

## Confirmed missing execution layer

Before recovery, PR #8 did not contain:

- `contracts/fork/SynergyAtomicQeQtCycleV11.sol`;
- `test/synergy_atomic_qe_qt_v11_polygon_fork.js`;
- `scripts/validate_atomic_qe_qt_v11_fork.py`;
- `contracts/fork/SelfCreatedGradientProbeV12.sol`;
- `test/self_created_gradient_v12_polygon_fork.js`;
- `scripts/validate_self_created_gradient_v12.py`;
- the direct-source V11/V12 workflows.

At the same time, `test/stateful_supercycle_v8_10x10_polygon_fork.js` instantiated `TemporaryQETokenV11` and `SynergyAtomicQeQtCycleV11`. Therefore the V8 integration surface in PR #8 was structurally incomplete.

## Workflow-name overwrite

The file `.github/workflows/stateful-supercycle-v8.yml` had been repurposed to run the V15.1 historical external-revenue workflow. The content was valid for V15.1, but the filename and acceptance surface were wrong. Recovery separates the two workflows again:

- `stateful-supercycle-v8.yml` — V8 10-internal/10-external stateful fork acceptance;
- `synergy-v15-1-strict-historical.yml` — V15.1 historical external-revenue workflow.

## Architecture that must remain unified

The recovered stack is not the isolated V15.5 two-pool experiment. The primary positive-edge research path is:

1. internal permissioned graph;
2. managed temporary QE inventory;
3. independently caused external DEX dislocation;
4. external graph route through real Polygon pools;
5. exact internal buyback;
6. QT closure of temporary supply;
7. consolidated LP/treasury accounting after gas and flash premium;
8. fail-closed rollback on stale or unprofitable routes.

V15.5 remains useful only as a negative control proving that ADDLP, reversible self-swaps, mint and burn without an external payer/edge cannot create WPOL surplus.

## Pool layers

- V7: exact six-pool internal core over WPOL, USDT, SYNA and SYNR.
- V8: ten internal pools plus ten validated real Polygon external pools; currently only a two-edge external route is executed.
- V10/V13/V14: discovery and strict accounting over fifty selected external pools across 100 blocks.
- V15.1–V15.3: historical victim/backrun, RFQ, solver-auction and transaction-panel external revenue surfaces.

The next integrated acceptance surface must preserve V14 accounting while allowing the route optimizer to select from the 50-pool external graph and execute through the V11 QE/QT closure primitive.
