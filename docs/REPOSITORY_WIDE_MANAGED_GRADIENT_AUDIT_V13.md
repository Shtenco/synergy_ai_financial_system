# SYNERGY V13 — repository-wide managed-gradient audit

## Why V10 cannot answer the managed-gradient question

The V10 50-pool scanner reads real QuickSwap V2/V3 states, but it does not execute the protocol architecture stored in the repository.

It models one abstract internal `SYN/USDT` round trip and then requires a public external cycle to pay the complete exact buyback. It does not include:

- the ten protocol-owned internal pools;
- two managed synthetic currencies, SYNA and SYNR;
- burn of synthetic reserve directly from a protocol-owned LP;
- equal mint into another protocol-owned LP;
- pair reserve synchronization after managed burn/mint;
- graph selection of the source liquid currency and the destination liquid currency;
- internal protocol-owned fees as retained LP assets rather than external expenditure;
- the reserve, insurance, gas, backing, liability and V6 reinvestment layers.

Therefore the V10 result `0 profitable blocks / 100` is valid only for the external QuickSwap graph under its simplified one-pool buyback assumption. It is not a test of the complete managed QE/QT gradient system.

## Version history recovered from the repository

### V1 — LP-recycling prototype

`LiquidityGrowthCycle` removed 15% of LP, sent 10% of the LP token to a dead address, used released quote for buyback, minted the governed base token and re-added liquidity.

This burned the LP ownership claim. It did not burn a synthetic reserve token from inside the pair. The deterministic model correctly recorded that repeated LP destruction exhausts protocol LP and does not create external reserve NAV.

### V3 — protected assets and no LP destruction

The explicit 10% LP burn was removed. Codehash allowlists, protected-asset non-decrease checks, post-route settlement profit and a profit tax were added.

### V4 — protocol-owned triangular liquidity

The repository introduced three protocol-owned positions:

- WPOL/SYNA;
- WPOL/SYNR;
- SYNA/SYNR.

External WPOL was split between LP, liquid reserve, insurance, gas and operations. Minted SYNA/SYNR was treated as internal inventory rather than external revenue.

### V5 — restricted representative tokens and compounding

The V5 engine separated original external capital, reinvested external profit and retained external profit. Representative-token transfers were restricted to trusted venues and protocol endpoints. Internal emission remained excluded from revenue.

### V6 — external-profit reinvestment

The V6 controller reinvested verified external reserve-asset revenue after keeper cost and tax. It required an external payer, a passing real-liquidity invariant and unchanged bootstrap capital.

### V7 — six-pool permissioned internal graph

The internal graph became the complete graph over WPOL, USDT, SYNA and SYNR:

- WPOL/SYNA;
- WPOL/SYNR;
- SYNA/SYNR;
- WPOL/USDT;
- USDT/SYNA;
- USDT/SYNR.

V7 charged an `internalValueLoss` to a QE-only distortion and accepted only externally caused graph profit.

### V8 — ten internal pools created, but only one executed

The V8 fork fixture created the complete ten-pool graph over SYN, WPOL, USDT, USDC and WETH. However, the atomic executor received only the SYN/USDT pair address. Its profitable path was:

`SYN/USDT internal -> QuickSwap V3 USDT/WPOL -> QuickSwap V2 WPOL/USDT -> SYN/USDT buyback`.

The other nine internal pools were seeded and committed into `topologyHash`, but were not used by the optimizer or executor. V8 therefore proves a one-internal-pool atomic leg inside a ten-pool topology, not a ten-pool managed-gradient engine.

### V11 — exact one-pool QE/QT closure

V11 implemented temporary mint, internal extraction, real external V3/V2 route, exact buyback, complete temporary burn, liquid-reserve restoration and non-decreasing `k`. It still touched only one internal pair.

### V12 — the actual reserve burn/mint mechanism

V12 implemented the missing operation exactly:

