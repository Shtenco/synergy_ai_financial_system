# Graph arbitrage and QE results

The primary experimental contour now disables SYNA/SYNR transfer burning and connects `SYNA/WPOL`, `SYNR/WPOL`, `SYNA/SYNR`,
`SYNA/USDS`, `SYNR/USDT`, `USDS/USDT`, and `WPOL/USDT`. Routes start and end
in USDT, use integer Uniswap V2 reserve arithmetic, include pool fees, include
zero-burn token transfers, and repayment of a 9 bps flash-loan fee.

The expanded graph also includes `USDC`, `DAI`, `WETH`, `WBTC`, `LINK`, `AAVE`,
and `CRV`, connected through stablecoin, WPOL, and WETH edges. The experiment
therefore searches a 12-token contour rather than the original five-token core.

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

## No-burn experiment

Run `python scripts/run_no_burn_graph_experiment.py`. The optimizer uses a wider
1–2,000 USDT size grid, executes the best route, mutates reserves, and repeats
until no route clears the modeled 0.05 USDT gas cost. The report includes every realized
route and cumulative USDT profit. This is an experimental counterfactual: the
deployed V2 tokens still need a migration or owner-exemption change before an
on-chain result can match zero-burn arithmetic.

For the representative fixture, the optimizer executed nine profitable routes
and realized 224.950451 USDT after the 9 bps flash premium and 0.05 USDT gas per
transaction. The first route was `USDT→WPOL→SYNA→SYNR→USDT` with 100 USDT input
and 156.889779 USDT net profit. Repeated execution closed the modeled price
dislocations; this is a finite arbitrage harvest, not perpetual yield.

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
