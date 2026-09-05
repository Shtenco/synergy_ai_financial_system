# DEX Finance → MetaPay External Profit Bus integration

Date: 2026-09-05
Status: R&D integration candidate, not production-authorized.

## Purpose

This repository already contains DEX graph-arbitrage/QE research and an on-chain `LiquidityGrowthCycle.executeGraphArbitrage` boundary that requires the settlement-token balance to grow by at least `minProfit` or reverts.

The missing cross-project link was a standard evidence object that can be consumed by MetaPay and then classified by Financial OS.

`simulation/metapay_external_profit_evidence.py` adds that adapter.

## Economic perimeter

Evidence must compare the same externally redeemable settlement asset over the same consolidated economic perimeter.

If `LiquidityGrowthCycle` transfers an internal protocol tax from the executor to a treasury controlled by the same economic entity, that internal transfer is **not an external cost**. Executor + treasury should be consolidated for system-wide external NAV.

External costs include items such as:

- gas paid to external validators/builders;
- flash premium paid externally;
- external bridge/withdrawal fee;
- external DEX/CEX/provider fee not already reflected in the measured balance delta;
- other independently settled costs.

## Formula

For balance-delta DEX evidence:

```text
external_cash_delta = post_external_balance - pre_external_balance
candidate_external_pnl = external_cash_delta - external_costs_remaining - flash_premium_remaining
```

The route is admissible only if:

- real settlement occurred;
- independent external market/counterparty evidence exists;
- flash principal is repaid;
- transaction hash and block number exist for on-chain settlement;
- candidate P&L is positive.

Internal mint quantity and internal mark delta are preserved only as provenance and never enter this formula.

## Wire mapping to MetaPay

The adapter emits the fields used by MetaPay's `ExternalProfitBus`:

```text
source = DEX_ARBITRAGE
settlement_asset = external settlement token
input_amount = 0
settled_output = consolidated external cash delta
external_costs = remaining external costs
flash_premium = remaining flash premium
settlement_realized = true/false
independent_external_counterparty = true/false
flash_principal_repaid = true/false
provider_references = venue/lender refs
route_digest = SHA-256 of canonical evidence
internal_mint_quantity = provenance only
internal_mark_delta = provenance only
```

`input_amount=0` is deliberate in this balance-delta adapter: working principal is already inside both pre- and post-balance measurements. Subtracting principal again would double-count it.

## Relationship to the print-machine/QE contour

Internal QE may alter price geometry, but no internal mark is passed as P&L. Only an externally closed route that changes the consolidated external balance can enter the External Profit Bus.

Therefore:

```text
internal QE / mint / repricing
        ↓
possible market discrepancy
        ↓
external arbitrage/order flow
        ↓
real external settlement
        ↓
DEX evidence adapter
        ↓
MetaPay External Profit Bus
        ↓
Financial OS classification
```

This preserves the existing negative solvency evidence: controlled revaluation alone does not add external reserves, and moving existing bridge reserves does not create system-wide profit.
