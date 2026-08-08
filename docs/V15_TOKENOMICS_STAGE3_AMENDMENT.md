# SINERGY V15 — Stage 3 Tokenomics Amendment

This amendment refines `V15_TOKENOMICS_CONSTITUTION.md` after the institutional hardening pass.

## A1. Three-proof rule for external distribution

A rise in Economic HardNAV alone is not enough to create distributable profit.

External distribution requires all three independent proofs:

1. **HWM proof** — positive Economic HardNAV PnL after physically verified external contributions and historical loss carry-forward;
2. **revenue-source proof** — hard tokens physically swept from an allowlisted protocol hard-account revenue source into `V15RevenueRouter`;
3. **capital-headroom proof** — `V15SolvencyController.distributionHeadroom1e18()` is positive.

Therefore:

`DistributionBudget = min(ProfitAfterLoss, EligibleRevenueSwept, SolvencyHeadroom)`.

A direct donation may increase NAV but cannot by itself create distribution budget.

## A2. Solvency headroom is balance-sheet derived

The owner no longer supplies an arbitrary reserve-top-up number to period settlement.

The controller derives conservative hard-distribution headroom as the minimum of:

- Economic HardNAV above its floor;
- base K/coverage headroom above the distribution threshold;
- absolute risk-capital headroom;
- every enabled stress scenario's STS headroom.

Single-asset concentration remains an independent pre/post-transfer hard gate.

This makes reserve retention a function of the actual balance sheet rather than a discretionary accounting input.

## A3. Crisis accounting never stops

A RED/YELLOW/ORANGE state may prohibit distribution, but it must not prohibit period accounting.

`settlePeriod()` therefore still records negative operating PnL and increases loss carry-forward when distribution headroom is zero.

The protocol is not allowed to hide a crisis loss merely because it is in emergency mode.

## A4. Eligible revenue sources

A source may count as eligible revenue only when:

- governance explicitly allowlists the source;
- the token is a registered hard asset;
- both the source and RevenueRouter are registered protocol hard accounts for that token;
- the actual received token balance delta is measured.

Typical sources:

- realized MEV/arb capture vault;
- public trading-fee vault;
- bridge/service-fee vault;
- independent external-arbitrage profit vault.

Owner capital, investor deposits and unsolicited donations are not eligible revenue merely because they are hard assets.

## A5. Buyback/burn treatment

An own-token buyback from an external holder is an **external hard distribution**.

It consumes the same distribution budget as holder/project/founder payouts because:

- hard assets leave consolidated protocol custody;
- the acquired own token has zero Economic HardAsset value;
- burning it does not restore the hard asset spent.

An internal hard transfer into a 100%-protocol-owned pool is retained capital and is not a distribution.

## A6. Fast stop / slow restart

Long-lived V15 `owner` roles should be assigned to the repository's timelocked N-of-M multisig.

`V15SolvencyController.guardian` is a separate emergency role:

- guardian may pause new searcher exploitation, expansion and distribution immediately;
- guardian cannot unpause;
- only the timelocked owner may restart;
- exact restore/recovery remains available.

## A7. Liability reporting

Manual liabilities have a freshness TTL.

Stale liability data makes HardNAV/RiskNAV reads fail closed.

A non-zero liability cannot be disabled from the registry.

Switching a source-managed liability back to manual mode invalidates the old manual report until a new amount is submitted.

## A8. Gradient-engine accounting boundary

A V13.1 gradient engine may be registered with the V15 accounting adapter only if its synthetic is already irreversibly excluded from Economic HardAssets.

This prevents a governance/configuration path from later recognizing the monetary synthetic as hard collateral.

## A9. Large-search winner's-curse penalty

The future 10-internal / 50-external optimizer will search many correlated candidates.

Selecting the maximum estimated edge creates multiple-testing bias even if every individual quote estimator is approximately unbiased.

V15 therefore treats model uncertainty as including:

- empirical prediction-overstatement buffer;
- search-space / winner's-curse penalty;
- structural model-risk add-on.

Reference:

`simulation/v15/model_risk.py`.

For a simple Gaussian-style reference bound:

`SelectionPenalty ~= sigma_error * sqrt(2 ln(M / alpha))`,

where `M` is the number of candidates searched in the decision family.

Production calibration must use empirical quote-to-execution errors and preferably block/bootstrap maximum-error distributions; the analytic expression is a conservative reference, not a theorem about market errors.

## A10. Optimizer objective

The final action hierarchy is:

1. accounting/supply validity;
2. mode permission;
3. Economic HardNAV floor;
4. absolute risk-capital floor;
5. K / STS;
6. concentration;
7. worst-case hard gain after oracle/model/system costs;
8. only then solvency buffer, capital efficiency, gradient alpha and turnover.

`HOLD` is a first-class optimal action.

No synthetic price target, TVL target, nominal market-cap target or maximum wedge may override this hierarchy.
