# RAG ADDENDUM V6 — MARKETPLACE / GOODS / IMPORT-FX / INVESTMENT-BANK BRIDGE

Status: **CANONICAL ADDENDUM** to SINERGY Architecture RAG Memory V3.

## Retrieval rule

When a future task asks how SINERGY connects money creation to the real economy, retrieve this addendum together with the canonical Architecture RAG V3.

## Canonical chain

`Savings -> maturity buckets -> regulated bank/investment-bank balance sheet -> Productive Capital Auction -> funded project claim -> production/logistics/import-capex -> marketplace/customs/payment evidence -> independent verification -> conditional targeted authorisation release -> bank refinancing / working-capital recycling -> project revenue -> principal repayment -> QT`.

## New distinctions

1. `Domestic marketplace channel != domestic origin of goods`.
2. Marketplace GMV is observability input, not HardNAV and not physical output by itself.
3. Goods availability may include imported goods fully, but imported goods receive a monetary-release haircut because they create replenishment and FX dependence rather than equal domestic productive capacity.
4. Import FX demand must come from invoice/payment evidence and then pass through MetaPay RFQ/FXP liquidity reservation.
5. Banks remain savings transformers. SINERGY Financial OS is an orchestrator and policy/verification layer, not a replacement for bank balance sheets.
6. Targeted escrow authorisation is a conditional limit. It is not circulating money, profit, reserve or bank yield before verified release.
7. Bank expected return cannot include future mint as a subsidy. Negative risk-adjusted underwriting => `NO ACTION` unless real project economics, collateral or external first-loss capital changes the result.
8. Financial Snapshot V3 adds a real-economy observability block while Financial Snapshot V2/double-entry ledger remains the monetary truth source.

## Real-economy state fields

- goods availability base;
- domestic-origin delivered goods;
- import-origin delivered goods;
- productive base;
- import dependency;
- new financial savings;
- term-eligible savings;
- bank productive funding capacity;
- private bank funding committed;
- targeted authorisation outstanding;
- import FX demand by settlement currency.

## Marketplace verification

Production adapters should reconcile, where legally/technically available:

- delivered/refunded orders;
- warehouse stock;
- SKU/manufacturer/country-of-origin;
- customs/HS evidence;
- fiscal receipt/settlement evidence;
- invoice settlement currency;
- bank/MetaPay payment finality.

No single marketplace API is sufficient proof of domestic productive output.

## Investment-bank gate

Minimum simplified condition:

`ExpectedInterest - ExpectedCreditLoss - FundingCost - CapitalCharge - OpsCost > minimumMargin`.

Targeted monetary authorisation must not appear in this expected-return identity.

## Status of modules

- `financial_os_v4/real_economy_bridge.py` — goods decomposition, savings transformer, bank auction, conditional release, orchestration cap.
- `financial_os_v4/investment_bank.py` — risk-adjusted underwriting / NO ACTION gate.
- `financial_os_v4/snapshot_v3.py` — V2 monetary truth + real-economy observability wrapper.
- `simulation/marketplace_investment_bank_bridge.py` — local 100/250/500-cycle research calibration.
- `synergy_pay_system/src/metapay_v2/import_settlement.py` — import invoice batches and exact-destination-currency RFQ with prefund/NDC reservation.

## Prohibited reconstruction

Do not reconstruct any future design where:

- GMV growth directly creates money;
- imported marketplace goods are labelled domestic production;
- an FX conversion of internal units becomes external reserve;
- bank losses are compensated by extra mint and then called bank profit;
- target authorisation is counted as HardNAV;
- a nominal marketplace or bank quote is treated as settled external value.
