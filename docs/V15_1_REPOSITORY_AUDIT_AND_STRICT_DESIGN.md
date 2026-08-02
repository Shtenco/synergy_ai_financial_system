# SYNERGY V15.1 — repository audit and strict external-revenue design

## Scope

This audit reviewed the V14/V15 branch as one accounting and execution system:

- PR #8 and its changed-file set;
- V14 stateful scanner, result and fail-closed interpretation;
- `ExternalRevenueEngineV15`, `SolverAuctionV15` and `PrivateRFQSettlementV15`;
- the Polygon-fork test, runtime patch scripts, validator and workflow;
- the older `OrderflowAuction` and repository order-flow design;
- the relationship between fixture capital, external revenue and consolidated NAV.

The audit does not treat a successful compilation, a positive quote, a synthetic
victim, a funded RFQ fixture or a solver's own payment as proof of market edge.

## V14 baseline retained

V14 remains the accounting boundary. It proved that the tested QuickSwap-only
managed gradient did not produce a strict closed-loop profit across the selected
100-block range. The best route required at least `0.121799 USDC` of additional
external value to clear the configured profit threshold, approximately
`2.68515 bps` of its forward notional.

V15.1 may supply that value only from independently realized external execution.
It may not revive the V13 independent-snapshot sum or classify protocol-owned LP
redistribution as revenue.

## Critical findings in V15

### A-01 — CI mutates the source under test

The workflow patches the JavaScript test and another Solidity source at runtime.
The committed branch therefore is not the exact source compiled and executed by
CI. In particular, a patch replaces `OrderflowAuction` with `SolverAuctionV15`
and repairs an epoch selected before publication. A checkout without those
patches is not reproducible.

**V15.1 rule:** CI may validate or generate reports, but it may not rewrite source
files before compilation or execution.

### A-02 — the committed auction flow is invalid without its patch

The committed test reads `currentEpoch()` before `publish()`, while the explicit
V15 auction increments the epoch during `publish()`. It later settles the old
epoch. The committed test also deploys `OrderflowAuction`, although its helper is
written for the explicit-close V15 interface.

**V15.1 rule:** the checked-in test must be directly executable.

### A-03 — the pinned-venue patch is not executed by the workflow

The branch contains `patch_external_revenue_v15_pinned_venue.py`, but the current
V15 workflow neither invokes it nor lists it among trigger paths. The latest
"pinned venue" commit therefore does not change the tested program.

### A-04 — the victim transaction is manufactured

The fork test creates a very large USDC swap solely to manufacture a price shock,
then reports the resulting backrun as external edge. This proves conditional
execution mechanics, not historical or live order-flow availability.

**V15.1 rule:** synthetic-victim tests receive only `STRUCTURAL_PASS`. Economic
`PASS` requires replay of an actual historical Polygon transaction from a fork
at the preceding block, or separately authenticated live private order flow.

### A-05 — fixture funding removes assets from real LP contracts

The test impersonates real QuickSwap pair contracts and transfers their token
balances to test actors. Even when the donor pair is not the selected execution
venue, this is not independent funded capital and mutates fork state without a
market transaction.

**V15.1 rule:** fixture funding must be disclosed, excluded from NAV and must not
be represented as revenue. Strict economic evidence records the funding source
and verifies that principal, fixture injection and profit are separate.

### A-06 — private RFQ profit is chosen by the test

The three RFQ amounts are constructed from the desired profitable output, and
the best maker deliberately supplies the largest subsidized quote. This is a
valid RFQ settlement unit test, but not evidence that such a quote existed.

**V15.1 rule:** simulated RFQ revenue is reported separately and is never included
in strict external NAV. Counted RFQ revenue requires an authenticated quote with
maker identity, expiry, signature, funded inventory and reproducible provenance.

### A-07 — solver auction revenue is economically circular

The test's own funded signers pay 0.3 POL to treasury. The engine sends all route
profit to treasury and returns only principal to the winner, so the winning
solver pays the bid and gas while retaining no route profit. Such a solver is not
rational, and its own payment cannot prove external demand.

**V15.1 rule:** solver bonds are refundable security, not revenue. The winning
solver bids a treasury share of realized route profit and retains the remainder.
Strict evidence requires both treasury net revenue and positive winner net PnL
after its execution gas.

