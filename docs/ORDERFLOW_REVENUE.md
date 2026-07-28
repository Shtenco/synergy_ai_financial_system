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
