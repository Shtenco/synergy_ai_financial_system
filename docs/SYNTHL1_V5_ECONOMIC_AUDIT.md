# SynthL1 V5 economic audit

## Executive verdict

The recursive mechanism is mechanically valid but it must be described precisely:

`initial internal USDx QE -> CORE buyback/burn -> protocol-owned graph wedge -> external searcher closes wedge -> realized-profit capture -> captured USDx reinvestment -> next pulse`

A closed self-created wedge is **not** a source of positive consolidated external NAV. With protocol-owned pulse pools, the best theoretical closed-loop result approaches zero from below as the protocol captures almost all arbitrage rent and leaves the searcher only a minimal reward.

The mechanism is therefore best understood as a **MEV/LVR recycling amplifier**. Positive hard edge requires an independent external revenue component: external market mispricing, public orderflow fees, solver auction payment, bridge revenue, or another asset inflow.

## 1. Correct accounting scope

For pulse pools that are 100% protocol-owned:

- freshly minted USDx placed into those pools remains protocol treasury stock;
- it is not yet an external USDx liability;
- when a searcher deposits `q` external USDx and withdraws `q + B`, external USDx liability increases by exactly searcher profit `B`;
- captured USDx held by the protocol remains internal and can be recycled;
- CORE burn is not counted as hard profit.

Thus, ignoring independent external revenue and costs:

`Delta CNAV = - cumulative searcher retained profit <= 0`.

If a pulse pool is not 100% protocol-owned, the initializer itself externalizes synthetic liabilities. For a seed `M` and protocol LP share `phi`, a conservative first-order liability attribution is:

`external liability from initializer ~= M * (1 - phi)`.

For `M = 80`:

- 100% protocol LP -> `0` external USDx liability from the initializer;
- 50% protocol LP -> about `40` USDx;
- 0% protocol LP -> about `80` USDx.

Therefore V5.1 now rejects QE/reinvestment unless the configured protocol liquidity owner holds 100% of shares in the pulse pool.

## 2. Exact initializer wedge

For an initially balanced CPMM `R CORE / R USDx`, LP fee `f`, and USDx pulse `M`, let `s=M/R`.

After `USDx -> CORE`:

`P1/P0 = (1+s) * (1+(1-f)s)`.

For `R=100`, `M=80`, `f=0.003`:

`P1/P0 = 3.23568`, therefore the spot wedge is **223.568%**.

Large wedges are easy to create, but the pulse is a balance-sheet operation, not profit.

## 3. Why a large output toll is the wrong main MEV capture mechanism

A static output toll changes the marginal arbitrage condition.

For a two-leg route with LP fee `f` on both legs and output toll `tau`, infinitesimal arbitrage is profitable only when:

`P_high/P_low > 1 / ((1-f)^2 * (1-tau))`.

With `f=0.003` and `tau=30%`:

- minimum ratio ~= `1.437`;
- the system naturally leaves a **~43.7% no-arbitrage band**.

Contract-realistic recursive simulation for `seed=80`, `reserve=100`, `15` protocol-owned pools, `30%` output toll:

- initial wedge: `223.568%`;
- first captured output toll: about `11.56 USDx`;
- cumulative recycled toll: about `20.82 USDx`;
- cumulative searcher retained profit / CNAV leakage: about `10.98 USDx`;
- recursion stops after roughly `15` pulses because remaining spread is no longer profitable after the toll;
- residual spread is about `43.7%`.

So a 30% output fee both leaks too much value and prevents full convergence.

## 4. Corrected V5.1: realized-profit tax

The main capture mechanism is moved into `GraphArbExecutor`.

For an actually completed atomic route:

`grossProfit = actualReturnedBaseToken - principal`.

Then:

`protocolTax = grossProfit * profitTaxBps / 10000`.

`searcherNetProfit = grossProfit - protocolTax`.

The tax is transferred physically to `MEVCaptureReinvestor` before the searcher receives its final return.

This is superior to taxing gross swap output because a constant proportional profit tax does not change which route size maximizes gross profit; it simply scales the searcher's reward.

`MAX_PROFIT_TAX_BPS = 9900` allows a 99% capture upper bound while leaving 1% of realized profit to the searcher.

The searcher still requires:

`searcherNetProfit > gas + risk premium`.

Therefore 99% is not always executable. The rate must be lowered when gross opportunity is too small.

## 5. Bypass prevention

A realized-profit tax is useless if searchers can call the pulse pool directly.

V5.1 therefore adds an optional managed-pool gate:

- `USDx -> CORE` pulse direction remains available for the engine;
- `CORE -> USDx` closing direction can be set to `GraphArbExecutor-only`;
- the executor measures actual returned balance and taxes only realized profit.

