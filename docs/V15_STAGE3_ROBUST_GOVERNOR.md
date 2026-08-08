# SINERGY V15 — Stage 3 Robust Governor

Status: **overlay hardening / econometric design**. Frozen V13.1 remains unchanged.

## 1. Stage-3 objective

V15 must not maximize nominal wedge, nominal solver profit, or nominal protocol PnL.

The hierarchy is:

1. accounting/supply invariants;
2. Economic HardNAV floor;
3. absolute risk-capital floor;
4. K / STS floors;
5. hard-asset concentration limit;
6. worst-case hard gain after uncertainty and system costs;
7. only then optimize return/capital efficiency.

The optimizer therefore works over the admissible set, not over all imaginable routes.

## 2. New integration corrections

### 2.1 ORANGE direct-searcher bypass closed

`routeSolvent()` is a survival test and may be true in ORANGE. It must not be used as permission for a new V13.1 exploitation.

`V15PostRouteGate` now calls:

`searcherRouteAllowed()`

which is true only when:

`mode in {GREEN, YELLOW}`

and all current portfolio/risk limits pass.

Thus direct calls to frozen `GraphArbExecutor` cannot bypass the V15 action-class policy in ORANGE/RED.

### 2.2 Emergency restore cannot be trapped by low coverage

Frozen `ReserveGradientEngine.restoreGradient()` asks its accounting adapter for coverage before performing the exact synthetic restore.

In a real emergency, coverage can fall below the frozen engine's normal floor, yet restore itself is supply-neutral and moves no hard quote assets.

`V15AccountingAdapter` therefore has an explicit gradient-engine registry:

- before `initializeGradient`, registered engine has `active == false` -> REAL coverage is returned;
- during an already-active gradient, the frozen coverage callsite is `restoreGradient()` -> adapter returns unlimited compatibility coverage so restoration can proceed;
- this bypass is available only to governance-registered gradient engines.

This preserves a critical invariant: **risk deterioration can never trap the protocol inside a synthetic reserve displacement**.

## 3. Absolute capital and concentration limits

Ratios can lie by scale. A system with 200% coverage on one dollar of capital is not institutionally equivalent to a system with 200% coverage on one million dollars.

Stage 3 adds:

`RiskAssets >= MinRiskAssets`

and:

`max_i(RiskValue_i / TotalRiskAssets) <= ConcentrationMax`.

Concentration breach moves the state toward ORANGE rather than pretending the system is fully healthy.

The default concentration cap remains disabled (`100%`) for backwards-compatible tests. Production governance must explicitly choose a lower limit after empirical calibration.

## 4. Robust hard gain

For candidate action `u` and stress scenario `s`:

`DeltaN_s(u) = stressed post-action Economic HardNAV change`.

Uncertainty/cost reserve:

`U(u) = OracleError(u) + ModelError(u) + SystemCost(u)`.

Robust gain:

`G_robust(u) = min_s DeltaN_s(u) - U(u)`.

Risk-expanding actions require:

`G_robust(u) >= G_min > 0`.

A candidate with higher headline profit but negative tail outcome is rejected before ranking.

## 5. Maximin optimizer

Among safe candidates the Stage-3 reference optimizer ranks lexicographically by:

1. largest `G_robust`;
2. largest post-state solvency buffer;
3. largest robust gain / hard turnover;
4. largest gradient-initiated alpha;
5. lowest turnover.

This intentionally differs from `argmax nominal profit`.

Reference implementation:

`simulation/v15/robust_optimizer.py`

## 6. Gradient edge attribution

For the same route/state compute both:

- `DeltaN_gradient` with selected reserve gradient;
- `DeltaN_0` with gradient set to zero.

Define incremental initiated alpha:

`Alpha_gradient = DeltaN_gradient - max(0, DeltaN_0)`.

Activation ratio:

`ActivationRatio = Alpha_gradient / DeltaN_gradient`, when `DeltaN_gradient > 0`.

Interpretation:

- `ActivationRatio ~= 1`: edge was effectively unlocked by V13/V15 gradient geometry;
- `ActivationRatio ~= 0`: route was mostly a pre-existing external opportunity;
- intermediate values separate the two sources.

This metric is mandatory for honest econometric attribution. It prevents a profitable external market state from being mislabeled as protocol-created alpha.

## 7. Gradient-size frontier

`simulation/v15/gradient_frontier.py` explicitly models the searcher's own optimal principal and then scores the resulting protocol gain after:

- 99% realized-profit tax ceiling;
- absolute solver floor;
- oracle-error reserve;
- system cost.

The reference frontier shows the key policy result:

- maximum wedge is not generally optimal;
- very small external basis can produce nominal positive protocol PnL while robust PnL remains negative;
- the optimal gradient tends to rise only as independent external basis grows.

Therefore the V15 coordinator must treat gradient size as a control variable, never as a target.

## 8. 10,000-candidate Monte Carlo governor sanity test

A local Stage-3 randomized stress run generated 10,000 synthetic candidate actions under:

- minimum risk assets = 50;
- maximum single-asset concentration = 80%;
- GREEN K/STS floors = 130%;
- minimum robust gain = 0.01.

Result:

- accepted: 410;
- accepted candidates violating any configured hard constraint: **0**.

Dominant rejection reasons were absolute-capital floor, coverage floor, concentration, STS, then robust-gain floor.

This is a controller sanity test, not evidence of market profitability.

## 9. Buyback/burn accounting correction

Because own synthetics have zero Economic HardAsset value:

`hard asset -> buy own token -> burn own token`

reduces protocol HardNAV by the hard asset spent.

Therefore buyback/burn is economically a **distribution to tokenholders**, not retained protocol profit.

It may be funded only from distributable realized hard surplus and must pass the same post-distribution solvency gate as holder/project/founder payouts.

By contrast:

`capture vault -> 100%-protocol-owned managed pool`

is an internal hard-asset transfer and is HardNAV-neutral.

## 10. Stage-3 go/no-go rule for 10x50 optimizer

The full `2 synthetics x 5 internal pools + 50 external pools` optimizer remains behind these gates:

1. V15 overlay compile passes;
2. V15 EVM tests pass;
3. frozen V13.1 EVM regression passes;
4. emergency restore test passes;
5. post-route GREEN/YELLOW gate test passes;
6. archival Polygon fork passes;
7. only then enable the full graph searcher.

Until then, V15 Stage 3 is an economic/risk overlay and reference optimizer, not a deployment claim.
