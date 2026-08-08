# SynthL1 V5.2 economic audit

## Verdict

The recursive mechanism is mechanically coherent after the V5.2 hardening, but its economic role must remain precise:

`initial internal USDx QE -> CORE buyback/burn -> protocol-owned graph wedge -> executor-gated searcher arbitrage -> adaptive tax on realized arb profit -> captured USDx -> reinvestment -> next pulse`

This first layer is an **MEV/LVR recycler and liquidity-gradient engine**. It is not, by itself, a source of positive external value.

A second independent layer is required for positive hard edge:

`external graph mispricing + solver-auction bids + bridge/public-flow fees + other hard-asset revenue`.

The strongest design is therefore not “maximize wedge”. It is “maximize externally funded edge subject to solver incentive, USDx solvency and CORE-liquidity runway”.

---

## 1. Two NAVs are required

### Hard CNAV

The strict solvency metric remains:

`HardCNAV = real hard assets - externally held USDx liabilities`.

Internal CORE marks, internal LP marks and self-created wedges do not increase HardCNAV.

For a fully protocol-owned pulse graph, self-wedge closure increases external USDx liability only by the searcher's retained reward. Captured USDx remains protocol treasury stock.

Ignoring independent external revenue and system-paid costs:

`Delta HardCNAV = - retained searcher reward <= 0`.

### Liquid economic NAV

Hard CNAV is deliberately conservative on assets, but it can hide an important cost: the engine burns protocol-owned CORE inventory.

For risk analysis add a second metric:

`Delta LiquidEconomicNAV = Delta HardCNAV - h * P_CORE_external * CORE_burned`,

where `h` is a haircut from 0 to 1.

This does not assert that burn has zero tokenholder benefit. It simply refuses to assume that reducing supply automatically creates enough externally realizable price appreciation to offset the CORE inventory destroyed.

---

## 2. Exact wedge and CORE-burn equations

For an initially balanced CPMM `R CORE / R USDx`, LP fee `f`, pulse `M`, and `s=M/R`:

`P1/P0 = (1+s) * (1+(1-f)s)`.

The fraction of the target pool's CORE bought and burned by the pulse is:

`BurnFraction = (1-f)s / (1+(1-f)s)`.

With `f=0.003`:

| M/R | Initial wedge | CORE burned from target pool |
|---:|---:|---:|
| 0.2 | 43.93% | 16.62% |
| 0.5 | 124.78% | 33.27% |
| 0.8 | 223.57% | 44.37% |
| 1.0 | 299.40% | 49.92% |
| 2.0 | 798.20% | 66.60% |
| 5.0 | 3491.00% | 83.29% |

Huge wedges are therefore easy, but they consume future graph inventory quickly.

---

## 3. Recursive 15-pool sweep

Reference assumptions:

- 15 protocol-owned CORE/USDx pools;
- each starts at `100 CORE / 100 USDx`;
- LP fee 0.30%;
- realized-profit tax ceiling 99%;
- solver reward floor 0.01 USDx;
- no independent external revenue.

Selected results:

| M/R | Initial wedge | Cumulative recycled tax / seed | Searcher leakage | Total graph CORE burned |
|---:|---:|---:|---:|---:|
| 0.2 | 43.93% | 15.50% | 0.148 USDx | 1.29% |
| 0.5 | 124.78% | 38.63% | 0.296 USDx | 3.16% |
| 0.8 | 223.57% | 59.22% | 0.564 USDx | 4.96% |
| 1.0 | 299.40% | 72.07% | 0.787 USDx | 6.13% |
| 2.0 | 798.20% | 129.83% | 2.685 USDx | 11.49% |
| 5.0 | 3491.00% | 275.27% | 13.931 USDx | 24.24% |

`cumulative recycled tax / seed > 100%` does **not** mean profit. It means the same internal synthetic inventory was captured and reused multiple times while the graph surrendered CORE inventory and solver rent.

### Practical burn-budget result

If policy limits one recursive epoch to roughly **5% of total graph CORE inventory**, the reference geometry places the largest admissible pulse near:

`M/R ~= 0.8`.

That still creates an initial wedge of approximately **223.6%**, while keeping total graph CORE burn near **4.96%**.

This is a much better risk/recycle point than a 500%-of-reserve pulse, which creates a spectacular wedge but consumes roughly one quarter of the entire 15-pool CORE inventory in the recursive sequence.

---

## 4. Why V5.2 uses adaptive realized-profit tax

A large static output toll distorts the marginal arb condition and leaves a no-arbitrage band.

V5.2 instead taxes actual completed route profit:

`G = actualReturnedBase - principal`.

The configured `profitTaxBps` is a maximum tax ceiling.

The executor now also has a protocol-configured solver reward floor `R_solver`.

`Tax = min(maxTaxShare * G, G - R_solver)`.

Therefore:

`SearcherReward >= R_solver`.

This preserves solver participation on later/smaller recursive opportunities better than blindly applying 99% forever.

The reward floor should be updated from L1 gas/risk conditions. It is policy input, not searcher-controlled tax relief.

---

## 5. Auction + tax theorem

Let a self-created wedge offer gross arb rent `G`.

After realized-profit tax, the solver receives `B` USDx. Suppose a competitive solver auction captures a hard-asset bid `A` from that solver.

For a purely self-created wedge with no independent external edge, a rational solver cannot sustainably bid more than its available reward:

`A <= B - gas/risk`.

Protocol HardCNAV changes approximately by:

`Delta HardCNAV = A - B <= 0`.

