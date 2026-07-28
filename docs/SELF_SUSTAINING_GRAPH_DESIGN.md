# Self-sustaining graph: executable design and limits

## Four-contract boundary

1. `GraphPolicy` queues an off-chain optimizer's action only when simulated LNAV
   exceeds its baseline, then applies a one-hour timelock and 24-hour expiry.
2. `GraphTreasury` is custody. Only allowlisted modules can consume a policy and
   move or burn exactly its bounded amount.
3. `LiquidityGrowthCycle` executes remove 15%, send 10% LP to the dead address,
   buy back with half the released quote, mint base, and add liquidity.
4. `MEV24hVault` escrows output from integrated routes for 24 hours; an early
   exit sends 40% to the burn sink.

## Accounting result

The integer simulator uses the Uniswap V2 formula with a 30 bps fee and router-
style ratio-limited liquidity addition. Reserves stay solvent and normalized
`k` does not decrease, but repeated 10% LP destruction exhausts executable
treasury LP after 59 cycles in the deterministic fixture. External quote-reserve LNAV does not grow: buybacks,
LP removal, and re-addition merely rearrange existing assets. Minted SYNA/SYNR
must not be counted as free profit because they create a corresponding token
liability/dilution. Burning LP destroys the treasury's claim; it does not free
liquidity.

Consequently, sustainable positive LNAV requires an external yield source such
as real trading fees or independently profitable arbitrage. Flash loans provide
temporary capital, not profit, and must be gated by atomic repayment plus a
post-operation LNAV/min-profit check. No deployment should claim guaranteed
growth or complete MEV protection.

## Fork acceptance gate

Before deployment, pin Polygon block `60000000`, impersonate no production
owner, and assert the real pair token ordering, reserves, router bytecode, token
transfer-tax behavior, role ownership, oracle freshness, slippage, and post-cycle
LNAV. The fork is not reproducible until an archival RPC endpoint is available;
local AMM tests are deterministic but are not a substitute for that fork gate.
