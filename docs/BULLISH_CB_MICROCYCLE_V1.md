# SYNERGY Bullish Central Bank Microcycle V1

## Tested scenario

Starting capital:

- 1 USDT for the robot and AI central bank;
- 1 USDT on the stablecoin side of the initial SYNA/USDT pool;
- 1 USDT gas budget.

One atomic cycle contains two SYNA purchases of 0.1 USDT and five SYNA sales with approximately 0.04 USDT spot notional each. The AI central bank stabilizes the pool after every trade. Fifteen cycles cover 150 blocks and contain 105 internal trades.

## Solvency criterion

This version uses one economic criterion only:

```text
solvency margin =
  final(TVL + robot balance + AI-CB balance)
- initial(TVL + robot balance + AI-CB balance)
- full gas cost
```

The system is solvent when the solvency margin is positive.

Definitions used in the fork:

- pool TVL = USDT reserve + SYNA reserve valued at the pool spot price;
- for this constant-product pool, pool TVL is equivalent to `2 × USDT reserve`, apart from integer rounding;
- robot balance = robot USDT + controller-held SYNA valued at the pool spot price;
- AI-CB balance = treasury USDT.

No external-revenue, hard-NAV or organic-TVL test is used in the solvency verdict.

## Bullish central-bank policy

- A decline of at least 1% relative to SMA20 applies a global negative rebase at twice the measured decline, capped at 8% per event.
- Growth of at least 1% permits minting at the measured growth rate, capped at 4%.
- Newly minted SYNA is paired with accumulated treasury USDT and added to liquidity rather than sold.
- The treasury receives the modeled trade fees.

## Pinned Polygon fork result

The exact Solidity source compiled with solc 0.8.26 and executed on Polygon chain ID 137 at pinned block 90,790,000.

```text
cycles:                              15
covered blocks:                     150
trades:                             105
price multiple:                1.674716808605
supply change:                -28.3902552881%

initial TVL:                    2.000000 USDT
final TVL:                      2.214583 USDT

initial robot balance:          1.000000 USDT
final robot balance:            0.991020 USDT

initial AI-CB balance:           0.000000 USDT
final AI-CB balance:             0.000579 USDT

initial total:                   3.000000 USDT
final total:                     3.206182 USDT
gross growth:                   +0.206182 USDT

full deployment + cycle gas:     0.0765233167 USDT
net growth after gas:           +0.1296586833 USDT
```

## Verdict

```text
PASS_SOLVENT
```

The combined growth of pool TVL, robot balance and AI central-bank balance exceeded the complete gas cost by approximately 0.129659 USDT.

The requested 1 USDT gas budget covered deployment and all fifteen cycles.

## Mainnet stage

The workflow entered the Polygon-mainnet decision stage and returned:

```text
solvency metric passed: true
decision: READY_BY_TVL_ROBOT_CB_SOLVENCY_METRIC
private key loaded: false
transaction signed: false
transaction broadcast: false
reason not broadcast: CI_HAS_NO_MAINNET_PRIVATE_KEY
```

Thus the system passed the requested mainnet readiness metric. CI did not possess or load a real mainnet private key, so it did not sign or broadcast a transaction.

## Immutable evidence

```text
public evidence repository: Shtenco/shtencoauantai.github.io
branch:                     ci/bullish-cb-microcycle
commit:                     c159283854f6b7161e925e668b81b0a05f8b959c
workflow run:               30734361826
workflow job:               91460277174
artifact:                   8829028612
artifact digest:
sha256:8cc4c813f82c6a8065c01fb3fa38a4f5b1dd393ed6670986103be84674e89b38
```
