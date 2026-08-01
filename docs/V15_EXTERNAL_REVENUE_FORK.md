# SYNERGY V15 — external revenue engine and Polygon fork proof

## Purpose

V14 proved that a managed internal gradient cannot be counted as realized profit
until the source real asset is bought back and both internal LPs are restored.
Its best closed-loop candidate missed the configured acceptance threshold by
approximately `2.68515 bps`, or `$0.121799` for the tested notional and gas model.

V15 does not relax those gates. It adds an independent external-revenue layer
that may fund the strict V14 closure only after revenue has been realized in a
real settlement asset.

## Components

### 1. Real multi-DEX intrablock backrun

The fork test dynamically finds a liquid pair shared by:

- Uniswap V3 on Polygon; and
- QuickSwap V2 on Polygon.

A funded victim swaps `USDC -> intermediate asset` on QuickSwap V2. Automining is
disabled, and the victim transaction and the winning solver transaction are
placed in the same Anvil block. The solver follows the victim and executes:

`USDC -> intermediate asset on Uniswap V3 -> USDC on QuickSwap V2`

The test rejects the run unless the victim has a lower transaction index than
the backrun. No pre-victim transaction is submitted, so the proof is a backrun,
not a sandwich.

### 2. Solver auction

The existing `OrderflowAuction` contract is reused. Three solvers submit POL
bids against a committed route hash. After settlement:

- only the highest bidder may execute;
- the solution hash is consumed once;
- replay is rejected; and
- the winning POL payment is transferred to treasury.

The fork test wraps the received POL and swaps it through the real QuickSwap V2
`WPOL/USDC` market. Auction revenue is therefore realized as USDC instead of
being counted through an invented mark.

### 3. Private RFQ settlement

`PrivateRFQSettlementV15` implements EIP-712 maker-signed orders with:

- explicit maker and optional taker;
- exact input and exact output;
- expiry;
- maker nonce;
- salt; and
- single-use replay protection.

Three funded makers sign competing quotes off-chain. Only the selected order is
revealed in the fill transaction. Maker inventory is transferred from an actual
token holder present in the pinned fork state; no protocol synthetic token is
minted.

This is a funded private-order simulation on a historical fork. It is not a
claim that the same RFQ was historically available from 0x, UniswapX or another
live market maker.

### 4. External revenue engine

`ExternalRevenueEngineV15` accepts two route types:

- Uniswap V3 to QuickSwap V2 public backrun;
- private RFQ to QuickSwap V2 settlement.

For every accepted route it:

1. verifies the settled solver-auction winner;
2. verifies the committed solution hash;
3. pulls the solver principal;
4. executes the complete external round trip;
5. requires realized output to exceed principal;
6. requires at least `269 ppm = 2.69 bps` external edge;
7. returns the entire principal to the solver;
8. transfers only realized profit to treasury; and
9. consumes the solution permanently.

The contract has no mint or burn function and does not touch V14 internal LPs.

## Fork acceptance gates

The independent validator requires:

- Polygon chain ID `137`;
- a pinned historical fork block;
- deployed code and liquidity at two distinct DEX families;
- victim and backrun in the same block;
- victim transaction index lower than backrun transaction index;
- no sandwich front-run;
- public backrun edge at or above `269 ppm`;
- three solver bids in each of two auctions;
- winning solution consumed once;
- at least three competing RFQ maker quotes;
- RFQ nonce consumed and replay rejected;
- RFQ edge at or above `269 ppm`;
- all recorded actor gas converted to USDC and deducted;
- net external revenue at or above `$0.121799`;
- aggregate net external edge at or above `269 ppm`;
- no protocol synthetic mint/burn; and
- explicit disclosure of simulated private/RFQ components.

## Evidence interpretation

A passing fork test proves that the recorded V15 transactions generated enough
external settlement value under the pinned fork scenario to cover the measured
V14 gap after recorded gas.

It does not prove:

- live private relay inclusion;
- historical availability of the simulated RFQ quote;
- future profitability;
- absence of competing MEV searchers;
- production contract security; or
- audited deployment readiness.

A production adapter may later consume firm 0x Swap API/RFQ quotes or Polygon
UniswapX orders, but those integrations require live credentials, maker access,
latency controls and separate security review.
