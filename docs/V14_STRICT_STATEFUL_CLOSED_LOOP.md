# SYNERGY V14 — strict stateful closed-loop proof

## Goal

V14 replaces the V13 independent-snapshot sum with one sequential protocol state.
All ten internal LP balances, all synthetic reserve allocations, the treasury and
the gas budget are carried from block to block. A block can change the next
block only through an accepted exact cycle.

## Internal topology

Two managed synthetics are paired with five real liquid assets:

- SYNA/WPOL
- SYNA/USDT
- SYNA/USDC
- SYNA/DAI
- SYNA/WETH
- SYNR/WPOL
- SYNR/USDT
- SYNR/USDC
- SYNR/DAI
- SYNR/WETH

Every pool starts with 5,000 managed synthetic units and liquid depth worth
approximately 5,000 USD at the first tested block. The liquid token amounts are
fixed after initialization; later blocks mark those same amounts at current
oracle prices rather than recreating 5,000 USD of liquidity.

## Fully closed cycle

For managed synthetic S, source asset A and destination asset B:

1. Retarget the synthetic gradient with equal managed burn/mint. Total S supply
   does not change.
2. Temporarily mint q units of S.
3. Swap q S into S/A and extract real asset A.
4. Route A through an exact real Polygon DEX path and receive B.
5. Require the forward output itself to cover the exact B buyback. No reserve or
   treasury subsidy may bridge the buyback leg.
6. Spend the exact required B to buy q S from S/B.
7. Burn the bought q S. Temporary QE supply returns to zero.
8. Burn q S from the source pair and mint q S into the destination pair. The
   target synthetic gradient is restored with zero net supply change.
9. The buyback has added B to the destination LP. V14 temporarily mints an
   independently calculated amount of S, swaps it into S/B to extract exactly
   that added B, and burns the deposited temporary S directly from the pair.
   The destination LP returns to its pre-cycle liquid and synthetic reserves.
10. Require the recovered forward output to cover the exact reverse-route input.
11. Route B through a different exact external path back into A.
12. Restore exactly the A extracted from the source LP. Any reverse-quote
    rounding excess goes to treasury.
13. Deduct conservative gas from the stateful USDT gas budget.
14. Accept only if both LPs are restored, all synthetic supply invariants close,
    the external routes are disjoint, both buyback and reverse route are funded
    atomically, and realized protocol NAV after gas is positive.

The destination buyback is therefore not counted as profit and is not left as a
hidden destination-LP gain. The source extraction is not left as a hidden
source-LP loss. Both internal liquid reserves end an accepted cycle unchanged.

## Realized NAV identity

For an accepted cycle:

`realized delta = forward B value - exact reverse-route B input value + reverse-output excess A value - gas`

This identity is compared against the difference between complete protocol NAV
before and after the applied state transition. Internal synthetic inventory is
not treated as external value.

## External state safety

Historical Polygon blocks do not contain the protocol's hypothetical trades.
V14 therefore applies a fail-closed single-use lock: after an accepted cycle,
every QuickSwap pool used by either the forward route or restoration route is
unavailable for the rest of the 100-block run. Forward and reverse routes must
also be disjoint inside the cycle.

This avoids repeatedly quoting a historical reserve state after the model has
hypothetically changed that same external pool. It is conservative and may
reduce the number of accepted cycles.

## Acceptance gates

An accepted cycle must satisfy all of the following:

- exact forward quote succeeds;
- forward output covers the exact synthetic buyback without treasury subsidy;
- exact reverse input is found by bracketed binary search;
- forward output also covers the reverse-route input after buyback value is
  recycled from the destination LP;
- source liquid amount after cycle equals its amount before cycle;
- destination liquid amount after cycle equals its amount before cycle;
- source and destination k do not decrease;
- managed gradient supply delta is zero;
- temporary QE supply after cycle is zero;
- destination-recycle temporary supply after cycle is zero;
- total SYNA and SYNR reserves are preserved;
- no external pool is reused;
- accounting identity error is within tolerance;
- realized NAV after gas exceeds the configured minimum.

## Output interpretation

Validator PASS means the sequential accounting and stated invariants are valid.
It does not automatically mean an edge exists.

Possible edge statuses:

- `STRICT_STATEFUL_REALIZED_EDGE_FOUND`
- `NO_STRICT_STATEFUL_REALIZED_EDGE_IN_RANGE`

Only `cumulativeRealizedNavUsd` is the V14 cumulative-profit field. V13's sum of
independent best snapshots is intentionally absent.

## Remaining limitation

V14 is a strict stateful shadow backtest, not a transaction-inclusion proof. It
uses historical external pool states as exogenous block snapshots, excludes
used pools after one accepted cycle, and does not prove private bundle inclusion,
competition latency, reorg behavior or production contract security. A later
fork executor should replay accepted V14 cycles atomically against pinned state
and then be independently audited.
