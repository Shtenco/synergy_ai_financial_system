# Federation V3 — Financial R&D boundary

This repository preserves historical experimental finance from Parts V/IX: AI central-bank ideas, AMM, QE/QT, MEV, liquidity loops, token mechanics and related simulations.

## Role
R&D source only. Canonical economic truth moved to `synergy_financial_os`; payment settlement to `synergy_pay_system`; institutional trading intelligence to `midas_ai`.

## Experiments to preserve
- AMM/liquidity mechanisms;
- issuance/burn/rebase/buyback;
- QE/QT scenarios;
- bridge/liquidity loops;
- market-impact and MEV research;
- external arbitrage/fee hypotheses;
- solvency and reserve stress.

## Required firewall
Every result must split:
`ExternalCash`, `ExternalLiabilities`, `HardNAV`, `InternalMark`, `ExternalPnL`, `FlashDebt`, `Fees`, `Slippage`, `Solvency`.

No internal token/LP revaluation is allowed to masquerade as externally realized value.