External DEX pools remain unrestricted. This restriction is for protocol-owned internal MEV surfaces, not for third-party pools.

## 6. Existing recursive 99% model reinterpreted

`simulation/synthl1/recursive_qe_mev.py` previously called 99% capture an idealized managed-fee/auction upper bound.

After V5.1, its main economics correspond closely to a proportional realized-profit tax, provided:

1. the closing direction cannot bypass the executor;
2. output toll is zero or small enough not to distort the route;
3. the retained 1% searcher reward exceeds gas/risk costs.

For the reference `80 / 100 / 15 pools` scenario, the existing model gives approximately:

- first gross arb surplus: `22.61 USDx`;
- first 99% protocol capture: `22.39 USDx`;
- first searcher reward: `0.226 USDx`;
- cumulative recycled capture: `~47.47 USDx`;
- cumulative searcher leakage: `~0.48 USDx`.

The closed loop still has negative CNAV, but the loss is only about `0.6%` of the initializer before gas rather than `13.7%` under the 30% output-toll model.

## 7. External revenue needed for a positive edge

Let:

- `X_n` = independent external revenue in cycle n;
- `B_n` = searcher retained reward;
- `C_n` = gas/bridge/ops cost paid by the system;
- `T_n` = captured self-wedge rent recycled internally.

Then self-wedge capture `T_n` is not new hard value. A conservative consolidated equation is:

`Delta CNAV_n = X_n - B_n - C_n`.

Break-even requires:

`X_n >= B_n + C_n`.

For a target +10% hard edge on capital `K`:

`X_total >= 0.10*K + cumulative(B_n + C_n)`.

Scaling the reference shape proportionally from `80` to `5` units:

- 99% realized-profit-capture model has about `0.60%` searcher leakage before gas;
- on `K=5`, leakage is roughly `0.03`;
- therefore a true `$5 -> $5.5` consolidated result still requires about `$0.53 + costs` of independent external value.

By contrast, the static 30% output-toll model leaks about `13.7%` of the initializer; at the same scale it would require about `$1.19 + costs` of external value to net +$0.50.

## 8. Recursive stability condition

If captured USDx is the only next-pulse fuel:

`Pulse_(n+1) = Capture_n`.

Define recycle efficiency `alpha_n = Capture_n / Pulse_n`.

Without external revenue, `alpha_n < 1` and recursion eventually decays.

To hold pulse size constant:

`ExternalTopup_n >= Pulse_n - Capture_n`.

To grow pulse size:

`ExternalTopup_n > Pulse_n - Capture_n`.

This external top-up may be hard stable revenue or externally paid USDx. An external USDx payment to protocol is economically valuable because it reduces external USDx liability and becomes recyclable treasury stock.

## 9. Best use of the existing repository

The following pre-existing contracts remain valuable:

- `GraphPolicy` -> outer LNAV/timelock gate;
- `GraphTreasury` -> custody boundary;
- `OrderflowAuction` -> competition among solvers and additional external bid revenue;
- `SecureFlashExecutor` -> independent external graph edge and flash liquidity;
- `TimelockedMultisig` -> governance hardening.

`OrderflowAuction` is especially useful because an auction/access payment can capture searcher rent without imposing a huge output toll. The V5.1 realized-profit tax is the deterministic fallback; solver auction revenue can be an additional external revenue line.

## 10. Current verdict

### Passed conceptually / numerically

- Initial QE creates the intended large wedge.
- Captured USDx can be physically recycled without fresh mint after initialization.
- Closed-loop conservation is respected: no positive hard NAV is invented.
- A proportional realized-profit tax can approximate the former 90-99% managed-capture model without a 40%+ no-arb band.
- Protocol-only LP ownership can be enforced at pulse time.

### Still required before deployment

- Solidity compilation / EVM tests.
- Integration test wiring `GraphArbExecutor` as capture collector and managed-pool arb executor.
- Gas-aware adaptive profit-tax policy.
- Direct integration with `OrderflowAuction` / `GraphPolicy`.
- Fork/live tests for external venues.
- Formal invariant test that `SystemAccounting` cannot exclude USDx held in a partially public LP.

## Bottom line

The mathematically strongest architecture is now:

`internal QE pulse -> protocol-owned wedge -> executor-gated searcher arb -> tax on realized arb profit -> captured USDx -> reinvest -> next pulse`

plus an **independent external edge layer**:

`external graph arb + solver auction bids + public flow/bridge fees`.

The first layer maximizes recycling and minimizes LVR leakage. The second layer is what can make consolidated hard NAV grow above zero.
