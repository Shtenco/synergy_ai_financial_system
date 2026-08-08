# SINERGY Financial OS V4 — side-by-side architecture

This document belongs to the new `feat/financial-os-v4-20260809` branch. It does **not** replace the legacy AMM/QE/MEV experiments. Those remain valuable historical and falsification material.

## 1. Monetary constitution

The V4 constitution starts from three non-interchangeable functions:

- **SYNA — capital/equity/risk/upside**;
- **SYNR — reserve/savings/insurance capital**;
- **SYNT — stable transaction money and unit of account**.

`capital != reserve != money != credit` is the first invariant. Credit can be represented technically in SYNT, but it must be tracked as a liability with its own maturity, expected-loss and funding-duration accounting.

## 2. HardNAV is the public truth metric

The system publishes three valuation layers:

```text
HardNAV      = hard redeemable external assets - external liabilities
LiquidNAV    = haircut liquid assets          - external liabilities
EconomicNAV  = haircut economic assets        - external liabilities
```

The system's own token market cap, virtual reserves, internally recycled fees and self-generated price marks do not count as hard assets.

Distributable profit is:

```text
max(0, HardNAV_t - HardNAV_(t-1) - NetNewCapital_t)
```

This prevents deposits, capital injections, minting and self-token repricing from being mislabeled as profit.

## 3. Savings and duration market

Users may route 2–5% of income into a 1–100 week vesting ladder. Vesting is not a free-float manipulation trick; it is a funding-duration declaration.

Loans must satisfy:

```text
loan_maturity < funding_maturity
```

Rewards are paid from realized external profit and can be weighted by token-weeks / amount-duration.

## 4. P2P and productive credit

P2P debt is denominated in KZT/USDT/SYNT value, not in a potentially appreciating amount of SYNA. Own system equity is not the primary collateral.

Temporary productive money creation is bounded by:

```text
QE_max = min(reserve_capacity,
             liquidity_capacity,
             verified_productive_demand,
             risk_capacity)
```

Principal repayment drives QT. Interest and service income become external revenue only after actually collected.

## 5. Gesell layer

Demurrage is optional and applies to **idle transactional SYNT**, not to every form of savings or capital.

A protected transaction balance can have zero demurrage. Above that threshold, a small countercyclical carry cost can encourage idle money to move into spending, term savings or productive investment. Collected demurrage can be split between QT/burn, insurance and reserves.

## 6. AI central bank: rules first, RL second

The architecture is:

```text
Monetary Constitution
      -> deterministic baseline policy
      -> bounded RL residual
      -> safety shield / hard invariants
      -> action
```

RL is never allowed to bypass hard constraints. If the model is unavailable, residual action becomes zero and the deterministic policy continues.

Hard action constraints include:

- HardNAV coverage >= 1;
- LCR >= configured floor;
- no unbacked mint;
- no flash debt at accounting commit;
- loan maturity < funding maturity;
- MIDAS drawdown kill switch;
- no buyback without realized distributable profit.

## 7. Four operating modes

- `GROWTH`: weak output/low inflation; productive credit can expand within verified capacity.
- `NORMAL`: ordinary policy.
- `DEFENSE`: reduce risk, freeze buyback, increase reserves.
- `EMERGENCY`: stop new lending/QE/MIDAS risk and protect redemptions.

## 8. Insurance and loss waterfall

Losses are isolated by type:

```text
borrower collateral
 -> expected-loss reserve
 -> event-specific insurance
 -> general reserve / SYNR junior capital
 -> sponsor first-loss capital
 -> protected saver capital (last resort)
```

Normal MIDAS market drawdown is not an insurance event.

## 9. Two lifts, redefined

The useful two-lift model is balance-sheet based:

- **asset lift**: hard reserve + realized external profit + haircut performing assets;
- **liability lift**: outstanding SYNT/credit/emission obligations.

Unrealized self-token appreciation does not retire liabilities. Only realized external settlement, repayment, dividends or external trading profit can do so.

## 10. Integration with existing repository

The old contracts and simulations are not deleted or silently reinterpreted. V4 consumes their lessons:

- AMM invariants remain useful for execution and liquidity;
- solver auctions can monetize independent external orderflow;
- flash liquidity is a temporary funding primitive, not revenue;
- MEV recapture is recognized only when consolidated external PnL improves;
- controlled internal marks are not HardNAV.

The reference Python package in `financial_os_v4/` is intentionally dependency-free and accounting-first so it can become the common invariant library for future Solidity, Python and payment-system implementations.
