# SINERGY V15 — Formal Mathematical Specification

Status: **mathematical design only**. This branch forks the frozen V13.1 baseline and does not modify V13.1.

V15 = V13.1 supply-neutral edge engine + solvency/risk brain distilled from the older two-contour SINERGY model.

The purpose of this document is to define state, accounting boundaries, admissible transitions and invariants before any Solidity implementation.

---

## 0. Design axiom

V15 is not allowed to recognize wealth merely because the protocol reprices, mints, burns, locks, or redistributes its own synthetic tokens.

A positive economic result exists only when consolidated hard-asset NAV increases after all external liabilities and system-paid costs are included.

---

## 1. Sets and state

Let:

- `H` = set of hard/external assets (USDT, USDC, DAI, WETH, WPOL, etc.);
- `A` = set of protocol synthetics (`SYNA`, `SYNR`, ...);
- `M_a` = managed protocol-owned pools for synthetic `a`;
- `E` = external venue graph;
- `L` = externally enforceable protocol liabilities;
- `S` = stress-scenario set.

For hard asset `i in H`:

- `b_i` = consolidated protocol balance of asset i;
- `p_i` = canonical oracle mark in USD;
- `lambda_i in [0,1]` = static risk haircut;
- `p_i^s` = stressed executable mark in scenario s.

For liability `j in L`:

- `ell_j` = outstanding amount;
- `r_j` = canonical USD redemption/notional value;
- `mu_j^s >= 1` = stress multiplier.

For synthetic `a in A`:

- `S_a` = total supply;
- `x_{a,m}` = synthetic reserve in managed pool m;
- `q_{a,m}` = hard quote reserve in managed pool m;
- `T_a, F_a, K_a, V_a, B_a, O_a` = treasury, free, locked, vesting, bridge and other explicitly enumerated synthetic partitions.

A V15 state is

`X_t = (hard balances, liabilities, synthetic supplies/partitions, managed-pool reserves, external-pool state, oracle state, capture balances, risk state)`.

---

## 2. Two separate NAVs

### 2.1 Economic HardNAV

Unhaircut consolidated hard wealth:

`HardAssets_t = sum_i p_i * b_i`

`ExternalLiabilities_t = sum_j r_j * ell_j`

`HardNAV_t = HardAssets_t - ExternalLiabilities_t`

Own synthetics are assigned zero hard-asset value in this equation.

If an own synthetic carries an enforceable hard redemption promise, that promise is entered on the LIABILITY side instead.

### 2.2 RiskNAV

For every hard asset define a conservative executable mark:

`pRisk_i = min(pOracle_i, pTWAP_i, pExit_i(qStress_i))`.

Then

`RiskAssets_t = sum_i lambda_i * pRisk_i * b_i`

`RiskLiabilities_t = max_s sum_j mu_j^s * r_j^s * ell_j`

`RiskNAV_t = RiskAssets_t - RiskLiabilities_t`.

HardNAV measures economic value. RiskNAV decides whether the monetary engine is allowed to act.

---

## 3. Coverage and stressed solvency

### 3.1 Hard coverage

If external liabilities are non-zero:

`K_hard = RiskAssets / RiskLiabilities`.

If no external liabilities exist, `K_hard = +infinity`.

### 3.2 STS

For stress scenario `s`:

`LiquidHardAssets_s = sum_i lambda_i^s * pExit_i^s(qStress_i^s) * b_i - C_s`

where `C_s` includes system-paid liquidation/gas/bridge costs in that scenario.

`StressLiabilities_s = sum_j mu_j^s * r_j^s * ell_j`.

`STS_s = LiquidHardAssets_s / StressLiabilities_s`.

Global stop-test:

`STS = min_s STS_s`.

No proof may assume a fixed relation such as `freeFloat/collateral <= 1`; every stress input is read from the actual current state.

---

## 4. Synthetic supply-partition invariant

For every synthetic a:

`S_a = sum_{m in M_a} x_{a,m} + T_a + F_a + K_a + V_a + B_a + O_a`.

Every synthetic-holding location must belong to exactly one partition.

Therefore for every state transition:

`Delta S_a = Mint_a - Burn_a = sum Delta(partitions_a)`.

