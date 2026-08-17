# ai_financial_system in the SINERGY repository federation

Status: **additive boundary document**. No legacy implementation is superseded or deleted by this file.

## Repository role

`Shtenco/ai_financial_system` remains the primary financial R&D laboratory and reference-implementation archive for the SINERGY financial stack.

Its historical and current value includes:

- AMM and multi-token graph experiments;
- SYNA/SYNR token and liquidity research;
- AI Central Bank and AI Market Maker research;
- QE/QT and Bridge-QE experiments;
- Economic State Oracle and DeFi contour work;
- flash-liquidity and solver experiments;
- anti-MEV / commit-reveal / order-flow auction research;
- Polygon fork evidence and negative controls;
- SynthL1 / reserve-gradient / HardNAV-gated route research;
- bounded RL and policy experiments;
- Financial OS V4/V5 research package with accounting, maturity, P2P, productive credit, investment-bank and real-economy bridges.

The new `Shtenco/synergy_financial_os` repository is **not** a replacement for this history. It is the canonical constitution/schema/integration layer above it.

## Preservation rule

Nothing in the historical research line should be removed simply because a later accounting interpretation changed.

Examples:

```text
old AMM-growth hypothesis
old transfer-tax/burn variants
QE/bridge experiments
self-created-gradient research
flash-loan prototypes
negative no-external-payer controls
Polygon fork evidence
V4/V5 Financial OS branch
```

These remain useful for provenance, regression, falsification and mechanism reuse.

## Canonical interpretation boundary

Historical mechanisms may remain technically useful even when they are not accepted as sources of consolidated external profit.

Reference accounting rules for new integrations:

```text
own-token market cap       != HardNAV
internal AMM mark          != external asset
virtual reserve            != hard reserve
mint / burn / rebase       != profit by itself
flash principal            != revenue
self-paid protocol fee     != consolidated profit
new participant principal  != profit
principal repayment        != profit
```

A mechanism contributes to realized financial profit only when the consolidated externally realizable position improves after all relevant costs and capital flows.

## Relationship to synergy_financial_os

`synergy_financial_os` should reference reusable material from this repository by:

- repository;
- branch/tag/commit;
- file/contract/module;
- original claim;
- current evidence status;
- current accounting interpretation;
- known negative controls.

Code should not be copied solely to make the canonical repository self-contained.

## Financial OS V4/V5

The additive `feat/financial-os-v4-20260809` branch is an especially important reference layer because it already contains:

- `CanonicalDoubleEntryLedger` work;
- Hard/Liquid/Economic NAV separation;
- `FinancialSnapshotV2/V3` research;
- 1–100 week maturity state;
- P2P duration funding;
- productive-credit verification;
- credit pricing;
- investment-bank policy;
- real-economy bridge;
- Gesell/demurrage research;
- bounded RL and hard risk modes;
- integrated simulation and stress cases.

This branch should be treated as a major canonical-source candidate, not flattened into `main` without review.

## Claim-status taxonomy

Use claim-specific statuses:

- `LEGACY`;
- `EXPERIMENTAL`;
- `VERIFIED_SIM`;
- `FORK_VERIFIED`;
- `CANONICAL`;
- `PRODUCTION`.

Execution verification and economic-return verification are separate claims.

## Cross-repository ownership

- `synergy_financial_os` — canonical financial constitution, schemas and integration contracts;
- `synergy_matrix_sota` — household savings/maturity/funding state;
- `synergy_eurasian` — productive real-economy project/economic-state layer;
- `synergy_pay_system` — MetaPay routing, compliance, settlement and reconciliation;
- `synergychain` — portal/OGAS/control-plane integration;
- `agi_olga` — OLGA/NEXUS intelligence;
- `ai_language` — semantic engineering and requirement traceability;
- `ai_compress` — lossless/MDL memory and archive technology.

## Migration rule

Future work should be additive. When a historical mechanism is promoted into the canonical federation, add an adapter/specification/test around the source implementation instead of deleting the source generation that produced it.
