# SINERGY V15 — Invariant Proof Notes

This file accompanies `V15_MATHEMATICAL_SPEC.md`. It records the algebraic identities that must hold before implementation.

## P1. Supply-neutral gradient

For synthetic supply S and two managed reserves x_s, x_d:

`x_s' = x_s - delta`

`x_d' = x_d + delta`

All other synthetic partitions unchanged.

Therefore

`Delta S = -delta + delta = 0`.

Because no hard quote reserve moves during initiation and own synthetic is excluded from HardAssets:

`Delta HardNAV_gradient = 0`

before explicitly modeled system-paid costs.

For equal initial synthetic reserves X and quote-normalized equal prices, the post-gradient spot ratio is

`P_source'/P_destination' = (X+delta)/(X-delta) = (1+r)/(1-r)`, `r=delta/X`.

The wedge changes execution geometry; it is not booked as wealth.

---

## P2. Searcher/protocol/external conservation

Let B be the destination/base hard asset and A the source hard asset.

Searcher supplies P units of B.

The managed pools convert this to Aout units of A. The external route returns `P+G` units of B, where G is realized gross arbitrage profit.

Protocol captures Tax from G and solver retains `G-Tax`.

At common canonical marks p_A and p_B:

`Delta N_protocol = p_B(P+Tax) - p_A*Aout`.

`Delta N_external = p_A*Aout - p_B(P+G)`.

`Reward_solver = p_B(G-Tax)`.

Adding all three:

`Delta N_protocol + Delta N_external + Reward_solver = 0`.

Thus a positive protocol gain cannot arise from internal synthetic repricing. In this closed accounting universe it is matched by an external counterparty/LP loss, net of solver reward.

If third-party costs exist, the complete identity is

`Delta N_protocol + Delta N_external + Reward_solver + ThirdPartyRevenue = 0`,

with signs defined consistently for each party.

---

## P3. Exact synthetic restore

After exploitation, exact chained synthetic amount z has moved from destination to source:

`x_s = x_s* + z`

`x_d = x_d* - z`.

Restore burns z at source and mints z at destination:

`x_s -> x_s*`

`x_d -> x_d*`.

Hence restore also has `Delta S = 0`.

The engine must reject any state for which

`x_s - x_s* != x_d* - x_d`

outside integer tolerance.

---

## P4. Gradient close

Closing the gradient performs the inverse reserve transfer:

`x_s := x_s + delta`

`x_d := x_d - delta`.

This restores the pre-gradient synthetic reserves and again has `Delta S = 0`.

Hard quote balances accumulated/lost during prior external execution remain where the economics actually occurred; they are not erased by synthetic close.

---

## P5. Internal hard-asset transfers cannot create HardNAV

For a hard asset i transferred by amount q from one protocol-owned account to another:

`b_i,total' = (b_i,1-q) + (b_i,2+q) + ... = b_i,total`.

Therefore

`Delta HardAssets = p_i * Delta b_i,total = 0`.

This is why capture-vault -> managed-pool reinvestment changes future market geometry but not current HardNAV.

---

## P6. Capital-flow-adjusted operating PnL

Let N_t be HardNAV after all protocol balances/liabilities are consolidated.

Let C_t be genuine external capital contributions and W_t genuine capital withdrawals/distributions.

Define

`Pi_t = N_t - N_{t-1} - C_t + W_t`.

Then owner deposits do not masquerade as revenue, while withdrawals are added back when measuring operating performance.

Synthetic mint/burn/internal transfer has no C_t term.

Only positive Pi_t that survives reserve/solvency requirements is distributable.

---

## P7. HardNAV and RiskNAV must remain distinct

Economic conservation requires common, unhaircut canonical marks:

`HardNAV = sum_i p_i b_i - L`.

Solvency uses conservative executable marks/haircuts:

`RiskNAV = sum_i lambda_i pRisk_i b_i - LRisk`.

Haircuts deliberately destroy accounting conservation and therefore MUST NOT be used to test the P2 zero-sum identity.

This separation is mandatory.

---

## P8. Protocol-owned LP accounting

For any LP account k, let phi_k be the protocol's economic share of the LP.

Only

`phi_k * reserve_{i,k}`

may enter the protocol hard-asset balance.

For managed reserve-gradient pools V15 requires

`phi_k = 1`.

Otherwise synthetic reserve manipulation could transfer value to public LPs while the accounting engine incorrectly books 100% of pool assets to the protocol.

Every underlying hard-asset unit must be counted exactly once: either directly as a wallet/vault balance or through an LP claim, never both.

---

## P9. Solvency preservation is a controller theorem, not a market theorem

Define the admissible action set U(X) as all actions u whose post-state X' satisfies:

1. supply-partition conservation;
2. liability completeness;
3. HardNAV accounting uniqueness;
4. robust HardNAV gain floor for risk-expanding actions;
5. `K_hard(X') >= K_min`;
6. `STS(X') >= STS_min`;
7. atomic QE/QT neutrality when used.

The controller executes only `u in U(X)`.

If X_0 satisfies the invariants, then by induction every accepted X_n satisfies them.

This does NOT prove that U(X) contains a profitable action. When no safe profitable action exists, the correct action is HOLD/UNWIND.

---

## P10. Correct definition of the risk envelope

For a scalar size q, if every relevant risk constraint is monotone over the operating interval, define the cap for constraint c as

`q_c = sup{q >= 0 : constraint_c(X,q) holds}`.

Then

`q_max = min_c q_c`.

If any constraint is non-monotone in q, the min-of-independent-caps shortcut is invalid. The optimizer must instead solve directly over the feasible set

`Q(X) = {q : all post-state invariants hold}`.

The same rule applies to gradient size delta.

---

## P11. Numerical validation performed before implementation

Reference V13.1 fixture:

- managed source/destination initially 100 SYN / 100 quote each;
- supply-neutral gradient delta = 40;
- post-gradient price-ratio amplifier = 140/60 = 2.3333333333;
- external A/B pool = 10000 / 10100;
- principal P = 39.8 B;
- LP fee = 0.30%;
- realized-profit tax ceiling = 99%;
- solver absolute reward floor = 0.001 B.

Computed:

- synthetic moved z = 39.7713354610;
- Aout = 39.7904838014;
- external returned B = 39.9094980554;
- gross arb G = 0.1094980554;
- protocol tax = 0.1084030748;
- solver reward = 0.0010949806;
- protocol HardNAV delta = +0.1179192734;
- external LP delta = -0.1190142540;
- conservation residual ~= -9.7e-13.

A high-precision Decimal randomized test over 1,088 profitable random states produced maximum conservation residual `1e-51`.

These checks validate the algebraic accounting identity, not live profitability.
