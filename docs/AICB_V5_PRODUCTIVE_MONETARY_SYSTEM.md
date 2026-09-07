# SYNERGY AI CENTRAL BANK V5 — Productive Monetary System

## Status

R&D / sandbox candidate. Not a production central bank, security, stablecoin, or legal-tender system.

## Why V5 exists

V5 joins four previously separate layers:

1. **AICB V4 policy brain** — proposes a bounded target emission from inflation, reserves, goods growth, productive capacity, employment and money/goods balance.
2. **Synergy Eurasian** — owns productive-project facts and produces a productive-growth attestation.
3. **Synergy Financial OS** — owns accounting truth and produces an eligible-asset / HardNAV growth attestation.
4. **Emission Escrow** — mints only into lock and releases only when both independent growth gates exist.

The governing rule is deliberately stronger than either predecessor:

```text
released monetary value
<= verified productive growth value
<= evidence from real production/capacity

AND

released monetary value
<= verified eligible HardNAV growth
<= evidence from external/real assets net of liabilities
```

Operationally:

```text
dual_gate_credit = min(productive_growth_credit, financial_growth_credit)
```

The two credits are consumed together when escrow is released. A productive proof cannot be reused as accounting backing, and an accounting gain cannot be reused as physical backing.

## Authority model

| Component | May propose | May attest productive growth | May attest accounting growth | May approve risk | May release |
|---|---:|---:|---:|---:|---:|
| AICB V5 | yes | no | no | no | no |
| Synergy Eurasian | no | yes | no | no | no |
| Financial OS | no | no | yes | no | no |
| Risk Authority | no | no | no | yes | yes, only against both credits |
| Governance | role rotation/pause | no | no | no | no |

## Economic firewall

These do **not** create productive or financial emission backing by themselves:

- mint or rebase;
- internal token mark-up;
- own-LP repricing;
- flash-loan principal;
- debt-funded gross asset increase;
- unverified capacity plans;
- projected jobs or projected output;
- accounting revaluation without eligible real/external asset growth.

## Productive gate

A productive attestation should be derived from completed projects and verified observations such as:

- additional goods actually produced and accepted into inventory/sales;
- additional productive capacity actually commissioned;
- externally verified export output/revenue where used as productive evidence;
- logistics capacity that produces measurable throughput improvement;
- SME production that is actually measured rather than merely financed.

Physical quantities and valuation are kept separate. Any conversion from physical units to money requires a versioned valuation-method reference and evidence references.

## Financial gate

Financial OS computes conservative credited growth as:

```text
hardnav_growth = max(current_hardnav - previous_hardnav, 0)
liability_increase = max(current_liabilities - previous_liabilities, 0)
net_eligible_growth = max(eligible_asset_gross_growth - liability_increase, 0)
financial_credit = min(hardnav_growth, net_eligible_growth)
```

Internal marks and flash principal remain audit fields only.

## Release equation

For proposal `p` with required backing value `R_p`:

```text
usable = min(
    available_financial_credit,
    available_productive_credit,
    operator_max_credit,
    R_p - consumed_dual_credit
)
```

Then:

```text
target_released = approved_tokens * consumed_dual_credit / required_backing
```

Both global credits decrease by the same `usable` value.

## Lineage from Productive Liquidity Protocol V4

The uploaded historical V4 simulator already contained the core economic idea:

```text
mint -> escrow -> matching capital -> project -> proof of productivity -> release/delay/haircut/cancel
```

It also separated `free_money` from `escrow_money`, modeled banks and productive anchors, applied rating/quarantine/fraud learning and constrained physical output by productive capacity.

V5 preserves that policy lineage but moves settlement and authority out of the simulator:

```text
simulation/policy proposal != accounting truth != productive truth != token release authority
```

## V5 target

The final sandbox E2E should prove one complete project lifecycle:

```text
AICB snapshot
 -> TargetEmissionProposal
 -> independent risk approval
 -> mint into escrow
 -> Eurasian project completion evidence
 -> ProductiveGrowthAttestation
 -> Financial OS close
 -> EligibleAssetGrowthAttestation
 -> dual-gate release
 -> Financial OS recognition
 -> immutable commitment / audit trail
```

A failed productive gate or failed financial gate must leave the corresponding emission locked or cause cancellation/burn.