No reward, bridge mint, LP rebalance, vesting unlock or gradient operation may exist outside this ledger.

---

## 5. Supply-neutral reserve-gradient transition

Choose one synthetic `a`, source pool `s`, destination pool `d`, and gradient size `delta > 0`.

Preconditions:

1. both pools are 100% protocol-owned;
2. both pools use the same synthetic a;
3. `0 < delta < x_{a,s}`;
4. liquidity additions are protocol-gated;
5. managed swap directions are executor-gated;
6. all post-transition risk invariants remain admissible.

Transition:

`x'_{a,s} = x_{a,s} - delta`

`x'_{a,d} = x_{a,d} + delta`

`S'_a = S_a`.

All hard quote reserves are unchanged by gradient initiation.

Hence, before system-paid execution costs:

`Delta HardNAV_gradient = 0`.

If source/destination initially have equal synthetic reserve X and comparable quote marks, with `r = delta/X`, the synthetic price-ratio amplifier is

`P_source'/P_destination' = (1+r)/(1-r)`.

The wedge may be large; it is not itself booked as profit.

---

## 6. Searcher exploitation transition

Let the destination quote asset be B and source quote asset be A.

A searcher supplies principal `P` units of B.

Managed route:

`B -> synthetic(destination) -> A(source) -> external graph -> B`.

Let:

- `z` = exact synthetic amount moved from destination to source;
- `Aout` = A withdrawn from source pool;
- `R` = B returned by the external graph;
- `G = R - P` = realized gross arbitrage profit, requiring `G > 0`.

Realized-profit capture:

`Tax = min(tau * G, G - RewardMin)`

`SolverReward = G - Tax >= RewardMin`.

Protocol hard-asset change at canonical marks, before system-paid costs:

`Delta HardNAV_protocol = p_B*(P + Tax) - p_A*Aout - Delta ExternalLiability`.

If this route creates no new protocol liability, the last term is zero.

### Conservation identity

Let the external graph be valued at the same canonical marks.

`Delta NAV_external = p_A*Aout - p_B*(P + G)`.

`SolverRewardUSD = p_B*(G - Tax)`.

Therefore:

`Delta HardNAV_protocol + Delta NAV_external + SolverRewardUSD = 0`.

This identity is a mandatory regression invariant (up to integer rounding and explicitly modeled third-party costs).

It proves that a positive protocol HardNAV transfer cannot be created by self-marking the synthetic. It must be matched by an external counterparty/LP value change or another explicitly modeled external inflow.

---

## 7. Exact synthetic restore after each exploitation

After the searcher moves exact synthetic amount `z`:

`x_{a,s} = x*_{a,s} + z`

`x_{a,d} = x*_{a,d} - z`

where star denotes the gradient target reserves.

Restore transition:

- burn z from source reserve;
- mint z to destination reserve.

Then:

`x_{a,s} -> x*_{a,s}`

`x_{a,d} -> x*_{a,d}`

`Delta S_a = 0`.

Required equality before restore:

`x_{a,s} - x*_{a,s} = x*_{a,d} - x_{a,d}`.

If the equality fails beyond integer tolerance, the operation is inadmissible.

The same active gradient can then be exploited again against the UPDATED external and internal state.

---

## 8. Gradient close / rotation

To close an active gradient of size delta:

`x_{a,d} := x_{a,d} - delta`

`x_{a,s} := x_{a,s} + delta`.

Again `Delta S_a = 0`.

Captured hard quote may be moved between protocol accounts/pools, but an internal transfer must satisfy

`Delta HardNAV_internalTransfer = 0`.

A new `(synthetic, source, destination, delta)` is selected only from the new state.

---

## 9. Optional atomic QE/QT credit contour

Permanent reflexive debt backed only by own synthetic is forbidden from being treated as hard collateral.

V15 may use temporary atomic liquidity `Q` only if:

`TemporaryMint_begin = Q`

and before transaction completion:

`TemporaryBurn_end = Q`.

Hard postcondition:

`S_a,end = S_a,start`.

No temporary-minted balance may remain at an external address or unaccounted protocol address after execution.

The QE amount is bounded by the monetary envelope in Section 10.

---

