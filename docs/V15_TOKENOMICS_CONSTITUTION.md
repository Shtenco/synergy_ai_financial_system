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

## 5. Operating PnL

For period t:

`OperatingHardPnL_t = HardNAV_t - HardNAV_(t-1) - Contributions_t + Withdrawals_t`.

A positive period does not become distributable until all historical loss carry-forward is recovered.

This creates a high-water-mark-like rule without valuing own tokens.

## 6. Distribution waterfall

The ordering is mandatory:

1. execution/gas obligations already incurred;
2. historical loss carry-forward;
3. required hard reserve top-up;
4. insurance/stress buffer;
5. operating and edge working-capital target;
6. only then optional distribution.

Possible downstream allocations from the final residual include:

- additional reinvestment;
- SYNA/SYNR buyback/burn;
- holder rewards;
- ecosystem/project funding;
- founder/DAO distributions.

No fixed percentage is constitutional. Percentages must be calibrated from real profitability, stress loss and liquidity data.

## 7. Mode-dependent distribution policy

### GREEN

Distribution may occur only if post-distribution Economic HardNAV, K, STS, absolute risk capital and concentration limits remain valid.

### YELLOW

No discretionary tokenholder/founder/project distribution. Surplus remains reserve/insurance/working capital unless governance explicitly tightens the rule further.

### ORANGE

No distribution and no new risk expansion. Only restore, hedge, repay and risk reduction.

### RED

Emergency only. No distribution, no new gradient, no new QE. Restore/reduce/liability management only.

## 8. Proposed token roles

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

## 9. Locking

Locking does not create HardNAV.

Its legitimate economic effect is to reduce the amount of synthetic supply that can become sellable inside a chosen stress horizon.

Any lock reward must be an accrued liability until paid and must be funded from distributable hard surplus, not implicit mint value.

## 10. Edge attribution

Every profitable V15 route should report at least three quantities:

- `ExternalEdge_0`: same-state/no-gradient baseline;
- `GradientEdge`: realized protocol hard gain with gradient;
- `GradientAlpha = GradientEdge - max(0, ExternalEdge_0)`.

This prevents the protocol from claiming credit for profit that already existed externally.

## 11. Risk-adjusted objective

Safety is not part of a weighted score; it is a hard admissibility condition.

Only among admissible actions may the optimizer rank by:

1. worst-case realized hard gain after uncertainty/cost;
2. solvency buffer;
3. capital efficiency;
4. gradient-initiated alpha;
5. lower turnover.

The correct output is allowed to be `HOLD`.

## 12. Governance constitution

Production governance should enforce:

- timelocked changes to oracle sources, haircuts, K/STS floors and concentration limits;
- independent guardian pause authority;
- no same-block relaxation of a risk parameter and use of the newly relaxed capacity;
- explicit registration of every liability source and hard-asset account;
- immutable exclusion of own synthetics from Economic HardAssets;
- staged rollout from tiny capital before scale-up.

## Bottom line

V15 tokenomics has one non-negotiable principle:

> synthetic geometry can create execution opportunity, but only external hard value can create economic profit.

Everything else — QE, gradient, locking, buyback, burn, staking and rewards — must respect that accounting boundary.
