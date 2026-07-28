# External order-flow revenue

The safe way to monetize external MEV searchers is a disclosed auction, not a
honeypot. `OrderflowAuction` accepts voluntary POL bids for route submission.
The highest bid of each 64-block epoch is paid to treasury after settlement;
outbid solvers can withdraw refunds. `SecureFlashExecutor` accepts only the
settled winning `routeData` hash, then applies policy, oracle, daily-notional,
codehash, repayment, and minimum-profit checks atomically.

This produces two independently measurable external flows:

1. POL voluntarily paid by external solvers for order flow;
2. settlement-token profit from an independently profitable external route.

QE-created discrepancies are admissible only when total protocol-owned pool
loss is included. A route reporting +50 USDT while reducing protocol LP/reserve
LNAV by 60 USDT is rejected rather than reported as profit. Public pools cannot
be made impossible to trade or "drain" while remaining permissionless; reserve
floors and post-total-LNAV checks must be enforced by protocol-owned adapters.

Run `python scripts/run_orderflow_experiment.py`. The deterministic fixture earns
1.38 POL of voluntary bids and 70 USDT of accepted route profit. A third route
with a 10 USDT total-LNAV loss is rejected, while its disclosed auction bid is
still paid under the auction terms. These figures are test inputs, not a
Polygon fork result or a promise of continuous revenue.

## Polygon searcher discovery

Publishing a contract is not enough to create solver participation. Each epoch
is announced during its first eight blocks through `AuctionAnnounced`, containing
indexed settlement/loan tokens, maximum notional, minimum profit, closing block,
venue-set hash, and a metadata URI. Searchers can backfill the event with
`eth_getLogs` and subscribe for new announcements.

After deployment, replace the placeholder in
`solver/auction-manifest.example.json`, host the manifest and referenced metadata
over stable HTTPS/IPFS, verify the contract source, and publish the address in the
project README and searcher channels. Operators can expose a line-delimited JSON
feed with `npm run solver:watch`; searchers reproduce `keccak256(routeData)` and
submit a POL bid with `npm run solver:bid` or call `bid(bytes32)` directly.

There is no protocol-level mechanism that forces existing Polygon searchers to
notice a new auction. Actual participation requires a deployed verified address,
public documentation, reliable opportunity data, competitive economics, and
monitoring. Auction revenue is zero when no external solver bids.
