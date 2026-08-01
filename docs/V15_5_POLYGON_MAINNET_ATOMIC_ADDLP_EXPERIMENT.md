# SYNERGY V15.5 — Polygon Mainnet atomic ADDLP micro-experiment

## Scientific question

Can one closed atomic cycle create **real external WPOL surplus** when the cycle contains:

1. Aave V3 `flashLoanSimple(WPOL)`;
2. ADDLP into two protocol-owned QuickSwap V2 pools;
3. a WPOL → xSYNA → WPOL reversible gradient;
4. an xSYNR → WPOL → xSYNR reversible gradient;
5. REMOVE-LP of exactly the liquidity minted by the flash cycle;
6. restoration of both seed LP positions and both pool reserves;
7. repayment of principal plus the actual Aave premium;
8. a strict post-cost edge of at least `2.685148 bps`;
9. reinvestment of 80% of realized net WPOL profit.

The null hypothesis is that internal ADDLP, mint, burn and self-swaps do **not** create external value. Without an independent market edge, the flash transaction should revert.

## Mainnet components

The experiment uses current Polygon PoS addresses pinned in the scripts:

```text
Aave V3 Pool:        0x794a61358D6845594F94dc1DB02A252b5b4814aD
WPOL:                0x0d500B1d8E8eF31E21C99d1Db9A6444d3ADf1270
QuickSwap V2 Router: 0xa5E0829CaCEd8fFDD4De3c43696c57F7D7A678ff
QuickSwap V2 Factory:0x5757371414417b8C6CAad45bAeF941aBc7d3Ab32
Polygon chain ID:    137
```

The deployment script refuses to continue if any address has no bytecode or if the connected chain is not 137.

## Isolation from public users

The contract deploys two explicit test assets:

```text
SYNERGY EXPERIMENT A - NO VALUE / xSYNA-V155
SYNERGY EXPERIMENT B - NO VALUE / xSYNR-V155
```

They can only be minted or burned by the experiment contract. No sale, bridge, public distribution, valuation claim or investor deposit is part of the experiment.

The QuickSwap pairs are protocol-owned test pools. The operator must not invite third-party liquidity or trading.

## Three transactions

### Transaction 1 — deploy

Deploys:

- `MainnetAtomicAddLpExperimentV155`;
- both experiment tokens;
- both QuickSwap V2 pairs.

The constructor verifies the Aave, WPOL, router and factory contracts and verifies that the router points to the expected factory.

### Transaction 2 — seed

`seedPools()` wraps a small amount of native POL into WPOL and seeds both pools. The contract hard-caps total native seed at `2 POL`.

Recommended first experiment:

```text
0.25 WPOL + 1,000,000 xSYNA
0.25 WPOL + 1,000,000 xSYNR
```

The seed LP remains owned by the experiment contract and can be recovered after the experiment. Any seed dust is transferred without being counted as revenue.

### Transaction 3 — one atomic flash cycle

Recommended initial plan:

```text
flash principal:     100 WPOL
ADDLP pool A:         30 WPOL + proportional xSYNA
ADDLP pool B:         30 WPOL + proportional xSYNR
A gradient:            1 WPOL → xSYNA → WPOL
B gradient:   equivalent xSYNR → WPOL → xSYNR
strict net floor:      2.685148 bps after Aave premium
```

The actual Aave premium is read from the Pool and capped in the plan. It is not assumed to equal the earlier synthetic fixed fee of 5 WPOL.

## Binding invariants

The callback rejects the cycle unless all of the following hold:

```text
callback caller == pinned Aave Pool
initiator == experiment contract
asset == WPOL
receiver WPOL before flash == 0
premium <= committed cap
owned seed LP after cycle == owned seed LP before cycle
WPOL reserve of each pool after >= before
experiment-token reserve of each pool after >= before
receiver WPOL >= principal + premium + strict net profit
net edge >= 2.685148 bps
settlement residue after profit distribution == repayment only
```

Therefore a wallet gain financed by protocol-owned LP damage is impossible to accept.

## Atomic rollback

If any invariant fails, the EVM reverts:

- both ADDLP operations;
- all four swap legs;
- both REMOVE-LP operations;
- all temporary mint/burn state;
- Aave premium transfer;
- profit counters and treasury transfers.

The already deployed contracts and seed pools remain, because deployment and seed are earlier transactions. They can be recovered with `recoverSeedLiquidity()`.

## 10 POL risk boundary

The contract checks at the start of the cycle:

```text
gasleft() × effective tx.gasprice <= 9.5 POL
```

The mainnet scripts independently enforce:

```text
actual deployment gas
+ actual seed gas
+ conservatively counted seed capital
+ maximum cycle gas cost
<= 10 POL
```

The extra 0.5 POL margin covers intrinsic gas and estimation error. A disposable wallet should be funded with only the amount approved for the experiment.

A reverted flash transaction does not lose flash principal or pool assets; it loses gas. Seed capital is protocol-owned and recoverable, but the script conservatively counts it inside the 10 POL budget.

## Expected outcome

For newly created isolated pools with no external order flow, the expected result is:

```text
ATOMIC_REVERT_NO_EXTERNAL_SURPLUS
completed cycles = 0
counted revenue = 0
reinvestment = 0
seed pool state = exactly restored
only gas spent
```

A successful receipt would be unexpected and must not automatically be called profit. It must be audited against:

- Aave repayment and actual premium;
- exact reserve and LP restoration;
- pre-funded balance exclusion;
- token-supply changes;
- 80/20 distribution;
- transaction trace and balance deltas.

## Commands

Fork proof:

```bash
POLYGON_RPC_URL=<archive-rpc> npm run test:v15.5:fork
```

Mainnet deploy and seed, from a disposable wallet:

```bash
export POLYGON_RPC_URL=<polygon-mainnet-rpc>
export OWNER_PRIVATE_KEY=<local-disposable-key>
export V155_REINVESTMENT_VAULT=<address>
export V155_RETAINED_TREASURY=<address>
export CONFIRM_V155_DEPLOY=DEPLOY_V15_5_POLYGON_MAINNET
npm run deploy:v15.5:polygon
```

Preflight without broadcasting the expected revert:

```bash
export V155_EXPERIMENT_ADDRESS=<deployed-address>
npm run run:v15.5:polygon
```

Broadcast exactly one expected-revert probe:

```bash
export V155_BROADCAST_REVERT_PROBE=I_ACCEPT_ONE_REVERTING_MAINNET_TRANSACTION
npm run run:v15.5:polygon
```

Never paste the private key into chat, source files, reports or pull-request comments.

## Evidence classification

- Fork PASS: real Polygon state, but no mainnet broadcast.
- Deployment artifact: proves contracts and pools exist, not profitability.
- Reverted mainnet probe: proves atomic rollback and records gas spent.
- Successful mainnet probe: requires a separate strict trace audit before any revenue is recognized.
