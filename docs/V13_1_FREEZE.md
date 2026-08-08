# V13.1 FREEZE

Status: **FROZEN BASELINE**

Branch: `synthl1-recursive-qe-mev-v5`
PR: #15

V13.1 is frozen as the reference implementation of the supply-neutral reserve-gradient edge initiator.

Frozen architecture:

`synthetic reserve shift -> self-created gradient -> executor-gated external graph route -> realized-profit tax -> post-trade HardNAV gate -> synthetic restore -> captured-quote reinvestment -> rotate`

Frozen economic conclusions:

- supply-neutral gradient: burn(source) == mint(destination), so controlled synthetic total supply is unchanged;
- protocol accounting must use one consistent oracle/HardNAV mark vector;
- aligned market == oracle mark is a negative control and must not create accepted HardNAV-positive routes;
- small external basis below the standalone multi-leg fee hurdle may become executable after the internal gradient changes route geometry;
- every accepted route must increase consolidated protocol HardNAV after tax and configured oracle uncertainty buffer;
- conservation must hold: protocol HardNAV delta + external LP delta + solver retained reward ~= 0, before external revenues/costs outside the modeled route.

No further V13.1 feature work should be added. Any new monetary, collateral, debt, payment-system, or dual-contour ideas belong to the V15 research/design line and must be re-audited independently before integration.
