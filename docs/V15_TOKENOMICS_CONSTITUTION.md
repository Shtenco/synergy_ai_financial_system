# SINERGY V15 — Tokenomics Constitution

This document defines what V15 is economically allowed to call capital, profit, reserve, distribution and monetary expansion.

It is a design constitution, not a promise of returns.

## 1. Hard reserve means external assets only

The V15 hard reserve consists only of externally valuable assets included in `V15EconomicLedger`, for example USDT/USDC/DAI/WETH/WPOL under governance-approved oracle and account configuration.

Own tokens (`SYNA`, `SYNR`, `USDx`, or future native synthetics) are not hard reserve assets.

Even if the product name contains the word "Reserve", an own token remains an internal synthetic for Economic HardNAV purposes.

## 2. Monetary operations

### 2.1 Reserve gradient

Allowed:

`burn delta SYN from source pool + mint same delta SYN to destination pool`.

Invariant:

`Delta total synthetic supply = 0`.

The gradient changes execution geometry only. It is never booked as revenue.

### 2.2 Atomic QE/QT

Optional temporary liquidity may be used only if the exact temporary supply is destroyed before transaction completion.

Invariant:

`S_end = S_start`.

No temporary balance may escape to an external address.

### 2.3 Permanent mint

Permanent synthetic issuance must be explicitly governed by a separate supply policy/vesting purpose.

It must never be triggered merely because own-token market price rose, and it never counts as hard revenue.

### 2.4 Buyback/burn

Buyback/burn is permitted only from distributable hard surplus.

Because the acquired own token has zero hard-asset book value, the hard asset spent is economically a distribution to tokenholders.

## 3. Sources of real protocol revenue

Eligible hard revenue can include only realized external value such as:

- V13/V15 graph value transfer from independent external venue basis;
- independent external arbitrage profit;
- solver-auction bids paid from solver capital;
- public trading fees from independent users;
- bridge/user service fees;
- other externally sourced hard-asset income explicitly identified in the ledger.

Not revenue:

- own-token mint;
- own-token burn;
- synthetic lock;
- self-trading fees;
- internal pool transfer;
- owner capital contribution;
- own-token market-cap appreciation;
- cumulative recycled tax turnover.

## 4. Capital hierarchy

V15 treats hard capital in five economic buckets conceptually:

1. **Liability backing** — assets required to satisfy enforceable claims;
2. **Stress/insurance buffer** — capital needed to preserve K and STS under shocks;
3. **Operating liquidity** — gas, keeper, bridge and execution working capital;
4. **Edge working inventory** — hard assets retained inside protocol-owned graph pools/capture accounts;
5. **Distributable surplus** — residual capital above all preceding requirements and loss carry-forward.

Only bucket 5 may finance tokenholder/project/founder distributions or buyback/burn.

## 5. Operating PnL and physical capital contributions

For performance analytics one may report a capital-flow-adjusted return series. For **distributable-profit accounting**, V15 uses a stricter rule.

External contributions must be physically transferred through `V15RevenueRouter` into a router balance that is itself registered as a hard account. The router measures the actually received token amount and values it through `V15EconomicLedger`.

Period distributable PnL therefore begins from:

`DistributionPnL_t = HardNAV_t - HardNAV_(t-1) - PhysicallyVerifiedContributions_t`.

There is deliberately no arbitrary reporter-controlled withdrawal add-back.

A hard withdrawal outside the approved distribution path is a real NAV loss and increases loss carry-forward; it cannot be transformed into accounting profit by reporting a number.

A positive period does not become distributable until historical loss carry-forward is fully recovered.

## 6. Retained allocation and external distribution are different

### 6.1 Retained capital allocation

Examples:

- capture vault -> insurance vault;
- capture vault -> protocol-owned reserve account;
- capture vault -> 100%-protocol-owned managed pool;
- reserve -> execution working-capital account.

These are internal transfers. If every account is consolidated exactly once, they satisfy:

`Delta Economic HardNAV = 0`.

They may alter K/STS/concentration and therefore still require risk checks, but they are not external distributions.

### 6.2 External hard distribution

Examples:

- hard-token holder reward;
- project payment;
- founder/DAO payout;
- own-token buyback from external holders followed by burn.

