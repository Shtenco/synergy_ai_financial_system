# SINERGY Financial OS — RAG Architecture Center V4

**Status:** CANONICAL / FEATURE-BRANCH REFERENCE  
**Branch:** `feat/financial-os-v4-20260809`  
**Rule:** legacy documents remain historical evidence. This file defines the preferred interpretation for new agents and code on this branch.

---

## RAG PRIORITY

When retrieved concepts conflict, prefer in this order:

1. hard accounting invariants;
2. externally settled evidence;
3. current branch schemas and tests;
4. current architecture documents;
5. historical simulations;
6. speculative token-price mechanics.

Never revive a historical mechanism merely because it produced a visually attractive price, TVL or market-cap path.

---

## ONE-SENTENCE DEFINITION

SINERGY is a programmable financial operating system that separates capital, reserve and transaction money; connects savings duration to productive/P2P credit; routes value across fiat, CBDC and crypto rails; and constrains issuance, investment and profit distribution by consolidated external balance-sheet truth and hard risk invariants.

---

## CANONICAL TAGS

`#HardNAV` `#TripleMoney` `#SYNA` `#SYNR` `#SYNT` `#MetaPay` `#Savings2to5`  
`#Vesting1to100` `#P2P` `#ProductiveQE` `#QT` `#Insurance` `#FirstLoss`  
`#Gesell` `#BoundedRL` `#AI-Central-Bank` `#ConsolidatedLedger`  
`#ExternalProfitOnly` `#MaturityMatching` `#ProfitWaterfall` `#MEVCapture`  
`#MultilateralNetting` `#CBDC` `#Interledger` `#Mojaloop` `#ISO20022`

---

# 1. MONETARY CONSTITUTION

## 1.1 Capital != Reserve != Money != Credit

- `SYNA` = CAPITAL / EQUITY / GOVERNANCE / UPSIDE / JUNIOR RISK.
- `SYNR` = RESERVE / SAVINGS CAPITAL / BASKET NAV / COLLATERAL / INSURANCE CAPITAL.
- `SYNT` = TRANSACTION MONEY / UNIT OF ACCOUNT / SETTLEMENT LIABILITY.
- Credit = temporary balance-sheet asset/liability, not permanent fourth speculative money.
- `SYNR-X` = optional technical inter-system clearing unit; not required to be retail money.

A single token must not simultaneously promise stable redemption, investment upside, reserve backing and credit elasticity.

## 1.2 Value first -> reserve -> emission

Preferred order:

```text
verified external value
 -> reserve / performing asset
 -> allowed liability issuance
```

Rejected order:

```text
mint
 -> internal price increase
 -> higher displayed market cap
 -> claim of new reserve value
```

---

# 2. ACCOUNTING TRUTH

## 2.1 Three NAV layers

```text
HardNAV = hard externally redeemable assets - external liabilities
LiquidNAV = haircut liquid assets - external liabilities
EconomicNAV = haircut economic assets - external liabilities
```

Canonical ordering for public snapshots:

```text
HardNAV <= LiquidNAV <= EconomicNAV
```

Own-token market capitalization is never a hard asset of its own issuer.

## 2.2 Distributable profit

```text
DistributableProfit_t =
max(0, HardNAV_t - HardNAV_(t-1) - NetNewCapital_t)
```

Therefore the following are **not profit** by themselves:

- new participant deposits;
- sponsor capital injection;
- token mint;
- token burn;
- internal rebase;
- own-token market-cap increase;
- virtual reserve increase;
- internal AMM price mark;
- internal treasury transfer;
- flash-loan principal;
- recycled protocol fee that originated inside the same consolidated entity.

## 2.3 Realized external revenue examples

Potential revenue after costs and evidence:

- P2P interest actually paid from external income;
- SaaS / AI Sales / automation revenue;
- merchant/payment fees from independent customers;
- externally realized MIDAS trading PnL;
- externally realized arbitrage after gas/fees/slippage/MEV;
- independent order-flow / solver-auction revenue;
- marketplace/licensing income;
- insurance premium income net of claims and administration.

---

# 3. SYNT — TRANSACTION MONEY

SYNT is deliberately boring money. Primary objectives:

- stable unit of account;
- payroll and merchant settlement;
- P2P-credit denomination;
- escrow;
- subscription and machine-payment settlement;
- reliable redemption rules.

Reference primary mint:

```text
minted_SYNT <= hard_backing_received
```

Reference redemption:

```text
pay external backing -> burn/reduce corresponding SYNT liability
```

Unbacked external SYNT issuance is forbidden in the hard-money reference layer.

---

# 4. SYNR — RESERVE / SAVINGS CAPITAL

SYNR represents reserve/savings capital, not a guaranteed speculative price.

Possible basket components after policy/legal review:

- bank/CBDC cash;
- regulated stable settlement assets;
- short-duration sovereign instruments;
- tokenized high-quality liquid assets;
- haircut BTC/ETH only in non-hard valuation layers;
- performing credit after expected-loss haircut.

SYNR can absorb junior risk before protected transactional money, subject to explicit prospectus/legal design.