## 10. Monetary/risk envelope

For candidate action u define independent caps:

- `Q_depth(u)` = maximum size allowed by executable market depth;
- `Q_nav(u)` = maximum size preserving HardNAV lower-bound requirement;
- `Q_sts(u)` = maximum size preserving STS floor;
- `Q_cov(u)` = maximum size preserving hard coverage floor;
- `Q_oracle(u)` = maximum size under oracle-confidence bound;
- `Q_ops(u)` = maximum size under gas/bridge/operational budget.

The action size is bounded by

`Q_max(u) = min(Q_depth, Q_nav, Q_sts, Q_cov, Q_oracle, Q_ops)`.

For a reserve gradient, the analogous bound is

`delta_max = min(delta_depth, delta_nav, delta_sts, delta_oracle, delta_inventory)`.

No cap may be inferred from the synthetic's nominal market capitalization.

---

## 11. Oracle uncertainty and robust acceptance

For a completed route let `Turnover_i` be the absolute hard-asset turnover in asset i and `epsilon_i` its allowed relative oracle error.

A conservative valuation-error bound is

`U_oracle = sum_i epsilon_i * p_i * Turnover_i`.

Let `C_sys` be system-paid gas, bridge, solver-auction, keeper and other hard costs not already included in protocol balances.

The route is acceptable only if

`Delta HardNAV_protocol >= G_min + U_oracle + C_sys`.

A stronger robust form evaluates a finite stress set:

`J(u) = min_{s in S} Delta HardNAV_s(u) - C_sys(u)`.

Execute only when

`J(u) >= G_min > 0`.

This is the core V15 economic gate.

---

## 12. State-dependent K/STS controller with hysteresis

Reference policy constants are parameters, not theorems:

- GREEN: `STS >= theta_G` and `K_hard >= k_G`;
- YELLOW: `theta_Y <= STS < theta_G`;
- ORANGE: `theta_R <= STS < theta_Y`;
- RED: `STS < theta_R` or coverage breach.

Required ordering:

`theta_G > theta_Y > theta_R > 1`.

Hysteresis requires a stricter threshold to move into a safer state than to remain in it.

Permitted action classes:

- GREEN: full bounded gradient + optional atomic QE/QT;
- YELLOW: reduced gradient, no risk expansion above a configured fraction;
- ORANGE: no new temporary monetary expansion; only HardNAV-positive unwind/external arb;
- RED: freeze edge initiation; repay, hedge, liquidate, and restore accounting only.

---

## 13. Lock/free-float risk treatment

Locking does not create HardNAV.

For stress horizon h define

`F_stress(h) = F_free + UnlockingWithin(h)`.

Only balances that can become sellable inside the stress horizon enter the synthetic exit-depth stress.

Lock rewards are liabilities until paid and may be funded only from distributable realized hard revenue.

---

## 14. Realized hard operating PnL and revenue waterfall

Let:

- `C_t` = external capital contributions during period t;
- `W_t` = capital withdrawals/distributions during period t.

After-cost operating hard PnL is

`Pi_t = HardNAV_t - HardNAV_{t-1} - C_t + W_t`.

Own-token mint, burn, lock, reserve transfer, gradient initiation and internal protocol transfers do not enter `C_t` and are not revenue.

Distributable amount:

`D_t = max(0, Pi_t - RequiredReserveTopup_t)`

subject to post-distribution constraints

`K_hard_after >= K_distribution`

and

`STS_after >= STS_distribution`.

Waterfall allocations must satisfy

`Gas + Insurance + Reinvestment + Holders + Projects + Founder <= D_t`.

No nominal synthetic emission may be labeled as hard project/holder revenue.

---

## 15. Sequential optimizer

At state `X_n`, candidate control is

`u_n = (synthetic, source, destination, gradient size, optional QE size, route, tax, reward floor)`.

The safe optimizer solves

`u_n* = argmax_u J(u | X_n)`

subject to all V15 invariants.

After execution:

`X_{n+1} = F(X_n, u_n*)`.

Quotes/routes are NEVER reused from `X_n` after state changes.

The next exploitation or gradient rotation is solved from `X_{n+1}`.

---

## 16. Mandatory invariants

