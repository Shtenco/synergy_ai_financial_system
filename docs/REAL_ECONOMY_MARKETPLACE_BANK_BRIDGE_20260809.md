# SINERGY Financial OS — Marketplace Goods / Import / FX / Investment Bank Bridge

Status: **CANONICAL RESEARCH ADDENDUM / LOCAL CALIBRATION**

This document extends the Financial OS architecture without changing any legacy `main` file.

## 1. What is preserved from the historical Productive Liquidity design

The historical Grand Unified V4/V5 line already contained the correct structural idea:

- productive issuance is not released directly into free circulation;
- the project first receives a conditional escrow/temporary-credit envelope;
- private/bank/anchor capital must match the project;
- release depends on observed project performance;
- domestic output is bounded by productive capacity;
- bad ratings, fraud and liquidity constraints can stop new projects;
- V5 adds competitive market/debt funding before central-bank residual funding.

The canonical Financial OS keeps this idea but changes the accounting boundary:

`targeted escrow authorisation` is **not HardNAV, profit or circulating money**. It is a conditional monetary limit. Only the amount released after verified growth becomes a monetary liability, and only against an eligible performing productive claim/asset.

## 2. Russian e-commerce is the goods observability layer

Public calibration anchor:

- AKIT reported Russian internet commerce of RUB 11.5 trillion in 2025, +28% YoY;
- 96.2% of online sales were through domestic Russian shops/platforms and 3.8% were cross-border.

Source: https://akit.ru/news/11-5-trln-rublej-akit-podvela-itogi-internet-torgovli-za-2025-god

Critical accounting distinction:

`domestic sales channel != domestic goods origin`.

A SKU sold by a Russian marketplace/seller may be imported. Therefore the goods observatory stores at least:

- platform / seller / order id;
- delivered quantity and constant-price value;
- refund/return status;
- warehouse saleable stock;
- seller jurisdiction;
- manufacturer/country-of-origin evidence where available;
- customs/HS/import declaration evidence where applicable;
- invoice/settlement currency;
- fiscal-receipt or equivalent settlement evidence.

The deterministic decomposition is:

`ImportOriginShare = CrossBorderShare + LocalChannelShare * DomesticChannelImportContent`.

For the 2025 channel shares, three sensitivity assumptions give:

| Domestic-channel imported content | Implied import-origin share of e-commerce | Import-origin e-commerce value |
|---:|---:|---:|
| 20% | 23.04% | RUB 2.650 tn |
| 35% | 37.47% | RUB 4.309 tn |
| 50% | 51.90% | RUB 5.969 tn |

The 20/35/50% values are **scenario assumptions**, not published AKIT statistics. Production deployment must infer origin from SKU/customs/seller/invoice evidence instead of using one national constant.

## 3. FX use must come from import settlement, not GMV

Bank of Russia reports that in 2025 more than half of Russian import payments were already made in rubles, while the combined share of USD and EUR fell below 15%.

Source: https://www.cbr.ru/about_br/publ/results_work/2025/razvitie-sistemy-platezhey-i-raschetov/

The reference simulation therefore uses only a bounded illustrative profile:

- RUB 55%;
- CNY 30%;
- USD+EUR 12%;
- other 3%.

This is a **simulation profile constrained by public ranges**, not a claim that marketplace imports have exactly this currency mix. Production uses actual bank/MetaPay invoice settlement data.

With the 35% domestic-channel import-content scenario, annual marketplace import-origin exposure is about RUB 4.309 tn. Applying the illustrative settlement profile gives an annual flow proxy of approximately:

- RUB settlement: RUB 2.370 tn equivalent;
- CNY settlement: RUB 1.293 tn equivalent;
- USD+EUR settlement: RUB 0.517 tn equivalent;
- other currencies: RUB 0.129 tn equivalent.

Again: this is sensitivity math, not an empirical marketplace currency census.

## 4. Banks remain savings transformers

The Financial OS does not replace banks. It orchestrates them.

Bank of Russia describes the banking sector as transforming customer funds into credit to the economy. Its 2025 financial accounts reported household financial savings of RUB 13.2 tn. Bank financing of sectors through credits and loans in 2025 was RUB 12.4 tn.

Sources:
- https://www.cbr.ru/banking_sector/
- https://www.cbr.ru/statistics/macro_itm/fafbs/financial_accounts/

Canonical flow:

```text
Household / company savings
        -> maturity buckets
        -> bank / investment-bank funding capacity
        -> competitive Productive Capital Auction
        -> project note / receivable / productive claim
        -> production / logistics / inventory / import-capex
        -> marketplace + customs + payment verification
        -> targeted escrow release
        -> bank refinancing / working-capital recycling
        -> project revenue
        -> principal repayment
        -> QT / liability destruction
```