---

# 5. SYNA — CAPITAL / UPSIDE

SYNA represents equity-like upside and governance/risk capital.

Its market price may be volatile. It is not the HardNAV anchor for SYNT and should not be the primary collateral for system-issued P2P credit.

System equity logic:

```text
Equity = external assets - senior liabilities - expected losses
```

SYNA market cap is market analytics, not reserve accounting.

---

# 6. SAVINGS 2–5% + DURATION MARKET

Users may route approximately 2–5% of income into savings by choice/mandate appropriate to the product design.

Funding is split across a 1–100 week vesting/maturity ladder.

Vesting is interpreted as **funding duration**, not as a token-price manipulation mechanism.

Canonical rule:

```text
loan_maturity < funding_maturity
```

Rewards can be weighted by amount-duration / token-weeks, but total rewards are capped by actually realized distributable profit.

---

# 7. P2P / PRODUCTIVE CREDIT

Credit principal is denominated in KZT/USDT/SYNT economic value even when technical token transfers are used.

Do not force a borrower to repay a fixed quantity of appreciating SYNA.

Credit capacity is bounded by funding duration, reserve capacity, expected loss, borrower quality and productive demand.

Productive QE envelope:

```text
QE_max = min(
  reserve_capacity,
  liquidity_capacity,
  verified_productive_demand,
  risk_capacity
)
```

Principal repayment reduces the corresponding credit-money liability / drives QT. Collected interest becomes external revenue.

---

# 8. GESELL / DEMURRAGE

Gesell is not interpreted as mandatory decay of every form of wealth.

Preferred SINERGY interpretation:

- optional small countercyclical carry cost on **idle transactional SYNT**;
- protected everyday transaction balance can have zero demurrage;
- savings move to term/SYNR structures rather than being punished;
- capital risk belongs in SYNA;
- collected demurrage can be directed to QT, insurance or reserves under transparent policy.

Do not use sell taxes/demurrage primarily to trap holders and manufacture token price appreciation.

---

# 9. AI CENTRAL BANK

Canonical stack:

```text
Monetary Constitution
 -> deterministic baseline rule
 -> bounded RL residual
 -> hard safety shield
 -> monetary action
```

RL is a residual optimiser, not sovereign authority.

If RL fails or is unavailable:

```text
RL residual = 0
```

and deterministic monetary policy continues.

Core state examples:

- inflation/output/velocity gaps;
- HardNAV coverage;
- LCR;
- NPL/default rate;
- reserve/insurance coverage;
- 1–100 week unlock curve;
- external PnL;
- FX/bridge stress;
- productive demand.

Core action examples:

- demurrage corridor;
- term-savings target;
- credit cap;
- productive-QE cap;
- QT share;
- reserve/insurance targets;
- MIDAS risk cap;
- buyback profit share.

---

# 10. HARD INVARIANTS

The following are hard constraints, not reward penalties:

```text
unbacked_mint == 0
flash_debt_at_commit == 0
loan_maturity < funding_maturity
buyback_budget <= realized_profit_budget
own_token_market_cap not in HardNAV
```

Additional policy floors/ceilings include:

- HardNAV coverage floor;
- liquidity coverage floor;
- NPL ceiling;
- MIDAS max-drawdown kill switch;
- bridge/provider risk limits.

---

# 11. POLICY MODES

`GROWTH`: productive expansion inside verified capacity.  
`NORMAL`: ordinary operation.  
`DEFENSE`: shrink risk, freeze buyback if needed, build reserves.  
`EMERGENCY`: stop new risk creation; prioritise redemption, reconciliation and recovery.

`NO ACTION` is a valid policy decision.

---

# 12. RISK / INSURANCE

Loss types are isolated instead of socialised silently.

Preferred waterfall:

```text
borrower collateral
 -> expected-loss reserve
 -> event-specific insurance
 -> general reserve / SYNR junior capital
 -> sponsor first-loss capital
 -> protected saver capital only as final residual risk
```

Normal MIDAS market drawdown is not an insurance claim.

Insurance covers explicitly defined events such as selected custody, oracle, smart-contract or catastrophic credit events, subject to policy wording and legal structure.

---

# 13. MIDAS

MIDAS is a bounded external-return sleeve, not the entire reserve.

Reference research limits retained from current architecture:

- risk per trade: small fixed fraction;
- daily loss stop;
- max drawdown kill switch;
- no automatic insurance of ordinary trading loss;
- only externally realized post-cost PnL enters distributable-profit accounting.

Internal backtest equity is evidence, not cash.

---

# 14. PROFIT WATERFALL

A waterfall is downstream of realized profit, never a mint schedule.

Example adaptive destinations:

- savers;
- insurance;
- general reserve;
- buyback/burn;
- operator.

Shares can be countercyclical. When reserve/LCR conditions deteriorate, saver/buyback shares may fall and reserve shares may rise.

---

# 15. BUYBACK / BURN

Canonical condition:

```text
BuybackBudget <= RealizedDistributableProfitBudget
```

