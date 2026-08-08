# SINERGY V15 — Stage 4 Capital Stack and Solver Market

Status: **economic/tokenomics design**, layered above frozen V13.1 and the V15 Stage-3 solvency/accounting overlay.

Nothing in this document is a promise of token returns or a claim of live-market profitability.

## 1. Three economically different token roles

### SYNA — residual growth/governance layer

Proposed role:

- governance participation;
- residual ecosystem/growth exposure;
- optional hard-surplus-funded buyback/burn or holder distribution.

SYNA is an own synthetic and therefore contributes **zero** to Economic HardAssets.

Its market-cap appreciation is not protocol revenue.

### SYNR — junior recapitalization / risk-coordination layer

Proposed role:

- junior non-hard-accounted recapitalization instrument;
- risk-governance / long-duration lock coordination;
- possible future discretionary hard-surplus participation.

SYNR is **not** the protocol's reserve merely because its name contains "Reserve".

Minting SYNR internally creates no hard capital.

Only an actual external sale/auction of SYNR for USDT/USDC/WETH/etc. can bring new hard capital into the system.

Those hard proceeds are a **capital contribution**, not operating revenue.

If SYNR is ever given an enforceable hard-redemption promise, the promise must be entered into V15LiabilityRegistry and reduces the recapitalization benefit.

### USDx — monetary/liability layer

Two cases are economically distinct:

1. atomic QE/QT: temporary supply is fully destroyed before transaction completion, therefore no lasting external liability remains;
2. permanent externally held redeemable USDx: the external amount is a hard liability and must be backed/stressed explicitly.

Permanent USDx issuance is never treated as free capital.

## 2. Recapitalization equation

Let:

- `R` = current RiskAssets;
- `L` = stressed/risk liabilities;
- `K*` = target coverage;
- `h` = risk factor/haircut of the contributed external asset;
- `C` = canonical hard capital contribution required.

Then a reference minimum is:

`C_required = max(0, K* L - R) / h`.

Example:

- R = 110;
- L = 100;
- target K = 130%;
- contributed-asset risk factor = 95%.

Then:

`C_required ~= 21.052632`.

After receiving that hard capital:

`RiskAssets = 130`,

`Coverage = 130%`.

The capital-flow-adjusted operating PnL remains zero because the hard inflow is investor capital, not protocol earnings.

Reference implementation:

`simulation/v15/capital_stack.py`.

## 3. Why a redeemable recap token is weaker capital

If the protocol raises hard assets C but simultaneously creates an enforceable hard liability D to the new tokenholders:

`Delta HardNAV = C - D`.

If `D = C`, the raise may add liquidity but does not add net hard equity.

Therefore the strongest recapitalization instrument is economically junior/residual rather than a new hard-redemption liability.

This is a balance-sheet statement, not a legal classification.

## 4. Buyback/burn

For Economic HardNAV purposes:

`hard asset -> externally held own token -> burn`

is equivalent to an external distribution of the hard asset.

If 10 USDC leaves consolidated protocol custody for a SYNA/SYNR buyback:

`Delta HardNAV = -10 USD`

before any unrelated external profit.

The subsequent own-token burn does not restore the 10 hard USD.

Therefore buyback/burn competes for the same external-distribution headroom as holder/project/founder payouts.

## 5. Recapitalization mode policy

### GREEN

No emergency issuance is required. Permanent SYNR issuance should normally remain off unless governance has a separately approved capital-raising purpose.

### YELLOW

Retain surplus. No discretionary hard distribution. A planned hard-capital raise may be prepared but is not automatically required.

### ORANGE

No new edge expansion. A hard-capital recapitalization auction can be economically rational if it improves K/STS and does not create offsetting hard liabilities.

### RED

Recovery only:

- exact gradient restore/close;
- hedge/repay/liability reduction;
- external hard-capital contribution/recapitalization;
- no new searcher edge initiation;
- no external distribution.

