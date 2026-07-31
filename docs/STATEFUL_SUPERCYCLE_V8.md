# SYNERGY V8 Stateful EVM Supercycle

This branch adds a deterministic, persistent 100-cycle EVM acceptance test for the complete sequence:

`FLASH GRAPH -> V6 REINVEST -> BACKED QE -> QT -> BUYBACK -> BURN -> LP REBALANCE -> PRICE DISPERSION -> NEXT FLASH GRAPH`.

The reviewed source bundle is stored in `.github/stateful_supercycle_v8_bundle.b64` and is materialized by CI before compilation. It contains:

- `contracts/supercycle/StatefulSupercycleV8.sol`;
- `test/stateful_supercycle_v8_100_cycles.js`;
- independent Python validator and evidence plotter;
- Russian technical documentation and the acceptance matrix.

The test preserves all balances and state between cycles: eight CPMM reserve pairs, ERC-20 balances, SYN supply, liabilities, backing reserve, protocol inventory, policy buffers, cumulative external revenue, QE/QT/buyback/burn/LP flows, and next-cycle price dispersion.

Core acceptance gates are checked after every stage:

- internal transfer revenue equals zero;
- `SYN supply = protocol inventory + external liabilities`;
- backing is not below liabilities;
- solvency, liquidity, and gas coverage are at least 120%;
- reserve policy ratio is at least 70%;
- buyback spend never exceeds the allocation sourced from realized external graph profit;
- only the FLASH GRAPH stage may increase cumulative external revenue.

The GitHub Actions artifact contains the full EVM log, JSON summary, 800-row stage trace, 100-row cycle trace, final pool reserves, independent validation verdict, and four evidence charts.

This is an economic architecture and accounting-continuity test. It does not claim that live mainnet price dispersion or flash liquidity will generate the same returns.
