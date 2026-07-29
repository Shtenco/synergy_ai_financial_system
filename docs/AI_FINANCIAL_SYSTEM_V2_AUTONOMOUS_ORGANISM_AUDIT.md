# AI Financial System V2 — Autonomous Organism Audit

Date: 2026-07-29

Branch reviewed: `feature/qe-mev-revenue-v2`

## Executive conclusion

The current V2 branch is **not yet a proven autonomous financial organism** and is **not mainnet-ready**.

The proposed business model can work only if external solvers receive access to a QE inventory or order that they cannot bypass through unrestricted public pools. If the protocol deliberately creates a stale or discounted public AMM price, searchers can use flash loans and ordinary routers to arbitrage the public pool directly. In that case the protocol does not operate an auction; it exposes its LPs to loss-versus-rebalancing (LVR).

Therefore the required architecture is not:

`public QE price wedge -> hope bots bid`

It is:

`exclusive QE inventory vault -> permissionless sealed solver auction -> atomic settlement -> quote asset to treasury`

A flash loan must be allowed as solver financing, but it must not provide an alternative path to the inventory. The solver may borrow POL or USDT to fund the winning bid; it still has to settle through the auction contract and pay the protocol-defined minimum quote amount.

## Current audit status

| Area | Status | Finding |
|---|---|---|
| QE window definition | Prototype | Bounded windows and discounts exist, but no complete settlement router is committed. |
| Solver registry | Prototype | Bonding and commit/reveal are present. Economic participation is not demonstrated. |
| Oracle guard | Prototype | Freshness and deviation checks exist. Feed selection and manipulation resistance require fork tests. |
| Reserve guard | Failed design | Current guard checks the balance of the guard contract itself, not the treasury, vault, or AMM pair. |
| ExternalMEVRouter | Missing | The branch does not contain the contract that must enforce payment, inventory release, callback, and post-state invariants atomically. |
| EVM integration test | Missing | No committed Hardhat test proves the seven required execution properties. |
| Monte Carlo | Conditional only | It assumes an external annual MEV revenue rate; it does not derive solver participation from market microstructure. |
| Mainnet readiness | No | No Polygon fork, external audit, live solver test, or production oracle validation. |

## Direct-bypass risk

### Why public pools bypass the auction

Assume the protocol publishes a pool price below the external fair price:

- public pool price: `P_pool`
- external fair price: `P_ref`
- `P_pool < P_ref`

Any searcher can:

1. borrow the quote asset through a flash loan;
2. buy the underpriced protocol token directly from the public pool;
3. sell or hedge it at the external price;
4. repay the loan;
5. retain the residual profit.

The searcher has no economic reason to submit a bid to a separate auction if the direct path yields a larger net profit.

The protocol LP bears the stale-price loss. Pool fees capture only a fraction of the arbitrage surplus and do not guarantee positive LP economics after LVR.

### Necessary non-bypass condition

Let:

- `I_QE` be the QE inventory;
- `A` be the auction settlement contract;
- `Q_min` be the minimum external quote payment;
- `B_solver` be the solver bond;
- `V_before`, `V_after` be conservative protocol LNAV before and after settlement.

The required conditions are:

1. `I_QE` is held by a vault and is transferable only by `A`.
2. There is no public AMM route that can withdraw `I_QE` at the auction discount.
3. `quote_received >= Q_min` before inventory is released.
4. Settlement is atomic: payment, inventory transfer, callback, and invariant checks occur in one transaction.
5. `V_after >= V_before + required_profit`.
6. Protected quote reserves cannot decrease.
7. Failed settlements revert completely.

Under these conditions, a flash loan becomes a funding source for a legitimate auction bid rather than a bypass.

## Recommended architecture

### 1. QE Inventory Vault

The protocol mints or deposits the bounded QE inventory into a dedicated vault.

The vault must:

- expose no unrestricted swap function;
- authorize only the settlement router;
- apply a per-window inventory cap;
- prevent governance from changing the receiver or price during an active settlement;
- emit complete accounting events.

### 2. Signed intent instead of a public stale price

Each QE window should be represented as an EIP-712 signed intent:

- base token;
- quote token;
- maximum base inventory;
- minimum quote amount;
- auction start and expiry;
- oracle reference;
- maximum deviation;
- protocol fee;
- settlement contract;
- nonce.

This is an inventory sale or RFQ intent, not a public AMM mispricing.

### 3. Permissionless solver competition

Solvers submit bids for the right to settle the intent. A bid should specify at minimum:

- quote amount paid to treasury;
- base amount requested;
- settlement deadline;
- route commitment;
- solver address;
- bond reference.

The winner is the valid bid maximizing conservative protocol surplus, not necessarily the bid with the largest nominal volume.

### 4. Sealed or private order flow

Publishing the complete route and winning transaction in the public mempool allows copying and sandwiching. Use one or more of:

- commit/reveal;
- encrypted or private bid transport;
- batch auction with delayed revelation;
- Polygon Private Mempool for the winning settlement transaction;
- multiple private relays with fallback and liveness monitoring.