1. burn SYN directly from the protocol-owned SYN/WPOL pool;
2. mint the same SYN amount directly into the protocol-owned SYN/USDT pool;
3. synchronize both pool reserves;
4. temporarily mint SYN to the executor;
5. sell it into the SYN/WPOL pool and extract WPOL;
6. sell WPOL externally for USDT;
7. buy the temporary SYN from the SYN/USDT pool;
8. burn the temporary SYN;
9. burn the newly deposited SYN from the source pool and mint it into the destination pool to restore the target gradient.

Total synthetic supply returned to the baseline after every cycle. This is the repository implementation that matches the managed-gradient description.

## Correct V13 topology

The intended internal graph is not V8's complete graph over one SYN plus four liquids. It is ten protocol-owned anchor pools:

- SYNA/WPOL;
- SYNA/USDT;
- SYNA/USDC;
- SYNA/DAI;
- SYNA/WETH;
- SYNR/WPOL;
- SYNR/USDT;
- SYNR/USDC;
- SYNR/DAI;
- SYNR/WETH.

The external graph contains real pools among the five liquid currencies and may be expanded to additional intermediate assets and DEXes.

## Correct managed cycle

For a selected synthetic `S`, source liquid `A` and destination liquid `B`:

1. QT-burn `g` units of `S` from `S/A`.
2. QE-mint `g` units of `S` into `S/B`.
3. Sync both internal pairs. This creates the managed internal price fork without changing total supply.
4. Temporarily mint `q` units of `S` to the atomic executor.
5. Sell `q S` into `S/A` and extract real asset `A`.
6. Route `A` through real external pools and receive real asset `B`.
7. Buy exactly `q S` from `S/B`.
8. Burn the temporary `q S`.
9. Burn the `q S` deposited into `S/A`, mint `q S` back into `S/B`, and sync. The target gradient is restored for the next cycle.
10. Send the remaining `B` to treasury or V6 reinvestment.

## Accounting identities that V13 must report separately

### Executor wallet profit

`wallet profit = external B received - B used for exact synthetic buyback`

A positive wallet result proves that the managed gradient closed the temporary QE/QT leg. It does not by itself prove consolidated growth.

### Consolidated liquid NAV change

`consolidated delta = external value(B received) - external value(A extracted) - external gas - flash premium - external fees not already included in quotes`

Internal swap fees are retained by protocol-owned LPs. They are not external expenditure and must not be deducted a second time. They still affect the cash needed to close the leg and therefore remain in the exact buyback calculation.

### Solvency state

The test must also report:

- temporary supply after each cycle;
- total SYNA and SYNR supply before/after;
- liquid balance of every internal pool before/after;
- synthetic balance of every internal pool before/after;
- reserve and insurance buckets;
- backing and external liabilities;
- gas coverage;
- consolidated NAV before/after;
- source LP change, destination LP change and treasury change;
- external-pool asset deltas;
- exact accounting identity error.

## Token-control boundary

The protocol can burn SYNA, SYNR or another token whose contract grants it an explicit managed-burn role. It cannot burn native USDT, USDC, DAI, WPOL or WETH from a pair because their token contracts do not grant SYNERGY that authority.

Protocol-owned pools containing those real tokens can still be created. Their real-token reserves can be swapped, withdrawn by burning protocol-owned LP positions, or increased by rebalancing. Direct managed burn/mint applies only to protocol-controlled reserve tokens or to explicitly backed internal wrappers.

## V13 acceptance rule

A cycle is accepted only if all conditions pass atomically:

- wallet buyback closes;
- temporary supply is zero;
- target synthetic gradient is restored exactly;
- all liabilities remain covered;
- reserve, liquidity and gas gates pass;
- consolidated liquid NAV after gas is positive;
- the same external source is not counted twice;
- failed or stale routes revert completely.

This specification supersedes the simplified V10 internal round-trip assumption for managed-gradient research.
