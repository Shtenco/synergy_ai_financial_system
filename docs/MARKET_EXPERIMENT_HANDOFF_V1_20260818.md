# SINERGY Financial R&D Market Experiment Handoff V1 — 2026-08-18

## Purpose

This additive protocol gives preserved AMM/QE/QT/MEV/flash/graph/bridge experiments one common result format without rewriting any historical experiment or promoting the R&D repository to accounting authority.

## Profit boundary

The handoff deliberately does **not** derive profit from:

- mint notional;
- flash principal;
- internal AMM/LP mark changes;
- self-token price or market-cap changes;
- gross external-asset movement by itself;
- new external capital contributions.

The only R&D P&L candidate is:

```text
external_pnl_candidate
  = externally_observed_revenue
  - gas_cost
  - venue_fees
  - bridge_fees
  - flash_fees
  - other_external_costs
```

Positive externally observed revenue requires an independent evidence digest. Fork and live-observed runs also require an execution-evidence digest.

## Diagnostic NAV

The result also reports external assets/liabilities before and after and computes:

```text
external_nav_surplus_after_capital
  = external_nav_after
  - external_nav_before
  - net_new_external_capital
```

This value is diagnostic only. Asset hardening or accounting reclassification can change it without creating distributable P&L, so it is not used by the candidate-profit formula.

## Authority boundary

Every result remains:

```text
classification = RND_ONLY
accounting_authority = Shtenco/synergy_financial_os
financial_os_recognition = NOT_PERFORMED
```

The maximum local handoff status is `HANDOFF_REVIEWABLE`. Financial OS must independently decide whether evidence maps to a canonical reporting entry and realized external P&L.

## Non-destructive evolution

This protocol is stacked above `docs/sinergy-federation-boundary-20260817`. Existing financial experiments, negative controls, Solidity contracts, fork reports and historical claims are unchanged. Their original semantics remain available for replay and falsification.