Burn can redistribute ownership claims among remaining holders but does not create external assets.

Do not burn saver liabilities without simultaneous economic settlement to the beneficiary.

---

# 16. TWO LIFTS — CURRENT INTERPRETATION

Useful interpretation:

- asset lift = hard reserve + realized external profit + haircut performing assets;
- liability lift = outstanding transaction/credit/emission obligations.

Unrealized self-token appreciation cannot close the liability lift.

Historical internal LP burn/mint gradients remain research mechanisms; they are not recognized as guaranteed external profit.

---

# 17. AMM / DEX / MEV

AMM is execution infrastructure, not a wealth generator.

Useful retained concepts:

- graph routing;
- stateful route simulation;
- protocol-owned liquidity funded from real surplus;
- solver/RFQ auctions;
- independent external order-flow capture;
- explicit gas/fee/slippage/MEV accounting;
- skip/no-trade state.

Rejected accounting:

```text
self-created price wedge -> protocol wealth
```

Only consolidated external settlement can establish new external PnL.

---

# 18. FLASH LIQUIDITY

Flash loan = temporary atomic financing.

It is not revenue.

Recognized result:

```text
external assets after operation
- external assets before operation
- flash fee
- gas
- trading fees
- slippage
- hedge/restore cost
```

All flash debt must be zero at accounting commit.

---

# 19. METAPAY

MetaPay is the universal value-routing layer.

User expresses an economic intent, e.g.:

```text
pay 50,000 KZT; recipient wants CNY
```

MetaPay evaluates approved rails such as:

- bank/ISO 20022;
- instant-payment/mobile-money switches;
- CBDC API facades;
- crypto/Lightning;
- Interledger/Rafiki;
- DLT bridge frameworks;
- internal SINERGY ledger.

Route score includes normalized economic cost, failure risk, latency, staleness, compliance and capital cost.

Fees in different currencies must be normalized to one numeraire before comparison.

---

# 20. CLEARING / NETTING

Gross transfers should be netted before expensive final external settlement where legally/operationally permitted.

Net positions remain real obligations.

Do not add nominal KZT + USD + CNY amounts as if they shared one unit. Netting metrics are computed per asset or after explicit FX normalization.

`SYNR-X` may serve as an internal technical clearing unit, but its existence does not create reserve assets.

---

# 21. CANONICAL SNAPSHOTS

`financial_os_v4.snapshot.FinancialSnapshot` defines the first branch-level machine-readable accounting snapshot.

A snapshot includes:

- three NAV values;
- hard assets;
- liabilities;
- distributable profit;
- token-layer NAV/coverage;
- policy mode;
- invariant failures;
- monotonically increasing sequence;
- SHA-256 digest of canonical JSON.

Digest != digital signature. Production authenticity requires approved signing/HSM policy.

---

# 22. CROSS-REPOSITORY OWNERSHIP

`ai_financial_system` owns monetary accounting, research policy and invariants.  
`synergy_pay_system` owns MetaPay routing, compliance, readiness and settlement boundaries.  
`synergychain` owns portal/control-plane integration and presentation of signed/read-only state.  
`shtencoauantai.github.io` owns public explanatory surfaces, not authoritative accounting.

The browser must never become the source of HardNAV truth.

---

# 23. SUPERSEDED / REJECTED IDEAS

The following may remain in historical research but must not be silently reintroduced as canonical economics:

- virtual reserves presented as real constant TVL;
- own-token market cap counted as protocol hard wealth;
- mint -> pump -> revalue -> claim profit;
- flash principal counted as revenue;
- permanent artificial price wedge as guaranteed yield source;
- internal triangle flow counted as new external capital;
- own token as principal collateral for own lending system;
- guaranteed participant yield funded from subsequent participants;
- removing saver/LP principal to finance apparent profit distributions;
- buyback financed by protected principal rather than realized surplus;
- assuming an external pool must remain systematically wrong;
- using vesting primarily to trap supply and manufacture price.

---

# 24. RETRIEVAL ANSWER RULES FOR FUTURE AGENTS

When answering about SINERGY economics:

1. identify the balance-sheet entity boundary;
2. identify external assets and liabilities;
3. separate principal, capital injection and profit;
4. separate market price from NAV;
5. state the funding maturity for any loan;
6. state the loss bearer and insurance boundary;
7. refuse to call internal repricing external profit;
8. distinguish research scenario return from verified realized return;
9. preserve historical code instead of deleting contradictory experiments;
10. propose new work in additive branches with tests and explicit invariants.

---

# 25. CORE FORMULAS

```text
HardNAV = HardAssets - ExternalLiabilities

DistributableProfit_t =
max(0, HardNAV_t - HardNAV_(t-1) - NetNewCapital_t)

QE_max = min(ReserveCapacity,
             LiquidityCapacity,
             VerifiedProductiveDemand,
             RiskCapacity)

LoanMaturity < FundingMaturity

Buyback <= RealizedDistributableProfitBudget

RLAction = clip(BaselinePolicy + RLResidual, ConstitutionalBounds)
```

These formulas are architecture guardrails, not promises of return.
