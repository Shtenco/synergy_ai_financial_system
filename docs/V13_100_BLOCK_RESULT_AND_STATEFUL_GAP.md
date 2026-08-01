# SYNERGY V13 — 100-block result and stateful gap

## What the completed V13 run proved

GitHub Actions run `30704838925` completed successfully on Polygon blocks
`91,260,683` through `91,260,782`.

The scanner used:

- 100 consecutive historical blocks;
- 10 protocol-owned internal pools (`SYNA` and `SYNR` against five liquid currencies);
- 50 real QuickSwap V2/V3 pools;
- external routes up to four hops;
- four managed gradient sizes;
- eight temporary QE sizes;
- 17,497,600 internal/path configurations;
- 48,024 exact candidate quotes, reduced to 6,003 unique external quote calls by caching.

Every independent block snapshot had at least one candidate above the configured
`$0.25` consolidated-profit-after-gas threshold.

Independent-snapshot summary:

- accepted snapshots: `100 / 100`;
- sum of per-block best consolidated deltas after gas: `$42.14740836494275`;
- average per-block best consolidated delta after gas: `$0.4214740836494275`;
- maximum per-block consolidated delta after gas: `$0.44701357738724595`;
- maximum executor-wallet result: `$229.243859`.

The dominant accepted configuration was:

- synthetic: `SYNA`;
- source pool: `SYNA/WETH`;
- destination pool: `SYNA/USDT`;
- gradient shift: `1,000 bps`;
- temporary QE size: `1,000 bps`;
- route: mostly `WETH -> USDC (V3) -> USDT (V3)`.

The wallet number is intentionally much larger than consolidated NAV growth.
The source LP loses WETH, the destination LP receives USDT used for exact
synthetic buyback, and the remainder reaches treasury. Only the sum of source LP,
destination LP and treasury is protocol NAV.

## What the run did not prove

The 100 rows are independent historical quote snapshots. The scanner starts every
block from the same internal liquid depth of `$5,000` per pool. It does not carry
the changed protocol-owned LP balances into the next block.

For the accepted rows in run `30704838925`:

- all 100 selected the same source pool, `SYNA/WETH`;
- the independent rows would withdraw a total marked WETH value of
  `$45,330.54469400983` from that one pool;
- that is about `9.0661x` its modeled `$5,000` starting depth;
- the independent rows would add `$44,688.52110000005` to `SYNA/USDT`;
- every accepted row leaves the source pool with less liquid reserve than it
  started with;
- every accepted row reports a final source-pool `k` ratio below `1` after the
  temporary synthetic is removed and the target gradient is restored.

Therefore `$42.1474` is the sum of independent best snapshot deltas. It is not yet
a demonstrated cumulative 100-cycle profit.

## Required V14 stateful proof

A strict sequential proof must:

1. carry all ten internal liquid reserves from block to block;
2. apply each accepted source-LP, destination-LP and treasury delta before the
   next block;
3. carry reserve, insurance, gas, backing and liability buckets;
4. exact-quote any external rebalance needed to replenish a depleted source
   asset;
5. reject a cycle unless the resulting state remains executable and solvent for
   the next cycle;
6. report realized cumulative NAV, not the sum of independent best snapshots;
7. separate mark-to-market gains from fully closed external cycles;
8. preserve full synthetic-supply and temporary-supply invariants after every
   state transition.

## Current honest verdict

- managed-gradient independent snapshot edge: **FOUND**;
- exact temporary QE/QT wallet closure: **FOUND**;
- positive per-snapshot consolidated NAV after gas: **FOUND**;
- stateful 100-cycle cumulative profit: **NOT PROVED**;
- repeatable pool restoration across 100 cycles: **NOT PROVED**.

The new `audit_managed_gradient_v13_statefulness.py` evidence gate records this
distinction explicitly so a snapshot PASS cannot be presented as a stateful
supercycle PASS.