With perfect competition, `A` can approach `B - gas/risk`, so:

`Delta HardCNAV -> -gas/risk`.

Therefore an auction can convert much of the residual synthetic leakage into external hard-asset revenue, but it still cannot make a closed self-wedge a positive-sum machine.

If the solver also has an **independent external graph edge** `E`, then it can rationally bid from that external surplus as well. That is where positive hard edge can originate.

---

## 6. $5 -> $5.5 target

Geometrically scale the reference `M/R=0.8` system to:

- initial hard capital: `$5`;
- initial pulse: `5 USDx`;
- each pulse pool: `6.25 CORE / 6.25 USDx`;
- 15 protocol-owned pools;
- max realized-profit tax: 99%;
- solver reward floor: `0.001 USDx`.

The model gives approximately:

- cumulative recycled tax: `2.9562 USDx`;
- cumulative externally retained searcher reward: `0.03927 USDx`;
- cumulative CORE burned: `4.6496 CORE`;
- HardCNAV delta from the closed recursive layer: `-0.03927 USD`;
- hard coverage with a $5 reserve remains far above 120% in this isolated fixture.

Therefore a true hard-NAV target:

`$5 -> $5.5`

still requires at least:

`$0.50 + $0.03927 = $0.53927`

of **independent external value**, plus system-paid costs.

If protocol CORE is also treated as liquid economic inventory at `$1/CORE` with only a 25% haircut, the conservative opportunity-cost adjustment adds roughly:

`0.25 * 4.6496 = $1.1624`.

Then the external value required to achieve a +$0.50 liquid-economic-NAV gain becomes approximately:

`$1.7017 + system costs`.

This second number is intentionally conservative and should not be confused with hard solvency accounting.

---

## 7. Critical contract hardening added in V5.2

### Managed LP gate

V5.1 required pulse pools to be 100% protocol-owned, but `GraphPool.addLiquidity()` was public. A third party could add a tiny LP position and permanently DoS the ownership invariant.

V5.2 adds:

- `liquidityManager`;
- `restrictLiquidityProviders`;
- owner-controlled managed-LP mode;
- engine-side verification that the manager equals `protocolLiquidityOwner`.

### Explicit CORE burn budget

Large pulses can silently exhaust graph CORE inventory even if USDx solvency is healthy.

V5.2 therefore requires an explicit `maxCoreBurnPerEpoch` before an epoch can start and reverts any pulse that would exceed it.

### Adaptive profit-tax floor

`GraphArbExecutor` now treats 99% as a maximum, not a mandatory rate. The tax automatically falls when necessary to preserve a configured solver reward floor.

---

## 8. Optimal policy objective

Do not optimize:

`max wedge`.

Do not optimize:

`max cumulative recycled tax`.

Use a constrained objective such as:

`J = ExternalHardRevenue - SearcherRent - SystemCosts - lambda * COREBurnValue - mu * SolvencyRisk`.

Subject to:

- external USDx coverage >= policy floor;
- pulse pool is 100% protocol-owned and LP-gated;
- managed closing direction is executor-gated;
- solver reward >= gas + risk floor;
- cumulative CORE burn <= epoch budget;
- pulse <= quote-reserve risk cap;
- external venue/oracle freshness constraints;
- no internal mark is counted as hard value.

If `ExternalHardRevenue = 0`, the economic optimum of this objective is no self-wedge at all. A nonzero QE pulse is justified only when it unlocks enough independent external revenue, strategic token-supply benefit, or other explicitly valued objective to compensate for solver rent, costs and CORE depletion.

---

## 9. Recommended V5.2 architecture

1. `GraphPolicy` approves an epoch only after risk/solvency/burn-budget checks.
2. `OrderflowAuction` can pre-announce the opportunity and collect external solver bids.
3. `RecursiveElasticEngine` creates the controlled QE/buyback/burn pulse.
4. Managed `GraphPool` closing flow is gated through `GraphArbExecutor`.
5. `GraphArbExecutor` computes actual realized profit and applies adaptive tax.
6. `MEVCaptureReinvestor` receives physical USDx tax.
7. Only that actual USDx balance can fund the next recursive pulse.
8. `SystemAccounting` tracks HardCNAV/coverage.
9. Off-chain audit tracks LiquidEconomicNAV and CORE-liquidity runway.
10. External flash/graph edge and solver-auction payments are the hard-value layer that can make total CNAV positive.

---

## 10. Current status

### Numerically passed

- huge-wedge formula;
- protocol-only recursive tax reuse;
- closed-loop conservation;
- external-principal cap sensitivity;
- adaptive solver reward floor;
- 30% output-toll counterfactual;
- 100% protocol LP accounting requirement;
- dual-NAV audit;
- CORE-liquidity runway / burn-budget analysis;
- scaled `$5 -> $5.5` external-value threshold.

### Contract hardening implemented

- managed LP gate;
- executor-only closing direction support;
- realized-profit tax up to 99%;
- adaptive solver reward floor;
- external USDx coverage floor;
- pulse-size cap;
- explicit per-epoch CORE burn budget;
- physical capture/reinvestment only.

### Still blocked / not yet proven

- Solidity compiler PASS on the branch;
- EVM integration tests for all 10 contracts;
- fork/live external-venue tests;
- full `OrderflowAuction -> pulse -> GraphArbExecutor -> reinvest` integration;
- formal verification of the accounting and ownership invariants.

The GitHub Actions workflow exists, but the current repository runner is failing before checkout/steps begin; this is not evidence of a Solidity compile failure.
