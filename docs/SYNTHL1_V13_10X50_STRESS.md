# SynthL1 V13.1 — 10 Internal / 50 External Stress Audit

## Purpose

This test restores the original V13 search geometry more closely than the one-synthetic five-pool reference model.

Internal graph:

- 2 controlled synthetic families: SYNA-like and SYNR-like;
- 5 quote assets per family: USDT, USDC, DAI, WPOL, WETH;
- total internal managed pools: **10**.

External graph:

- 5 external venue layers;
- 10 quote-asset pairs per venue;
- total external pools: **50**.

All quote assets are valued with one independent HardNAV mark vector. Each external venue layer is built from one cycle-consistent venue-price vector. Venue layers differ only slightly from one another.

The direct-leg stress engine is in:

`simulation/synthl1/v13_10x50_stress.py`

The full multi-hop stateful graph model remains:

`simulation/synthl1/stateful_gradient_graph_v13.py`

---

## 1. Clean no-gradient hurdle

Each combined route has three 0.30% fee legs:

1. destination quote -> synthetic;
2. synthetic -> source quote;
3. external source quote -> destination quote.

The infinitesimal break-even pair basis is therefore:

`1 / (0.997^3) - 1 = 0.905427%`.

The clean stress fixture intentionally caps the largest true-mark pair displacement at:

**0.800000%**.

Therefore even at infinitesimal size the no-gradient three-leg route is below break-even.

---

## 2. External-only control

The five venue layers use the same directional pattern with amplitudes:

- 0.300%
- 0.325%
- 0.350%
- 0.375%
- 0.400%

This creates true-mark pair basis up to ~0.8%, but the difference between external venues themselves remains small.

The maximum infinitesimal external-only two-venue round-trip multiple, including two 0.30% fees, is:

`0.995999032x < 1`.

So the 50-pool external graph does not contain a free external-only round trip in this fixture.

---

## 3. Stateful gradient rotation result

The optimizer searches:

- synthetic family;
- source asset;
- destination asset;
- external venue;
- supply-neutral gradient shift;
- searcher principal.

Every accepted candidate must have:

`Delta ProtocolHardNAV > 0`.

After every accepted route:

- synthetic gradient is restored/closed;
- quote-side internal reserves are carried forward;
- selected external pool reserves are carried forward;
- solver retained reward is carried forward;
- the entire search space is re-optimized.

The same external state is shared by both synthetic families, so the test cannot double-count external basis by giving SYNA and SYNR separate external markets.

### Grid-density robustness

| Principal grid | Accepted rotations | Protocol HardNAV | Solver reward | Max conservation error |
|---:|---:|---:|---:|---:|
| 40 | 18 | +0.799603299 USD | 0.058941636 USD | 2.36e-14 USD |
| 60 | 17 | +0.810053434 USD | 0.051002852 USD | 4.41e-14 USD |
| 80 | 16 | **+0.837590125 USD** | 0.024935360 USD | 1.53e-14 USD |

The result does not disappear as the principal grid is refined.

---

## 4. Why two synthetics help but do not double value

Under the 0.6%-max-pair reference vector and one shared external graph:

- 1 synthetic family: 4 accepted rotations, about `+0.217476 USD` protocol HardNAV;
- 2 synthetic families: 6 accepted rotations, about `+0.300144 USD` protocol HardNAV.

The 2-synthetic gain factor is about:

`1.38x`, not `2x`.

This is the expected conservation-respecting behavior. A second synthetic family expands the execution geometry and can expose additional profitable rotations, but it cannot duplicate the same external value source.

---

## 5. Basis sensitivity

A fast direct-leg sweep with one synthetic family, shared true marks and 99% realized-profit capture produced:

| Max pair basis | No-gradient executable under 0.001 USD floor | Accepted rotations | Protocol HardNAV |
|---:|:---:|---:|---:|
| 0.0% | no | 0 | 0 |
| 0.2% | no | 0 | 0 |
| 0.3% | no | 0 | 0 |
| 0.4% | no | 3 | +0.025145 USD |
| 0.5% | no | 3 | +0.103497 USD |
| 0.6% | no | 4 | +0.205541 USD |
| 0.8% | no | 8 | +0.430147 USD |

The clean economic conclusion is therefore threshold-like:

- too little external basis -> gradient creates no HardNAV-positive route;
- sufficient but still sub-fee external basis -> gradient activates executable routes;
- optimizer continues until the shared basis is consumed below the HardNAV gate.

The system is explicitly designed to stop rather than force a trade when no positive candidate remains.

---

## 6. Profit-tax sensitivity at 0.6% max pair basis

With 100,000 USD external side depth and 0.001 USD solver floor:

| Realized-profit tax | Accepted rotations | Protocol HardNAV | Solver reward |
|---:|---:|---:|---:|
| 50% | 3 | +0.091297 USD | 0.092016 USD |
| 80% | 3 | +0.114643 USD | 0.072765 USD |
| 90% | 4 | +0.159191 USD | 0.043976 USD |
| 95% | 4 | +0.182448 USD | 0.023524 USD |
| 99% | 4 | **+0.205541 USD** | 0.017172 USD |

The 99% ceiling maximizes protocol capture in this deterministic fixture, but production execution must leave enough absolute solver reward to cover gas, risk and competition.

The contract therefore uses both:

- a maximum percentage tax;
- an absolute solver reward floor.

---

## 7. External-depth sensitivity at 0.6% max pair basis

| External side depth | Accepted rotations | Protocol HardNAV |
|---:|---:|---:|
| 5,000 USD | 3 | +0.017166 USD |
| 10,000 USD | 4 | +0.039016 USD |
| 25,000 USD | 4 | +0.106925 USD |
| 50,000 USD | 4 | +0.162753 USD |
| 100,000 USD | 4 | +0.205541 USD |
| 250,000 USD | 4 | +0.231232 USD |
| 1,000,000 USD | 4 | +0.244082 USD |

The gain saturates as external depth becomes large relative to the internal 100-USD quote side. This is economically sensible: once external slippage is no longer the bottleneck, internal quote depth becomes the limiting resource.

---

## 8. What this does and does not prove

### It does prove in the deterministic model

- supply-neutral gradient initiation can activate a latent external basis below the standalone three-leg fee hurdle;
- two synthetic families expand route geometry without double-counting external value;
- 10 internal / 50 external stateful rotation remains positive under grid refinement;
- conservation holds to floating-point precision;
- the optimizer naturally stops when no HardNAV-positive route remains.

### It does not yet prove

- live Polygon profitability;
- real searcher participation at a 99% tax ceiling;
- gas-adjusted profitability on a specific chain;
- robustness to oracle error / stale marks / adversarial sequencing;
- Solidity/EVM correctness of the latest branch.

Those remain explicit deployment gates.

---

## Bottom line

The strongest corrected V13.1 architecture is:

`SELF-CREATED SUPPLY-NEUTRAL GRADIENT`

`-> ACTIVATE SUB-THRESHOLD CROSS-VENUE BASIS`

`-> EXTERNAL SEARCHER CAPITAL`

`-> REALIZED-PROFIT CAPTURE`

`-> ATOMIC HARDNAV GATE`

`-> RESTORE / REINVEST / ROTATE`

`-> REPEAT UNTIL NO POSITIVE HARDNAV CANDIDATE EXISTS`.

In the clean 10-internal / 50-external 0.8%-basis fixture, the refined-grid deterministic result is approximately **+0.84 USD protocol HardNAV** with no profitable external-only marginal cycle and no profitable no-gradient three-leg route.
