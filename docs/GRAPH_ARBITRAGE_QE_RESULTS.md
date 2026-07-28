# Graph arbitrage and QE results

The modeled contour connects `SYNA/WPOL`, `SYNR/WPOL`, `SYNA/SYNR`,
`SYNA/USDS`, `SYNR/USDT`, `USDS/USDT`, and `WPOL/USDT`. Routes start and end
in USDT, use integer Uniswap V2 reserve arithmetic, include pool fees, include
the stated 40% SYNA/SYNR transfer burn, and repay a 9 bps flash-loan fee.

The optimizer enumerates simple two-to-four-hop cycles and discrete safe input
sizes. It executes only strictly positive net-USDT opportunities. Re-optimizing
after each trade causes realized reserve LNAV to increase monotonically until
the mispricing is closed; it does not promise that a profitable route exists.

## QE scenarios

Minting SYNA or SYNR alone has zero external reserve value. Pairing minted tokens
with USDT, USDS, or WPOL spends external LNAV equal to the paired reserve.
Minting stablecoins is not treated as profit. QE may change relative prices and
create an arbitrage, but if the protocol owns the affected pools the arbitrage
often just moves its own reserves while paying fees and transfer burns.

With a 40% burn on both entry and exit, many token triangles that look profitable
under ordinary ERC-20 assumptions become losses. Production route simulation
must use balance deltas and fee-on-transfer-compatible router calls.

In the checked representative reserves, the taxed contour produced no positive
route at inputs of 10, 50, 100, 500, or 1,000 USDT. Removing the token tax from
the same reserves produced a seemingly profitable
`USDT→WPOL→SYNA→SYNR→USDT` route, demonstrating why ordinary-token simulation
would be a dangerous false positive. A separate deliberately dislocated market
fixture closed after three profitable executions and accumulated 3,008.852150
USDT net of the modeled 9 bps flash premium; this profit came from external
mispricing, not QE.

## Autonomous execution rule

An action is admissible only if conservative post-trade USDT LNAV exceeds
pre-trade LNAV after DEX fees, token burns, flash premium, gas, oracle haircut,
and slippage. Positive historical simulation is not a guarantee of future
profit. Keepers may discover routes, but the on-chain executor must enforce
`amountOut >= principal + premium + minProfit` atomically.

`LiquidityGrowthCycle.executeGraphArbitrage` supplies the non-flash execution
boundary: only controller-approved targets can be called, the route is atomic,
and the settlement-token balance must increase by `minProfit`. A flash lender
adapter must additionally include its principal and premium in that threshold;
it is deliberately not assumed to be profitable by default.
