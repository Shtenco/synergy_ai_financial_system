# Investment-bank NO ACTION gate for targeted productive authorisation

Status: **research control / not a yield forecast**.

The Financial OS must never use targeted monetary authorisation to manufacture a bank's expected return.

For a simplified project cohort where interest is earned only on successful projects:

`ExpectedInterestPerPrincipal = SuccessProbability * AnnualYield * DurationWeeks / 52`

`ExpectedCreditLossPerPrincipal = DefaultProbability * LGD`

A minimal underwriting gate is:

`ExpectedInterest - ExpectedCreditLoss - FundingCost - CapitalCharge - OpsCost > 0`.

Ignoring funding/capital/ops costs only to expose the conservation boundary, the break-even annual project yield is:

`r_break_even = PD * LGD / (SuccessProbability * DurationWeeks/52)`.

## Local calibration used by the marketplace/investment-bank bridge

These parameters are simulation assumptions, not observed Russian default/yield statistics:

- base success probability = 88%;
- base LGD = 30%;
- mean illustrative duration = 14 weeks;
- nominal project/bank yield = 16% annualised.

Base regime:

`r_break_even = 12% * 30% / (88% * 14/52) = 15.19%`.

At a 16% gross annual yield, the simplified expected margin before funding/capital/ops costs is only about **+0.19% of principal**. This should be interpreted as marginal, not attractive.

Stress regime in the local harness multiplies success probability by 0.82 and LGD by 1.25:

- success = 72.16%;
- PD = 27.84%;
- LGD = 37.5%.

Then:

`r_break_even = 27.84% * 37.5% / (72.16% * 14/52) = 53.74% annualised`.

Keeping a 16% gross yield produces an expected simplified loss of about **7.33% of principal** before funding/capital/ops costs.

Therefore a bank auction in this regime must do one or more of the following:

- return `NO ACTION`;
- require materially better verified project economics;
- reduce advance rate / increase collateral;
- require external first-loss capital;
- shorten duration or improve recovery economics;
- reprice the project if the real business cash flow can support it.

It must **not** use extra minting to make a negative expected-value loan appear profitable.

At unchanged 16% gross project yield, the stress cohort would require approximately 7.33% of principal in external loss absorption merely to offset the simplified expected gap. That is about 70.2% of the cohort's expected credit loss. Adding funding cost, regulatory/economic capital charge and operating cost increases the required protection.

This gate belongs before `ProductiveCapitalAuction` allocation and before any targeted monetary authorisation.