Private submission protects execution but does not replace the economic auction.

### 5. Atomic settlement router

`ExternalMEVRouter.sol` must perform the following sequence atomically:

1. authenticate the solver and commitment;
2. consume a valid QE window;
3. validate oracle freshness and reference deviation;
4. snapshot treasury, vault, and protected pool state;
5. pull the solver's quote payment;
6. send the protocol fee and sale proceeds to treasury;
7. release only the purchased QE inventory;
8. invoke the optional solver callback;
9. verify all protected reserve and LNAV invariants;
10. revert the entire transaction on any failure.

No external call should occur before the necessary state is locked and payment is secured. Reentrancy protection and checks-effects-interactions are mandatory.

### 6. Public pools are hedging venues, not QE giveaway venues

Public pools can remain available for ordinary trading, but:

- QE discount inventory must not be injected as a stale-price gift;
- treasury-owned LP must have daily loss and oracle deviation limits;
- liquidity changes must be policy-bound and timelocked;
- pool fee revenue must be compared against realized LVR;
- consider an auction AMM or LVR-reducing design for treasury liquidity.

## Will solvers participate?

Participation cannot be guaranteed by a contract or Monte Carlo assumption.

A rational solver participates when:

`expected external hedge value - winning payment - gas - flash fee - execution risk - capital cost > 0`

Participation becomes more likely when:

- access to the QE inventory is exclusive;
- the opportunity is large enough after all costs;
- bidding and simulation APIs are public and deterministic;
- settlement is atomic;
- losing bids are inexpensive;
- bonds are not excessive;
- route privacy prevents copying;
- the protocol has reliable uptime and sufficient inventory;
- solver payments and refunds are transparent.

Before mainnet, the protocol must run a public testnet solver program and measure:

- number of independent solvers per auction;
- bid dispersion;
- fill rate;
- protocol surplus captured versus theoretical surplus;
- solver concentration;
- failed settlement rate;
- latency;
- direct-pool arbitrage attempts;
- private relay failure rate.

A minimum launch gate should require at least three independent production solvers and no single solver exceeding 50% of fills over the test period.

## Existing public auction mechanisms

There is no universal Polygon chain-level standard that automatically forces MEV bots into a protocol auction. There are, however, established public protocol mechanisms.

### CoW Protocol

CoW Protocol uses permissionless fair combinatorial batch auctions. Off-chain intents are aggregated and solvers submit competing bids. The winning combination maximizes user surplus subject to fairness constraints.

Official documentation:

- https://docs.cow.fi/cow-protocol/concepts/introduction/fair-combinatorial-auction
- https://docs.cow.fi/cow-protocol
- https://api.cow.fi/docs/

This is the closest established model to the required solver competition. Deployment and custom-inventory support on the target Polygon environment must be verified before relying on it.

### Flashbots MEV-Share

MEV-Share is an open-source orderflow auction. Applications selectively reveal transaction information to searchers; searchers submit backrun bundles; the node simulates bundles and enforces a refund share to the orderflow originator.

Official documentation:

- https://docs.flashbots.net/flashbots-mev-share/introduction

The official documentation is Ethereum-focused and currently states that MEV-Share nodes accept backruns. It should not be treated as a Polygon-native auction without a separately verified deployment.

### 1inch Fusion / resolver competition

1inch Fusion uses resolvers competing to fill maker orders and cover gas. 1inch also documents Polygon support and an OTC mode with exclusive PMM liquidity access.

Official documentation:

- https://help.1inch.io/en/articles/6200682-why-is-using-1inch-better-than-a-dex-like-uniswap-or-pancakeswap
- https://help.1inch.io/en/articles/5306293-what-are-otc-transactions-and-how-do-they-work-on-1inch-network

A custom protocol integration, resolver admission, fee capture, and current Polygon feature availability require direct verification with 1inch. General dApp network support does not automatically mean every Fusion integration feature is permissionless on Polygon.

### Polygon Private Mempool

Polygon announced a private transaction submission endpoint in April 2026 to protect transactions from frontrunning and sandwich attacks.

Official source:

- https://polygon.technology/blog/polygon-launches-private-mempool-mev-protection-is-now-a-one-line-integration

This is execution protection, not an orderflow auction. It is useful for submitting the winning settlement privately, but it does not create solver competition or guarantee protocol revenue.

## Mathematical accounting model

Define conservative external LNAV as:

`LNAV_t = external quote assets + externally redeemable reserves - enforceable external liabilities`

For one period:

`LNAV_(t+1) = LNAV_t + auction payments + protocol fees + external yield - gas - hedging losses - attack losses - operating costs`

Minted SYNA or SYNR is not revenue. Internal price marks are not revenue. A solver payment is revenue only when an externally redeemable quote asset is transferred into protocol-controlled custody and remains available after all obligations and settlement costs.

The protocol is economically self-financing only if the long-run external inflow exceeds all losses and costs:

