# SYNERGY AI Central Bank — Real Asset Emission Escrow V1

## Purpose

This design converts AI-guided target emission into a **bounded, evidence-gated liability-free issuance process**.

The AI central bank is not the authority that creates spendable money. It may only propose a target emission. Independent risk authority may cap and approve the proposal. Approved tokens are minted only into a locked escrow. They become transferable only when canonical Financial OS closes attest eligible growth of real/external assets.

```text
AI / policy model
      |
      | proposal only
      v
Target Emission Proposal
      |
      v
Independent Risk Authority
      |
      | approve + cap + coverage ratio
      v
MINT -> EmissionEscrow (LOCKED)
      |
      | no beneficiary access yet
      v
Financial OS accounting closes
      |
      | verified eligible real/external asset growth
      v
Growth Credit
      |
      v
Risk allocation
      |
      v
Proportional Escrow Release
```

## Hard authority boundary

| Authority | Allowed | Forbidden |
|---|---|---|
| AI proposer | propose amount, beneficiary, policy/model refs | approve, mint, attest assets, release |
| Risk authority | cap/approve emission; allocate verified growth | invent accounting growth |
| Financial OS authority | post canonical closes and eligible-growth evidence | mint/release emission |
| Governance | role rotation, minimum coverage, emergency pause | should be a timelocked multisig in production |

The AI therefore remains a **policy proposal engine**, not an execution or accounting authority.

## Real-asset growth rule

A Financial OS close provides:

- `HardNAV`;
- liabilities;
- eligible gross real/external asset growth for the period;
- internal mark change (audit-only);
- flash-principal inflow (audit-only);
- immutable evidence reference.

The contract computes:

```text
HardNAVGrowth
    = max(CurrentHardNAV - PreviousHardNAV, 0)

LiabilityIncrease
    = max(CurrentLiabilities - PreviousLiabilities, 0)

NetEligibleAssetGrowth
    = max(EligibleAssetGrossGrowth - LiabilityIncrease, 0)

CreditedGrowth
    = min(HardNAVGrowth, NetEligibleAssetGrowth)
```

This intentionally blocks several false sources of apparent growth:

```text
mint                       -> 0 growth credit
rebase                     -> 0 growth credit
internal token mark-up     -> 0 growth credit
own LP repricing           -> 0 growth credit
flash principal            -> 0 growth credit
liability-funded assets    -> netted by liability increase
HardNAV rise without eligible assets -> 0 growth credit
```

`eligibleAssetGrossGrowth` is a Financial OS classification and must itself exclude internal marks, flash principal and unsupported valuations.

## Coverage

Every approved emission has an external accounting reference value and a coverage ratio.

For token quantity `Q`, externally justified accounting unit value `P`, and coverage `C`:

```text
RequiredGrowth = Q * P * C
```

Example:

```text
approved emission:     100 SYNA
accounting unit value: 1 USD/SYNA
coverage:              200%
required growth:       200 USD
```

After only 100 USD of verified eligible growth, at most 50 SYNA becomes releasable. The remaining 50 SYNA stays locked.

This is **not a price promise**. `unitValueUsdE18` is an approved accounting conversion used to size backing requirements; production policy must define how it is sourced and must not use a manipulable internal pool mark as the sole source.

## Financial close replay protection

Every Financial OS close uses:

- unique `closeId`;
- strictly increasing `sequence`;
- immutable `evidenceRef`.

The same close cannot be reused to create growth credit twice.

Global verified growth credit is consumed when allocated to a proposal, so the same backing growth cannot unlock two target emissions.

## Cancellation and expiry

Unreleased target emission is not silently recycled.

- Risk authority may cancel a proposal and burn all still-locked tokens.
- After deterministic expiry, anyone may finalize expiry; the still-locked amount is burned.
- Already released emission remains historical fact and is never rewritten.

## Escrow solvency

The runtime requires:

```text
actual token balance of escrow >= total locked emission
```

Every mint, release, cancellation and expiry checks this invariant.

### Important: rebasing-token compatibility

The current historical `RebaseSynaV2` changes balances globally through a rebase index. A normal fixed-unit escrow can therefore lose nominal balance after a negative rebase even if it performs no transfer.

**V1 must use either:**

1. a fixed-unit/non-rebasing emission token; or
2. a future share-aware escrow adapter that accounts in immutable shares rather than rebasing token units.

Direct production connection to a globally rebasing token is not claimed safe by this V1.

## Production gates

Before live economic use:

1. Financial OS must emit signed/typed close artifacts rather than a manually controlled EOA feed.
2. `financialOsAuthority` should be a verified adapter or threshold signer bound to canonical close digests.
3. Governance and risk authority should use timelock + multisig/HSM/MPC controls.
4. `unitValueUsdE18` policy must use independent accounting/oracle evidence.
5. Fixed-unit or share-aware token semantics must be proven.
6. Formal invariant/fuzz testing and independent smart-contract audit are required.
7. Emission cap, per-period cap, concentration limits and emergency procedures must be defined.
8. Regulatory characterization of the token and issuance process must be completed for every operating jurisdiction.

## Status

`R&D / sandbox candidate`.

This contract demonstrates the authority and accounting logic. It does not establish that emitted tokens are legal tender, regulated stablecoins, securities, deposits, or externally backed assets, and it does not create economic value by itself.
