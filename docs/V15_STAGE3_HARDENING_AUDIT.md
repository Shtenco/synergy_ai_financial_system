# SINERGY V15 — Stage 3 Institutional Hardening Audit

Status: design/source hardening complete for this pass; compiler/EVM/fork gates remain open.

Frozen base: V13.1 commit `385eaa2e6c811f1f29c504984484d9223b42b1b7`.

## 1. Accounting boundary

Economic HardNAV uses canonical external hard assets minus externally enforceable liabilities.

Own synthetics are permanently excluded from hard assets.

Risk accounting remains separate and uses conservative TWAP/exit/haircut/stress marks.

No own-token price increase, mint, burn, lock, internal transfer or reserve gradient is booked as hard profit.

## 2. Liability fail-closed policy

Manual liabilities now have a freshness timestamp and maximum age.

If a manual liability becomes stale:

`Economic HardNAV -> revert`

and therefore K/STS/action permission also fails closed.

Additional rules:

- switching from source-managed to manual mode invalidates the old manual report;
- re-enabling a liability does not refresh an old timestamp;
- a non-zero outstanding liability cannot be disabled from the registry.

A source-managed liability adapter is itself expected to revert on stale source data.

## 3. Synthetic exclusion is bound to gradient-engine registration

`V15AccountingAdapter.setGradientEngine(engine, true)` reads the frozen engine's synthetic getter and requires:

- `V15EconomicLedger.permanentlyExcludedAsset(synthetic) == true`;
- `V15EconomicLedger.isHardAsset(synthetic) == false`.

Therefore a V13.1 monetary synthetic cannot be registered for execution and later accidentally promoted into Economic HardAssets.

## 4. Action-class enforcement

`routeSolvent()` is a survival metric and can remain true in ORANGE.

New searcher exploitation is stricter:

`searcherRouteAllowed() = !emergencyPaused && mode in {GREEN,YELLOW} && routeSolvent()`.

`V15PostRouteGate` uses `searcherRouteAllowed()` rather than `routeSolvent()`.

Thus a direct call to frozen `GraphArbExecutor` cannot bypass the V15 ORANGE/RED policy.

## 5. Emergency restore invariant

Frozen `ReserveGradientEngine.restoreGradient()` internally asks accounting for coverage before the exact synthetic restore.

A liability/oracle shock can drive real coverage below that historical V13.1 floor while an active synthetic gradient still needs to be restored.

The V15 adapter therefore provides a narrowly scoped compatibility exception:

- governance must explicitly register the gradient engine;
- before gradient initialization (`active == false`) real coverage is returned;
- while the registered engine is already active, its frozen restore coverage read receives compatibility max coverage;
- the restore itself moves no hard quote assets and remains supply-neutral.

This prevents a solvency shock from trapping the protocol inside a synthetic reserve displacement.

## 6. Independent guardian

All long-lived V15 risk owners should be deployed as the repository's existing `TimelockedMultisig` (24 hour minimum delay, N-of-M approvals).

`V15SolvencyController` adds an independent guardian emergency stop:

- guardian or owner may pause immediately;
- guardian cannot unpause;
- only owner/timelock may restart;
- searcher routes, new expansion and distributions are blocked while paused;
- survival metrics and recovery/restore remain available.

This creates the intended asymmetric control:

`fast stop / slow restart`.

## 7. Absolute capital and concentration

K and STS ratios alone are not sufficient.

Stage 3 adds:

`RiskAssets >= MinRiskAssets`

and:

`max_i RiskAsset_i / TotalRiskAssets <= ConcentrationLimit`.

A concentration breach moves the controller toward ORANGE, preserving unwind/restore while blocking expansion.

Defaults remain permissive for backward test compatibility; production values require empirical calibration.

## 8. Robust optimizer

Safety constraints are hard constraints, not weighted preferences.

For candidate action u:

`RobustGain(u) = min_s DeltaHardNAV_s(u) - OracleError(u) - ModelError(u) - SystemCost(u)`.

Only admissible candidates are ranked, lexicographically, by:

1. worst-case robust hard gain;
2. post-state solvency buffer;
3. hard-capital efficiency;
4. gradient-initiated alpha;
5. lower hard turnover.

The correct output may be `HOLD`.

Reference: `simulation/v15/robust_optimizer.py`.

## 9. Gradient attribution and frontier

Every candidate should be evaluated both with and without the internal gradient on the same pre-state.

`GradientAlpha = DeltaHardNAV_gradient - max(0, DeltaHardNAV_noGradient)`.

This prevents V15 from claiming pre-existing external alpha as internally initiated alpha.

Reference frontier with 0.30% pool fee, 99% profit-tax ceiling, solver floor, 10 bps valuation buffer and explicit system cost shows:

- 0.4%-0.6% external basis can be nominally positive yet robust-negative;
- 0.8% basis preferred about a 10% gradient on the tested grid;
- 1.0% basis preferred about 20%;
- 1.5% basis preferred about 40%;
- 2.0% basis preferred about 50%.

These are reference-model results, not production calibration.

The policy conclusion is robust:

> maximum wedge is not the target; gradient size is a state-dependent control variable.

## 10. Deterministic governor stress

`simulation/v15/governor_stress.py`, seed 42, 10,000 synthetic candidates:

- accepted: 399;
- accepted hard-constraint violations: 0.

Configured reference constraints:

- minimum risk assets = 50;
- maximum single-asset concentration = 80%;
- GREEN K/STS floors = 130%;
- minimum robust gain = 0.01.

This validates controller logic only. It is not evidence of live market profitability.

## 11. Revenue proof is dual-gated

A direct deposit/donation can raise HardNAV and therefore must not automatically become distributable operating revenue.

V15RevenueRouter now requires both:

1. positive high-water-mark Economic HardNAV PnL after physically verified external contributions and historical loss carry-forward;
2. physically swept hard revenue from an allowlisted protocol hard-account source.

Thus:

`DistributionBase = min(ProfitAfterLoss, EligibleRevenueSwept)`.

The resulting budget is still subject to reserve policy and pre/post distribution K/STS/absolute-capital/concentration checks.

Typical eligible sources are capture, public-fee or bridge-fee vaults that are already protocol hard accounts.

An unsolicited external donation can raise NAV but, absent an eligible internal revenue sweep, produces zero distribution budget.

## 12. Buyback/burn is an external distribution

Because own synthetic inventory has zero Economic HardAsset value:

`hard asset -> buy own token externally -> burn`

reduces protocol Economic HardNAV by the hard asset spent.

Therefore buyback/burn belongs to the external distribution bucket and competes with holder/project/founder payouts for the same distributable hard-surplus headroom.

Internal reinvestment into protocol-owned reserves/pools is different: it retains hard assets inside consolidated HardNAV.

## 13. Current evidence boundary

Implemented/source-tested concepts:

- eight-contract V15 overlay;
- separate Economic/Risk accounting;
- liability freshness/non-removal rules;
- permanent synthetic exclusion;
- GREEN/YELLOW searcher gate;
- RED emergency restore compatibility path;
- guardian emergency stop;
- physical contribution accounting;
- eligible-revenue dual gate;
- loss carry-forward;
- maximin optimizer / gradient frontier / capital allocator references.

Still mandatory before deployment or 10x50 enablement:

1. Solidity compile;
2. V15 EVM suite;
3. frozen V13.1 EVM regression;
4. emergency RED restore EVM test;
5. guardian EVM test;
6. archival Polygon fork;
7. then full 10-internal / 50-external optimizer.

The current GitHub runner failure occurs before job steps begin and therefore is not a compiler result.