### A-08 — auction settlement contains a refund-loop denial of service

`SolverAuctionV15.settle()` loops through all losing bidders and reverts when any
refund receiver rejects native currency. One malicious bidder can block the
auction.

**V15.1 rule:** all refunds use pull payments. Settlement has no unbounded external
call loop.

### A-09 — auction terms are not bound to engine execution

The V15 engine checks the winning hash but does not enforce the auction's
`maxInput`, published minimum profit or venue commitment against the execution.
The route hash also lacks the epoch, while a global solution-hash replay map makes
an otherwise identical valid route unusable in later epochs.

**V15.1 rule:** the route commitment includes chain ID, engine, epoch, principal
and every step. The engine independently loads and enforces all opportunity
limits.

### A-10 — the engine is not a multi-DEX graph

V15 hard-codes only V3-to-V2 and RFQ-to-V2 functions. It cannot represent an
N-leg route selected by a graph solver.

**V15.1 rule:** execution uses a bounded sequence of allowlisted adapters. Each
step has exact token-flow accounting and a committed payload hash.

### A-11 — the validator trusts self-declared booleans

The Python validator mainly checks fields written by the test itself, such as
`internalV14LpBalancesTouched: false`. It does not independently recompute these
claims from raw balances, events and receipts.

**V15.1 rule:** the evidence report contains raw integer balances, receipts,
transaction ordering, opportunity terms and profit splits. The validator
recomputes arithmetic and rejects synthetic/RFQ/auction fixture revenue from the
strict total.

### A-12 — GitHub Actions currently fails before runner steps

The latest V10, V13, V14 and V15 jobs all have `steps: null`. This is an external
repository/account runner restriction, not a contract failure. It prevents a new
fork result but does not justify declaring an unexecuted test successful.

## V15.1 architecture

### Solver auction

- bounded opportunity with settlement token, maximum principal, minimum edge,
  minimum treasury revenue, venue-set hash, close block and expiry block;
- refundable solver bond used only for spam/default protection;
- winner selected by the highest treasury share of *realized* route profit;
- pull refunds; no settlement loop;
- unexecuted winning bond can be slashed after expiry;
- the engine is the single-use consumer of the winning solution.

### External revenue engine

- no mint or burn interface;
- no internal SYNA/SYNR LP interface;
- bounded route length;
- allowlisted adapter code hashes;
- exact token-in and token-out deltas on every route step;
- route commitment includes epoch and complete step payload hashes;
- principal returned to the solver;
- realized profit split between treasury and solver according to the auction;
- auction terms independently checked by the engine;
- no pre-existing engine balance may be classified as route output.

### Adapters

V15.1 supplies adapters for:

- Uniswap-V2-compatible routers, including QuickSwap V2;
- Uniswap-V3-compatible exact-input-single routers;
- maker-signed private RFQ settlement.

Additional DEX families can be added as adapters without weakening the engine's
accounting boundary.

## Evidence classes

### `STRUCTURAL_PASS`

Allowed for a deterministic fork fixture with an explicitly synthetic victim or
simulated RFQ. It proves execution order, route accounting, replay protection,
profit splitting and invariant enforcement. It does not prove available edge.

### `HISTORICAL_EDGE_PASS`

Requires all of the following:

1. fork starts at the block immediately before a real Polygon victim transaction;
2. original sender, target, calldata and value are replayed without changing the
   economic contents of the transaction;
3. victim and backrun execute in the same mined fork block in that order;
4. the route uses real deployed DEX contracts from at least two venue families;
5. strict counted revenue excludes fixture capital, simulated RFQ value and
   refundable solver bonds;
6. treasury revenue after attributable protocol/solver gas is at least
   `0.121799 USDC`;
7. winning solver net PnL after its execution gas is positive;
8. route edge is at least `269 ppm`;
9. all V14 internal LP and synthetic-supply invariants remain untouched;
10. an independent validator recomputes the result from raw integer evidence.

If no historical transaction passes, the correct result is
`NO_HISTORICAL_EDGE_PROVEN_IN_RANGE`, not a fabricated PASS.

## Production exclusions

Even a historical fork pass is not a production security audit or a guarantee of
future profitability. Live deployment still requires governance delay, adapter
review, oracle/risk limits, private inclusion integration, key management,
monitoring, independent audit and capital-at-risk limits.
