# SYNERGY V8 Stateful EVM Supercycle

This branch implements a persistent 100-cycle acceptance harness for:

`FLASH GRAPH -> V6 REINVEST -> BACKED QE -> QT -> BUYBACK -> BURN -> LP REBALANCE -> PRICE DISPERSION -> NEXT FLASH GRAPH`.

No fixture reset is allowed. Eight CPMM pools, ERC-20 balances, SYN supply, external liabilities, backing, protocol inventory, policy reserves, cumulative flows and next-cycle price dispersion survive from one cycle to the next.

## Correct external-value accounting

SYN and SYNR have zero external asset value inside the protocol boundary. Flash routes are ranked by route-specific change in consolidated POL/USDT NAV, not by the final POL token balance. In particular, `POL -> external SYN -> internal USDT -> internal POL` is not treated as external profit because it can return protocol-owned internal reserves while sending flash principal outside the boundary. Actual execution must also satisfy `afterNAV >= beforeNAV`.

## Productive backed QE

BACKED QE is protocol-owned productive liquidity, not a gift of newly minted public liabilities. It:

- mints only to the engine;
- does not increase external liabilities;
- reserves an equal amount of existing free external capital;
- deploys that reserve into internal LP during `LP_REBALANCE`;
- is bounded by fraction, epoch cap and 120% liquidity headroom.

QT retires only pre-existing, voluntarily tendered liabilities. A consolidated-equity floor is checked after every stage.

## Acceptance gates

- internal transfer revenue equals zero;
- `SYN supply = protocol inventory + external liabilities`;
- backing is not below liabilities;
- consolidated equity is not below bootstrap equity;
- solvency, liquidity and gas coverage are at least 120%;
- reserve policy ratio is at least 70%;
- buyback spend does not exceed allocation from realised external graph profit;
- only `FLASH GRAPH` may increase cumulative external revenue.

## Two execution surfaces

CI first runs an integer-exact shadow using the same 18-decimal integer CPMM arithmetic, validates all 800 rows independently, and renders evidence charts. It then compiles Solidity 0.8.26, runs the 100-cycle Hardhat EVM test, independently validates the EVM trace and requires tight numerical shadow/EVM parity.

The current integer-exact reference result has 100 cycles, 800 stages, 16 profitable flash cycles, zero internal revenue and an increase in consolidated equity from 30,000,000 to approximately 30,058,942 POL. This is not labelled an EVM PASS until GitHub Actions actually starts and completes the Solidity/Hardhat steps.

The test establishes accounting continuity for a deterministic scenario. It does not promise live mainnet profitability, available flash liquidity, identical price dispersion, or production security without independent audit.