A recapitalization auction in RED is a financing action, not trading profit.

## 6. Solver market: 99% is a ceiling, not the objective

Frozen V13.1 implements:

`Tax = min(tau_max * G, G - RewardFloor)`.

This is economically useful because the absolute solver floor can dominate the percentage tax when G is small.

Let:

- G = realized gross arbitrage opportunity;
- R = offered solver reward;
- C_solver = solver reservation cost (gas + failure/reorg/inventory/risk premium);
- N = number of competing independent solvers.

A solver participates only when:

`R >= C_solver`.

Expected protocol capture is approximately:

`E[Capture] = (G - R) * P(at least one solver participates)`.

Therefore maximizing `tau` mechanically is not the same as maximizing expected hard revenue.

Reference implementation:

`simulation/v15/solver_market.py`.

## 7. Illustrative solver-cost reference

Using the illustrative reservation-cost sample:

`[0.004, 0.006, 0.008, 0.010, 0.012, 0.018, 0.025]`

and four competing solvers, the reference optimizer found:

| Gross edge | Solver reward | P(any solver) | Expected protocol capture | Effective expected capture |
|---:|---:|---:|---:|---:|
| 0.020 | 0.010 | 95.94% | 0.00959 | 47.97% |
| 0.050 | 0.010 | 95.94% | 0.03837 | 76.75% |
| 0.100 | 0.010 | 95.94% | 0.08635 | 86.35% |
| 0.250 | 0.012 | 99.89% | 0.23773 | 95.09% |

These values are illustrative outputs of the reference model, not observed Polygon costs.

Policy conclusion:

> keep a high realized-profit tax ceiling, but calibrate the absolute solver reward floor from real execution/reservation data and solver competition.

## 8. Orderflow auction relation

The repository's existing `OrderflowAuction` remains complementary rather than redundant.

A transparent solver auction can:

- improve route competition;
- reveal willingness to pay for access;
- add genuine external bid revenue;
- reduce dependence on a guessed fixed solver reward.

Auction bids are eligible hard revenue only when physically received into an accounted protocol hard-asset account and included in the same HWM/revenue/headroom framework.

## 9. Locking

SYNA/SYNR locking is a risk-management primitive, not hard capital.

Legitimate effects include:

- reducing supply that can become sellable inside a stress horizon;
- governance commitment;
- possible access/reward weighting.

A promised hard lock reward is a liability once accrued.

An own-token reward mint is not hard revenue.

## 10. Capital hierarchy after Stage 4

V15 capital is classified as:

1. external-liability backing;
2. stress/insurance capital;
3. operating liquidity;
4. edge working inventory;
5. retained realized surplus;
6. externally distributable surplus;
7. new investor/recapitalization capital.

Bucket 7 improves balance-sheet capacity but is explicitly excluded from operating performance.

## 11. Non-negotiable accounting identities

### Internal own-token mint

`Delta Economic HardNAV = 0`.

### Supply-neutral gradient

`Delta synthetic supply = 0`,

`Delta Economic HardNAV_gradient = 0` before explicit system cost.

### Junior hard-capital raise

`Delta HardNAV = hard contribution - new hard liabilities`.

Capital-flow-adjusted operating PnL excludes the contribution.

### External buyback/distribution

`Delta HardNAV = - hard assets paid out`.

### Permanent redeemable USDx against equal hard deposit

If hard deposit and new hard liability are equal at canonical value:

`Delta HardNAV = 0`.

## Bottom line

The Stage-4 tokenomics objective is not to make own-token accounting look rich.

It is to create a capital stack where:

- V13.1 generates/activates execution geometry;
- V15 protects hard solvency;
- solver competition determines how much edge can actually be captured;
- SYNR can serve as a junior recapitalization coordination layer only when real hard capital enters;
- SYNA receives residual value only after hard profit exists and solvency headroom permits distribution;
- USDx is treated honestly as either atomic temporary supply or an external liability.