These send hard value outside the protocol and reduce Economic HardNAV by the hard asset spent.

They therefore consume **distribution headroom**.

## 7. Solvency distribution headroom

A distribution must preserve all capital requirements after the outflow.

Reference capital allocator:

`simulation/v15/capital_allocator.py`

It computes a conservative external-distribution cap from the minimum of:

- base coverage headroom;
- worst stress-scenario STS headroom;
- absolute risk-capital headroom;
- realized profit after historical loss recovery.

Conceptually:

`DistributionCap = min(ProfitAfterLoss, CoverageHeadroom, StressHeadroom, AbsoluteCapitalHeadroom)`.

Post-transfer concentration is a separate hard gate in `V15SolvencyController`.

## 8. Distribution waterfall

The ordering is mandatory:

1. execution/gas obligations already incurred;
2. historical loss carry-forward;
3. required hard reserve top-up;
4. insurance/stress buffer;
5. operating and edge working-capital target;
6. only then optional external distribution.

Possible external allocations from the final residual include:

- SYNA/SYNR buyback/burn;
- holder rewards;
- ecosystem/project funding;
- founder/DAO distributions.

Additional reinvestment is a retained allocation, not an external distribution.

No fixed percentage is constitutional. Percentages must be calibrated from real profitability, stress loss and liquidity data.

## 9. Mode-dependent distribution policy

### GREEN

Distribution may occur only if post-distribution Economic HardNAV, K, STS, absolute risk capital and concentration limits remain valid.

### YELLOW

No discretionary tokenholder/founder/project distribution. Surplus remains reserve/insurance/working capital unless governance explicitly tightens the rule further.

### ORANGE

No distribution and no new risk expansion. Only restore, hedge, repay and risk reduction.

### RED

Emergency only. No distribution, no new gradient, no new QE. Restore/reduce/liability management only.

## 10. Proposed token roles

These are V15 design roles, not hard-asset accounting claims.

### SYNA

Proposed role: governance/growth participation token.

Possible value-accrual channels:

- hard-surplus-funded buyback/burn;
- hard-surplus-funded holder distribution;
- governance utility.

None of these channels is guaranteed and none raises protocol HardNAV by itself.

### SYNR

Proposed role: internal risk-coordination / staking / locking token.

Potential uses:

- long-duration lock incentives;
- governance risk signaling;
- access/priority functions.

SYNR is not counted as hard reserve or primary solvency collateral merely because its name contains "Reserve".

## 11. Locking

Locking does not create HardNAV.

Its legitimate economic effect is to reduce the amount of synthetic supply that can become sellable inside a chosen stress horizon.

Any lock reward must be an accrued liability until paid and must be funded from distributable hard surplus, not implicit mint value.

## 12. Edge attribution

Every profitable V15 route should report at least three quantities:

- `ExternalEdge_0`: same-state/no-gradient baseline;
- `GradientEdge`: realized protocol hard gain with gradient;
- `GradientAlpha = GradientEdge - max(0, ExternalEdge_0)`.

This prevents the protocol from claiming credit for profit that already existed externally.

## 13. Risk-adjusted objective

Safety is not part of a weighted score; it is a hard admissibility condition.

Only among admissible actions may the optimizer rank by:

1. worst-case realized hard gain after uncertainty/cost;
2. solvency buffer;
3. capital efficiency;
4. gradient-initiated alpha;
5. lower turnover.

The correct output is allowed to be `HOLD`.

## 14. Governance constitution

Production governance should enforce:

- timelocked changes to oracle sources, haircuts, K/STS floors and concentration limits;
- independent guardian pause authority;
- no same-block relaxation of a risk parameter and use of the newly relaxed capacity;
- explicit registration of every liability source and hard-asset account;
- immutable exclusion of own synthetics from Economic HardAssets;
- all external capital contributions through the physically verified contribution path;
- all discretionary hard outflows through the revenue/distribution path;
- staged rollout from tiny capital before scale-up.

## Bottom line

V15 tokenomics has one non-negotiable principle:

> synthetic geometry can create execution opportunity, but only external hard value can create economic profit.

Everything else — QE, gradient, locking, buyback, burn, staking and rewards — must respect that accounting boundary.
