# Legacy Grand Unified AICB/DAO distillation

Status: **historical research review**. This document does not delete or rewrite the old Grand Unified / Unified DAO+AICB source. It classifies reusable mechanisms against the canonical SINERGY HardNAV rules.

## CANONICAL / salvage

The historical model contains several mechanisms worth preserving as research components:

- physical production bounded by productive capacity and utilisation;
- bank-liquidity floors instead of allowing negative liquidity;
- rating gates, quarantine, fraud penalties and learning;
- project-specific production/import/logistics/SME/export channels;
- escrow release linked to observed project performance;
- market funding, auction, repo/reverse-repo and maturity concepts;
- external reserve acquisition **when an actual external asset is received and reconciled**;
- the balance-sheet version of the twin elevators: asset capacity is compared with temporary/emission liabilities, but liabilities are retired only by realised external proceeds, principal repayment or authorised hard settlement;
- DAO health as a demand/risk observation, not as money or reserve backing;
- separate micro and macro histories for causal analysis.

## REJECTED as a balance-sheet source

### Internal DAO reserve -> external FX reserve

The historical Grand Unified bridge contains a channel that takes an amount from `dao_eco.global_reserve`, divides the local amount by the FX rate and adds the result directly to the AICB strategic external reserve basket.

The DAO reserve itself is generated primarily by internal DAO treasury allocations and modelled internal investment/MIDAS dynamics. Dividing an internal accounting unit by an FX rate is **not an external settlement** and cannot create a hard foreign reserve asset.

Canonical replacement:

```text
DAO internal value
    -> demand/risk/productive signal only
    -> NO HardNAV change

External payer / bank / merchant / FXP / exchange settlement
    -> reconciliation/finality
    -> external asset journal debit
    -> only then may HardNAV/reserve rise
```

This historical bridge is therefore `REJECTED` as a source of HardNAV, external reserve or distributable profit.

### Own-sovereign bonds held by the same consolidated CB -> external backing

The historical V6 asset elevator includes central-bank holdings of the same sovereign's bonds, after a haircut, as part of the asset side covering emission debt.

That treatment is not valid when the accounting perimeter consolidates Treasury and the central bank. The sovereign bond asset held by the CB and the sovereign liability issued by Treasury are an intra-group claim and cancel on consolidation. They may still matter operationally for collateral, duration, monetary transmission and legal-entity liquidity, but they are not new external net wealth for the consolidated SINERGY public balance sheet.

Canonical rule:

```text
Treasury liability to own consolidated CB
+ CB claim on own Treasury
= eliminate on consolidation
```

The claim may be included in HardNAV/elevator backing only when the accounting perimeter explicitly excludes the issuer and the claim is externally enforceable/redeemable against a legally separate balance sheet. The perimeter must be disclosed. Otherwise this channel is `REJECTED` as external backing.

### DAO token-price feedback -> wealth

A pass-through from a macro market index into an internal DAO token price may remain an experimental market-model feature. It must not feed HardNAV, reserve coverage, mint capacity or distributable profit until there is an executable external exit and realised settlement.

### Composite Grand Score as success criterion

A weighted score may be useful as a diagnostic dashboard, but it cannot override:

1. double-entry conservation;
2. HardNAV / LiquidNAV / EconomicNAV;
3. liquidity and maturity invariants;
4. external realised PnL;
5. liability coverage;
6. stress losses.

The canonical simulator therefore records mode scores only as secondary diagnostics and treats the balance sheet as source of truth.

## EXPERIMENTAL / strict guards

The following legacy ideas remain researchable, but not balance-sheet truth by default:

- cross-bloc QE;
- market-maker reserve interventions;
- dynamic reserve-currency demand;
- DAO-to-macro policy feedback;
- directional market support;
- external currency lock assumptions;
- market-index QE portfolios.

Each requires explicit external asset ownership, executable valuation/haircuts, settlement finality and loss recognition.

## New replacement architecture

The replacement path is:

```text
CanonicalDoubleEntryLedger
        |
        +-- external assets / liabilities
        +-- P2P performing assets
        +-- productive-credit assets
        +-- realised revenue / expenses
        |
        v
FinancialSnapshot V2
        |
        +-- HardNAV / LiquidNAV / EconomicNAV
        +-- 1..100 week unlock curve
        +-- LCR 1w / 4w / 8w
        +-- ledger sequence + SHA-256 digest
        |
        v
Monetary Constitution
        |
        +-- deterministic policy
        +-- bounded RL residual
        +-- GROWTH / NORMAL / DEFENSE / EMERGENCY
```

MetaPay remains a separate execution boundary. Payment/FX quotes may create revenue only after executable/compliant routing and settlement/reconciliation; an internal route or nominal spread is not profit.

## Audit rule

A future reuse of any historical AICB/DAO mechanism must answer five questions before it becomes canonical:

1. What exact external asset or performing claim appears?
2. What exact external liability is created or extinguished?
3. What is the legal/consolidation perimeter of both sides of the claim?
4. What journal entry proves conservation after intra-group elimination?
5. What happens under withdrawal/default/oracle/bridge/MIDAS stress?

If these cannot be answered, the mechanism remains `EXPERIMENTAL` or `REJECTED`.
