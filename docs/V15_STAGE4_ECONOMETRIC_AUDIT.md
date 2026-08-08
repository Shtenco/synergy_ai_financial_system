# SINERGY V15 — Stage 4 Econometric Cross-Layer Audit

Status: deterministic reference/economic validation only. This is not a live-market profitability claim.

## 1. Purpose

Stage 4 checks whether the new institutional layers are mutually consistent:

- solver participation economics;
- large-search model-risk penalty;
- correlated portfolio concentration;
- SYNR-like junior recapitalization;
- drawdown-aware risk budget;
- solvency-derived external distribution headroom.

The goal is to prevent a local optimization in one subsystem from violating the balance-sheet logic of another subsystem.

## 2. Solver market reference

Illustrative solver reservation-cost sample:

`[0.004, 0.006, 0.008, 0.010, 0.012, 0.018, 0.025]`

Four competing solvers and 99% realized-profit tax ceiling.

Reference optimal reward-floor outputs:

| Gross edge | Reward | P(any solver) | Expected protocol capture | Expected capture rate |
|---:|---:|---:|---:|---:|
| 0.020 | 0.010 | 95.94% | ~0.00959 | ~47.97% |
| 0.050 | 0.010 | 95.94% | ~0.03837 | ~76.75% |
| 0.100 | 0.010 | 95.94% | ~0.08635 | ~86.35% |
| 0.250 | 0.012 | 99.89% | ~0.23773 | ~95.09% |

Interpretation: a 99% tax ceiling is useful, but expected capture depends on solver participation. An overly small reward can reduce expected realized revenue even while headline capture percentage looks larger.

## 3. Winner's-curse reference

Gaussian-style reference selection penalty:

`Penalty = sigma * sqrt(2 ln(M/alpha))`

with `sigma = 0.004`, `alpha = 0.01`:

- M=1 -> ~0.012139;
- M=100 -> ~0.017168;
- M=100,000 -> ~0.022711.

Thus the full 10x50 graph cannot use the same model-error reserve as a one-route decision. Searching more candidates raises the required model-risk buffer.

This expression is a reference, not a production theorem; live/fork quote-to-execution errors must replace or calibrate it.

## 4. Correlated portfolio concentration

Reference risk-value portfolio:

- USDT 25;
- USDC 25;
- DAI 20;
- WETH 20;
- WPOL 10.

Largest individual asset = 25%.

But aggregate `stablecoin` risk group:

`25 + 25 + 20 = 70%`.

Therefore a 30% single-asset cap would incorrectly label this portfolio diversified while a 60% stablecoin group cap correctly detects the hidden common-risk concentration.

V15 needs both single-name and correlated-group limits.

## 5. Junior recapitalization reference

Pre-state:

- RiskAssets = 110;
- RiskLiabilities = 100;
- target coverage = 130%;
- contributed hard asset risk factor = 95%.

Required canonical hard capital:

`C = (1.30*100 - 110)/0.95 = 21.052632`.

Post-contribution RiskAssets = 130 and coverage = 130%.

Capital-flow-adjusted operating PnL remains zero.

With:

- existing SYNR supply = 1,000;
- maximum post-raise dilution = 10%;

maximum new SYNR:

`1000 * 0.10/(1-0.10) = 111.111111`.

Therefore minimum clearing price compatible with both the hard-capital target and the dilution cap is approximately:

`21.052632 / 111.111111 = 0.189474 hard units per SYNR`.

Illustrative bids at 0.50 / 0.35 / 0.25 / 0.20 clear the required raise at 0.25, issuing approximately 84.21 SYNR and producing post-raise dilution around 7.77%.

A lower-price-only book that cannot satisfy the capital target inside the dilution constraint fails; it is not reported as a successful recapitalization.

## 6. Drawdown risk budget

Reference state:

- high-water Economic HardNAV = 100;
- maximum drawdown budget = 10%;
- daily loss limit = 5;
- daily loss already used = 1;
- solvency loss headroom = 20.

Remaining action-loss budget becomes:

| Current NAV | Drawdown | Action loss budget |
|---:|---:|---:|
| 100 | 0% | 4 |
| 98 | 2% | 4 |
| 95 | 5% | 4 |
| 92 | 8% | 2 |
| 90 | 10% | 0 |

Thus risk falls with drawdown and reaches zero at the hard drawdown boundary. V15 explicitly rejects martingale-style risk expansion to recover losses.

## 7. Distribution headroom cross-check

Reference:

- RiskAssets = 160;
- RiskLiabilities = 100;
- target coverage = 130%;
- minimum absolute risk capital = 120;
- stress assets = 145;
- stress liabilities = 105;
- target STS = 120%.

Headrooms:

- base coverage: `160 - 1.30*100 = 30`;
- absolute capital: `160 - 120 = 40`;
- stress: `145 - 1.20*105 = 19`.

Therefore external-distribution headroom = 19 before the separate HWM-profit / eligible-revenue constraints.

The binding constraint is correctly the stress scenario, not headline coverage.

## 8. Cross-layer conclusion

The reference calculations are internally consistent:

1. solver economics prevents naive maximization of tax percentage;
2. large search space increases model-risk reserve;
3. group concentration catches risks hidden by single-name diversification;
4. recapitalization requires actual hard capital and is not operating PnL;
5. drawdown reduces risk budget;
6. external distribution is capped by the tightest solvency constraint.

This yields the intended hierarchy:

`SAFETY CONSTRAINTS -> ROBUST EDGE -> CAPITAL EFFICIENCY -> TOKEN DISTRIBUTION`.

The inverse hierarchy (token price / distribution target first) is explicitly forbidden.

## 9. Remaining implementation gates

Before Stage-4 economics may control live capital:

- Solidity compile;
- V15 EVM execution;
- frozen V13.1 EVM regression;
- independent Economic validation-oracle EVM path;
- liability freshness/non-removal EVM path;
- RED restore/guardian tests;
- validated canonical anchor must also be used by production RiskOracle wiring;
- archival Polygon fork;
- then and only then full 10-internal / 50-external optimizer.