The bank carries normal underwriting risk. Targeted issuance is not a guaranteed return for the bank.

## 5. Productive Capital Auction

Each investment bank bid carries:

- actually funded amount;
- funding cost;
- capital charge;
- maturity;
- risk score;
- funding currency;
- FX-hedge state.

The auction rejects a bid if:

- funding maturity is not longer than project maturity;
- the proposed funding is not actually funded;
- foreign-currency funding is unhedged;
- concentration limits would be exceeded.

The auction can clear multiple banks. Lowest nominal coupon alone does not win.

## 6. Targeted escrow release

A project receives an off-balance-sheet conditional authorisation `E`.

It is not circulating SYNT until verified release.

For a simple research profile:

`GoodsScore = min(1, (DeltaDomesticGoods + h_import * DeltaImportGoods) / TargetGoods)`

`BaseScore = min(1, DeltaProductiveBase / TargetProductiveBase)`

`ReleaseFactor = w_goods * GoodsScore + w_base * BaseScore`

`ReleasedSYNT <= E * ReleaseFactor`.

Reference policy:

- `w_goods = 60%`;
- `w_base = 40%`;
- imported goods haircut for monetary release `h_import = 30%`.

Imported goods count fully for **goods availability**, but only partially for **monetary-release capacity**, because imported inventory improves supply while creating replenishment/FX dependence rather than the same domestic productive capacity as local production.

## 7. Financial OS as orchestrator

The canonical OS does four things simultaneously:

1. observes goods and payment flows;
2. observes savings maturity and bank balance-sheet capacity;
3. runs capital/FX/payment auctions;
4. allows new monetary liabilities only after the Constitution and growth proof agree.

Therefore the core policy cap becomes:

`TargetAuthorization <= min(SavingsFundingCapacity, PrivateBankFunding/privateMatch, RiskCapacity, LiquidityCapacity, VerifiedProductiveDemand)`.

`NO ACTION` remains valid and mandatory if the risk-adjusted investment economics are negative.

## 8. Local reference calibration

For a deliberately small pilot, the local Monte Carlo uses:

- 2025 household financial savings: RUB 13.2 tn/year;
- SINERGY captures only 0.1% of new savings flow;
- 40% is term-eligible;
- banks may transform at most 45% of that eligible flow into new productive funding.

This gives approximately:

`13.2 tn / 52 * 0.1% * 40% * 45% = RUB 45.69 million/week`.

The simulation runs 300 deterministic seeds for 100/250/500 cycles. These are **research scenario outputs, not forecasts**.

Median results from the local harness:

| Cycles | Scenario | Private investment | Authorization unlocked | Verified goods | Productive-base increase | Import/FX replenishment | Bank net result | OS external fee revenue |
|---:|---|---:|---:|---:|---:|---:|---:|---:|
| 100 | base | 3.55 bn | 1.94 bn | 1.72 bn | 0.74 bn | 0.84 bn | +4.2 m | 5.3 m |
| 100 | stress | 2.30 bn | 1.03 bn | 0.92 bn | 0.39 bn | 0.47 bn | -147.7 m | 2.9 m |
| 250 | base | 8.85 bn | 5.34 bn | 4.74 bn | 2.03 bn | 2.36 bn | +17.1 m | 14.7 m |
| 250 | stress | 5.75 bn | 2.84 bn | 2.53 bn | 1.08 bn | 1.25 bn | -400.2 m | 7.8 m |
| 500 | base | 17.71 bn | 11.02 bn | 9.78 bn | 4.19 bn | 4.84 bn | +33.7 m | 30.3 m |
| 500 | stress | 11.51 bn | 5.89 bn | 5.23 bn | 2.24 bn | 2.58 bn | -816.4 m | 16.2 m |

The stress result is intentionally useful negative evidence: if banks keep the base underwriting terms during the stressed default regime, their expected/realised result becomes negative. The correct Financial OS reaction is **not** to compensate this loss by printing more money. It is to tighten/stop the Productive Capital Auction, demand more private first-loss capital, reprice risk or return `NO ACTION`.

## 9. Hard accounting boundaries

Never count as external value:

- target authorisation itself;
- locked/non-transferable escrow units before a beneficiary has an enforceable claim;
- marketplace GMV growth caused only by inflation;
- internal token appreciation;
- a nominal FX quote without settlement;
- imported inventory as domestic productive capacity;
- bank refinancing as profit;
- principal repayment as profit.

Count only reconciled external assets, eligible performing claims after haircut, actual fee/interest receipts, and realised settlement results.
