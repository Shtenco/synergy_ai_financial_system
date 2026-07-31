# V11 atomic QE/QT Polygon fork test scope

This branch adds a research-only pinned Polygon fork test for the complete atomic cycle:

`temporary QE mint -> internal SYNA/USDT extraction -> real QuickSwap Algebra V3 USDT/WPOL -> real QuickSwap V2 WPOL/USDT -> exact internal buyback -> QT burn`.

The test requires:

- no accepted cycle before an independent external price shock;
- total temporary supply restored after success;
- internal synthetic reserve restored within two raw units;
- internal liquid reserve and `k` non-decreasing;
- positive consolidated liquid result after converting actual gas to USDT;
- replay and unauthorized calls rejected;
- stale quote / adverse external move reverting the complete transaction without leaving temporary issuance or changed internal reserves.

This is experimental fork evidence, not a production audit or a guarantee of future arbitrage availability.
