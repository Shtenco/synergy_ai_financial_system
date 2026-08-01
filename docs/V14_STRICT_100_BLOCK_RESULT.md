# SYNERGY V14 — strict 100-block stateful result

## Verdict

GitHub Actions run `30709889373` completed successfully.

- validator verdict: `PASS`;
- edge status: `NO_STRICT_STATEFUL_REALIZED_EDGE_IN_RANGE`;
- Polygon blocks: `91,266,209–91,266,308`;
- consecutive real blocks: `100`;
- internal protocol-owned pools: `10`;
- selected real QuickSwap V2/V3 pools: `50`;
- accepted sequential cycles: `0`;
- cumulative realized NAV: `$0`.

`PASS` means that the state machine, accounting identities and fail-closed gates
were internally consistent. It does not mean that a profitable cycle was found.

## Search volume

The strict run evaluated:

- `23,040` internal managed-gradient configurations;
- `25,600` forward/reverse route pairs;
- `14,976` positive optimistic screening candidates;
- `396` exact candidates;
- `0` exact quote failures.

All `396` exact candidates failed the same gate:

`reverseRouteFundingFailure = 396`

No candidate failed because of:

- forward quote availability;
- reverse quote availability;
- atomic synthetic buyback funding;
- gas-budget availability;
- supply or LP invariants;
- accounting identity;
- realized-profit threshold after reaching the final accounting stage.

They were rejected earlier because exact forward proceeds could not fully finance
the exact external reverse route required to restore the source LP.

## Best exact near-miss

The closest cycle was:

- synthetic: `SYNA`;
- source internal pool: `SYNA/DAI`;
- destination internal pool: `SYNA/USDT`;
- gradient shift: `1,000 bps`;
- temporary QE size: `1,000 bps`;
- forward route: `DAI -> USDT` through QuickSwap V3;
- restoration route: `USDT -> USDC` through V3, then `USDC -> DAI` through V3.

Exact amounts:

- forward output: `453.602562 USDT`;
- exact internal synthetic buyback: `446.885211 USDT`;
- forward output after initial buyback: `6.717351 USDT`;
- exact reverse-route input needed after recycling the destination buyback:
  `453.646677 USDT`;
- pre-gas reverse-funding deficit: `0.044115 USDT`;
- estimated gas: `0.06768413484785914 USD`.

Thus the external closed loop lost about `0.97255 bps` before gas. Including gas,
the best route was short of break-even by about `$0.111799`, or `2.46469 bps` of
the forward notional. To pass the configured `$0.01` minimum realized-profit gate,
it needed an improvement of about `$0.121799`, or `2.68515 bps`.

## Meaning for V13

V13 showed a large executor-wallet surplus because it stopped after the internal
buyback and treated the source-LP loss and destination-LP gain through consolidated
mark-to-market accounting. V14 forced the complete closure:

1. finance the internal synthetic buyback from forward proceeds;
2. recycle the destination buyback reserve without counting it as profit;
3. execute a disjoint exact external reverse route;
4. restore the source real reserve exactly;
5. restore the destination real reserve exactly;
6. preserve managed synthetic supply;
7. deduct gas;
8. carry the resulting state into the next block.

Once the real source reserve had to be restored, every tested candidate became
negative. The V13 `$42.1474` snapshot sum is therefore not realizable as a closed,
stateful profit under the tested public QuickSwap-only topology.

## What remains scientifically open

The result does not prove that the architecture can never earn external revenue.
It proves that this strict public QuickSwap V2/V3 closed-loop search did not find
one over the tested 100-block range and parameter grid.

The remaining valid directions are external revenue sources that do not require
buying back the same public path at ordinary AMM prices:

- intrablock backrun/order-flow capture;
- private bundles and solver auctions;
- more DEX families and RFQ liquidity;
- fee rebates or protocol-owned external liquidity;
- asymmetric settlement with inventory limits rather than immediate complete
  roundtrip restoration;
- external payer/revenue flows independent of managed mint/burn accounting.

Any later version must preserve V14's accounting gates and may not restore the
V13 independent-snapshot sum as cumulative profit.