### I1 — Hard accounting boundary
Own synthetic inventory contributes zero to HardAssets.

### I2 — Liability completeness
Every externally enforceable redemption/debt/bridge claim is in ExternalLiabilities exactly once.

### I3 — Hard-asset uniqueness
Every protocol-controlled hard-asset unit is counted exactly once.

### I4 — Synthetic partition conservation
For every synthetic, total supply equals the sum of all explicit partitions.

### I5 — Supply-neutral gradient
Every gradient initiate/restore/close has `Delta S_a = 0`.

### I6 — Pure-gradient zero-wealth condition
Before system-paid costs, gradient initiation alone has `Delta HardNAV = 0`.

### I7 — Atomic QE/QT neutrality
If temporary monetary expansion is used, final supply equals initial supply and no temporary balance escapes.

### I8 — Realized-profit capture only
Protocol arb tax is a function of actually realized route profit, not gross swap output or notional.

### I9 — Solver participation
Every accepted solver route leaves at least the configured solver reward after tax.

### I10 — Positive robust protocol edge
Every accepted risk-expanding route satisfies the robust post-trade HardNAV inequality in Section 11.

### I11 — Coverage
Every accepted transition leaves `K_hard >= K_min(mode)`.

### I12 — Stress solvency
Every accepted transition leaves `STS >= STS_min(mode)`.

### I13 — Conservation regression
For a closed test universe with common marks and no omitted costs:

`Delta NAV_protocol + Delta NAV_external + SolverReward + ThirdPartyCosts = 0`.

### I14 — Internal-transfer neutrality
Moving assets between protocol-owned accounts/pools cannot change HardNAV.

### I15 — Revenue integrity
Only operating hard PnL after capital-flow adjustment is distributable revenue.

### I16 — Stateful re-optimization
Every route is evaluated on the state produced by all previous accepted routes.

---

## 17. Sufficient-condition theorem for V15 solvency preservation

This is deliberately a conditional theorem, not a claim that markets guarantee profit.

Assume at state X_t:

1. `HardNAV_t > 0`;
2. `K_hard,t >= K_min`;
3. `STS_t >= STS_min > 1`;
4. accounting sets are complete and unique;
5. oracle error is bounded by the configured epsilon set;
6. every transition is atomic or fails closed;
7. candidate action u is executed only if its post-state satisfies I1-I16.

Then the accepted state X_{t+1} satisfies:

- synthetic supply invariants;
- `HardNAV_{t+1} >= HardNAV_t + G_min` for a risk-expanding route after the modeled uncertainty/cost buffer;
- `K_hard,t+1 >= K_min`;
- `STS_{t+1} >= STS_min`.

Proof: these are explicit postconditions of the transition predicate. A candidate violating any condition is not in the admissible action set and reverts/is rejected.

This theorem proves preservation under the controller; it does NOT assert that an admissible profitable route always exists.

---

## 18. Mandatory falsification tests before implementation

The V15 simulator must include at least:

1. aligned oracle == venue prices -> no fake HardNAV edge;
2. zero external flow;
3. 50/50 orderflow;
4. market-neutral stochastic orderflow;
5. adversarial sell pressure;
6. stale-oracle rejection;
7. stablecoin depeg;
8. external depth collapse;
9. gas spike;
10. solver reward floor binding;
11. partial/public LP ownership rejection;
12. unregistered hard balance/liability detection;
13. lock maturity cliff;
14. bridge liability shock;
15. repeated gradient exploitation with full state carry-forward;
16. integer-rounding conservation checks.

The old deterministic `62% buy / 38% sell` trajectory must not be used as evidence of protocol-generated wealth.

---

## 19. V15 economic interpretation

V15 contains two distinct functions:

1. **Edge Engine (V13.1):** changes protocol-owned synthetic reserve geometry so that a small external relative-price basis may become executable.
2. **Solvency Brain (V15):** decides whether the edge may be initiated, sizes it, rejects false accounting gains, and permits distribution only from realized hard operating PnL.

The system does not claim to create external wealth from a closed synthetic loop. The mathematical target is instead:

`maximize robust realized HardNAV transfer from genuine external market state, subject to strict supply, accounting and solvency invariants`.