`E[auction payments + fees + yield] > E[gas + hedging losses + attacks + operations]`

## Corrected Monte Carlo results

The committed V2.2 model was independently rerun for 100,000 deterministic seeds over 60 months. It assumes:

- initial reserve: 1,000,000 quote units;
- annual external MEV flow proportional to reserve;
- monthly flow multiplier uniformly distributed from 0.4 to 1.2;
- monthly attack probability: 3%;
- attack loss: 1% to 15%;
- 25% of fee inflow treated as minted-token liability for the equity metric.

Results:

| Assumed annual external MEV flow | P(reserve > initial) | P(equity > initial) | Verdict |
|---:|---:|---:|---|
| 0% | 0.000% | 0.000% | Fail |
| 5% | 68.989% | 55.727% | Fail |
| 10% | 95.444% | 86.924% | Fail |
| 12% | 98.343% | 92.812% | Fail |
| 15% | 99.668% | 97.495% | Fail equity |
| 17.0% | 99.885% | 98.811% | Fail |
| 17.5% | 99.914% | 99.052% | Pass on tested grid |
| 18% | 99.932% | 99.207% | Pass on tested grid |
| 20% | 99.978% | 99.638% | Pass on tested grid |
| 25% | 100.000% | 99.949% | Pass on tested grid |
| 30% | 100.000% | 99.997% | Pass on tested grid |

These numbers are conditional model outputs. They do not prove that the protocol can generate 17.5% annual external MEV revenue. The model currently inserts that revenue rate exogenously instead of deriving it from order volume, price dispersion, solver bids, fill probability, gas, flash-loan costs, competing venues, and direct bypass.

## Test integrity finding

The current `tests/test_mev_revenue_engine.py` is not a simulation test. It assigns the values `0.04694`, `1.0`, and `0.99994` as constants and asserts them. It also states that a Hardhat file covers EVM execution, but no such integration test is present in the reviewed branch.

Therefore those assertions must not be cited as proof. Replace them with:

- deterministic unit tests of accounting functions;
- an explicit Monte Carlo validation script that computes results;
- EVM integration tests for payment, inventory release, callback, treasury fee, oracle rejection, drain rejection, and slashing;
- Polygon fork tests against deployed token and AMM bytecode.

## Critical remaining risks

### Critical: auction bypass

If QE inventory is exposed through a public pool at a stale price, direct arbitrage bypasses the auction.

### Critical: missing settlement router

Without a committed atomic router, payment and reserve invariants are architectural statements rather than executable guarantees.

### Critical: reserve guard targets the wrong account

The current guard records and checks the token balance of its own address. Unless protected assets are actually held by the guard, it cannot protect the treasury or AMM pair.

### Critical: simulation assumes revenue

The Monte Carlo model assumes the external MEV rate that it is supposed to demonstrate.

### High: oracle manipulation

A single spot feed, stale update, low-liquidity TWAP, or compromised feed can authorize inventory sale below fair value.

### High: toxic flow and adverse selection

Solvers participate exactly when the protocol price is favourable to them. Without competitive bidding, they capture the surplus and the protocol may retain only a small fee.

### High: solver concentration and censorship

A dominant solver or relay can reduce bids, delay fills, or censor competitors.

### High: governance abuse

Governance could create malicious windows, replace feeds, change routers, or release inventory unless changes are timelocked and bounded.

### High: token liability uncertainty

Minted tokens may represent a future redemption, buyback, governance, or market-support obligation. Counting only 25% as liability is an assumption, not an accounting fact.

### Medium: liveness

Private relays, oracles, resolvers, or settlement infrastructure may fail. The protocol needs cancellation and safe fallback paths.

## Mainnet launch gates

The system must not be called an autonomous financial organism until all gates pass:

1. Commit and review `ExternalMEVRouter.sol`.
2. Replace `ProtectedReserveGuard.sol` with account-aware and pair-aware guards.
3. Add complete Hardhat integration tests.
4. Add fuzz tests for reentrancy, fee-on-transfer tokens, rebasing tokens, callbacks, duplicate settlement, and oracle edge cases.
5. Run a pinned Polygon archival fork.
6. Integrate Polygon Private Mempool or another verified private path for winning settlements.
7. Run a public testnet solver competition with at least three independent solvers.
8. Demonstrate that direct public-pool bypass is impossible for QE inventory.
9. Derive revenue from measured bids and fills rather than an assumed annual percentage.
10. Obtain independent smart-contract and economic audits.
11. Operate a capped mainnet pilot with daily loss limits and emergency pause.
12. Recompute LNAV and liability metrics from live on-chain data.

## Final classification

Current classification:

**Experimental solver-auction architecture with conditional positive economics.**

Not yet demonstrated:

**Autonomous financial organism.**

The core concept remains viable if QE is implemented as an exclusive, bounded inventory auction. It is not viable as a deliberately mispriced unrestricted AMM pool. The latter invites direct flash-loan arbitrage and transfers value from protocol LPs to searchers.
