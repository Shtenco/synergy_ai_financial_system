# SINERGY Financial OS — Credit Pricing & Rating Term Structure V2

Status: additive research layer. The earlier 14-week `investment_bank.py` remains untouched as a frozen simplified regression model.

## Why V2 exists

The earlier one-period calculation treated one project yield and one 14-week horizon as if they could represent all bank lending. That is intentionally superseded for new research by a term-structured model.

A bank loan is not priced from `PD × LGD` alone and is not assigned one universal rate. A practical research decomposition is:

`loan APR(T) = reference/funding curve(T) + funding basis(T) + liquidity/term premium(T) + credit-risk spread(PD(T), LGD(T), EAD(T)) + capital charge + operating cost + target margin`.

For a floating-rate RUB loan the policy rate can be one reference anchor. For fixed or long-duration assets the bank should use its actual transfer-pricing/funding curve rather than assuming today's policy rate is the cost of every maturity.

Reference snapshot used in local examples: Bank of Russia key rate 14.00% effective from 2026-07-27. This is a dated calibration anchor, not a hard-coded production constant.

## Scoring/rating has four jobs

A rating is not merely a surcharge table. It drives:

1. approval / `NO ACTION`;
2. exposure/credit limit;
3. collateral, LTV, DSCR, covenants and first-loss requirements;
4. credit-risk component of price.

A very risky loan may therefore be rejected even if a huge nominal APR would mathematically cover expected loss. Excessive price can itself damage affordability and default probability.

## Horizon-specific risk

The same borrower has different cumulative default probabilities at 14 weeks, one year and three years. `BorrowerRiskProfile` therefore stores a curve of `TermRiskPoint` values instead of one annual PD copied into every maturity.

Each point contains:

- cumulative `PD(T)`;
- `LGD(T)` after collateral/recovery assumptions;
- `EAD(T)` factor.

PD interpolation is performed in cumulative-hazard space. Production should use validated bank rating curves and scenario/stress transitions rather than the research interpolation helper.

## Expected-loss spread

For the research implementation:

`EL_share(T) = PD(T) × LGD(T) × EAD_factor(T) - external_first_loss_share`, floored at zero.

The annualized expected-loss compensation is approximated as:

`risk_spread(T) = EL_share(T) / (T_years × survival_exposure_factor)`

with `survival_exposure_factor = 1 - 0.5 × PD(T)` as a simple uniform-default-timing approximation.

This is deliberately not presented as a production IFRS/IRB pricing formula. A production bank should integrate hazard, amortization and cash flows directly.

## Example calibration

Using only an illustrative decomposition around a 14.00% reference:

- funding basis: 1.25 pp;
- liquidity/term premium: 0.25 pp at 14 weeks, 0.50 pp at 1 year, 1.25 pp at 3 years;
- capital charge: 1.00 pp;
- operating cost: 0.75 pp;
- target margin: 1.25 pp.

Illustrative internal rating curves then produce rates roughly in these ranges:

- A: 18.7% (14w), 19.0% (1y), 19.8% (3y);
- BBB: 19.5%, 19.8%, 20.9%;
- BB: 21.9%, 22.0%, 23.4%;
- B: 27.9%, 27.7%, 30.1%.

These are examples for architecture testing, not market offers, forecasts or recommended lending rates.

## Financial OS role

SINERGY must not replace the bank's underwriting judgment with monetary issuance.

`rating/scoring -> bank underwriting -> price/limit/collateral -> private funding -> verified productive result -> conditional monetary authorization release`.

If the bank returns `NO ACTION`, targeted issuance cannot manufacture project profitability.

## Validation discipline

For the Python financial kernel the current validation order is local-only:

`real interpreter/compile -> unit tests -> frozen old-model regression -> Constitution/guardian invariants -> pinned historical-data replay -> ledger reconciliation -> only then multi-seed Monte Carlo`.

The separate phrase `real compiler -> V15 EVM -> frozen V13.1 EVM regression -> RED/guardian execution -> pinned Polygon archival fork -> reconciliation -> 10x50` is appropriate only when those named EVM artifacts actually exist. No `V15 EVM` or `V13.1 EVM` artifact is currently present in the searched `Shtenco/ai_financial_system` repository, so this branch does not pretend to have executed that literal pipeline.
