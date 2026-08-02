# SYNERGY Bullish Central Bank Microcycle V1

## Tested scenario

Starting capital:

- 1 USDT working capital for the robot and central bank;
- 1 USDT in the initial SYNA/USDT pool;
- 1 USDT gas budget.

One atomic cycle contains:

1. buy SYNA for 0.1 USDT;
2. buy SYNA for 0.1 USDT;
3. five SYNA sales with approximately 0.04 USDT spot notional each;
4. central-bank stabilization after every trade.

The cycle is executed once every ten blocks. Fifteen cycles therefore cover 150
blocks and contain 105 internal trades.

## Bullish central-bank policy

- A decline of at least 1% relative to SMA20 applies a global negative rebase at
  twice the measured decline, capped at 8% per event.
- Growth of at least 1% permits minting at the measured growth rate, capped at 4%.
- Newly minted SYNA is never sold. It may only be paired with accumulated treasury
  USDT and added to liquidity.
- The treasury receives only modeled trade fees.

## Security model

The seven trades and all central-bank reactions execute in one controller-only
transaction. The pool rejects direct public calls. Therefore there is no public
intermediate state between the two buys, five sells and rebases. The implementation
also has:

- zero-reserve and zero-price guards;
- transaction nonce;
- deadline;
- reentrancy lock;
- minimum hard-NAV gate;
- immutable controller binding.

This is stronger than a public router against front-running, but it also means the
pool is not a permissionless market in this test.

## Pinned Polygon fork

The exact Solidity source compiled with solc 0.8.26 and executed on Polygon chain
ID 137 at pinned block 90,790,000. The test used real Polygon USDT state and fork
gas conditions. The 2 USDT fixture was disclosed and excluded from revenue.

Results:

```text
cycles:                              15
covered blocks:                     150
internal trades:                    105
price multiple:                1.674716808605
supply change:                -28.3902552881%
gross TVL:                  2.000000 -> 2.214584 USDT
gross TVL change:                  +0.214584 USDT
organic external TVL change:        0.000000 USDT
external revenue:                   0.000000 USDT
setup gas:                          0.7355360757 POL
15-cycle gas:                       0.2369954440 POL
full gas:                           0.9725315196 POL
fork POL price:                     0.0786846649 USDT
full gas cost:                      0.0765233167 USDT
hard NAV change after gas:         -0.0765233167 USDT
```

The requested 1 USDT gas budget covered the complete deployment and all fifteen
cycles on the pinned fork.

## Economic interpretation

The policy successfully raised the internal SYNA spot price and nominal gross TVL
while reducing total supply. That does not create an external settlement asset.
Robot fees, central-bank balances and the protocol-owned pool belong to one
consolidated owner. Moving USDT among those components cannot increase hard NAV.

Before gas, consolidated hard USDT remained exactly 2 USDT. After full deployment
and cycle gas, total hard NAV fell by 0.0765233167 USDT. The growth in gross TVL is
therefore an internal mark and capital relocation, not external profit.

## Mainnet result

The same workflow proceeded to a distinct mainnet decision stage after the fork.
The strict gate returned:

```text
decision:             SKIPPED_FAIL_CLOSED
reason:               BLOCKED_BY_FORK_ECONOMICS
private key loaded:   false
transaction signed:   false
transaction broadcast:false
```

Mainnet was not attempted because the fork proved zero external revenue and
negative hard NAV after gas. The gate in `scripts/bullish_cb_mainnet_gate.py`
requires positive external revenue, positive organic TVL and positive hard NAV
after gas before any separately reviewed execution adapter may be invoked.

## Immutable evidence

```text
public evidence repository: Shtenco/shtencoauantai.github.io
branch:                     ci/bullish-cb-microcycle
commit:                     a974650c1257f548950189420b7a5799a412ce97
workflow run:               30733951035
workflow job:               91459074673
artifact:                   8828878857
artifact digest:
sha256:f4db4e0189affee35ccb0d328fcb43abf0191cac342cf7a20ee0fdafb5715eef
```
