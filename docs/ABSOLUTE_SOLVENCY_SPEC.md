# Synergy Absolute Solvency Specification

## Objective

Transform the under-collateralized QT system from negative equity to strict solvency in one autonomous run without minting new SYN during recovery.

## Initial balance sheet

- SYN liabilities at par: 100 SYN = 100 WPOL.
- Protocol WPOL assets: 43 WPOL.
- Initial equity: -57 WPOL.
- Initial reserve coverage: 43%.
- Flash lender liquidity is excluded from protocol assets because it belongs to the lender.

## Solvency definition

The recovery is complete only when all conditions hold simultaneously:

1. `protocol WPOL assets >= outstanding SYN supply × par price`.
2. Equity is non-negative.
3. Reserve coverage is at least 100%.
4. No SYN is minted after bootstrap.
5. Keeper execution remains profitable after standardized gas at 274 gwei.
6. The controller has no owner after bootstrap.
7. The controller halts automatically once solvency is reached.

## Recovery policy

Each cycle uses existing protocol SYN inventory and performs:

1. Open a bounded QT auction for 2 SYN at 0.75 WPOL per SYN.
2. Commit and reveal after two blocks.
3. Flash-borrow 1.5 WPOL.
4. Purchase 2 existing SYN from protocol inventory.
5. Redeem the 2 SYN against the buyback escrow at 1 WPOL per SYN.
6. Burn the 2 SYN immediately.
7. Repay flash principal and 5 bps premium.
8. Pay a fixed 0.30 WPOL keeper reward.
9. Recycle all remaining solver surplus and all auction proceeds above reserve floors back into the buyback escrow.

## Per-cycle economics

- Liability reduction: 2.00000 WPOL at par.
- Keeper reward leakage: 0.30000 WPOL.
- Flash fee leakage: 0.00075 WPOL.
- Net protocol asset reduction: 0.30075 WPOL.
- Net equity improvement: 1.69925 WPOL.

## Required recovery horizon

Starting deficit: 57 WPOL.

Minimum full cycles required:

`ceil(57 / 1.69925) = 34 cycles`.

Expected terminal balance sheet after 34 cycles:

- SYN supply: 100 -> 32.
- SYN burned: 68.
- Protocol WPOL assets: 43 -> 32.7745.
- Equity: -57 -> +0.7745 WPOL.
- Reserve coverage: 102.4203125%.
- Total keeper rewards: 10.2 WPOL.
- Total flash fees: 0.0255 WPOL.

## Safety constraints

- No minting after bootstrap.
- Fixed maximum cycle size.
- Demand liquidity and inventory caps.
- Two-block commit/reveal delay.
- Permissionless keepers.
- Irreversible removal of bootstrap authority.
- Automatic terminal halt when solvency is reached.
- Terminal calls revert after halt.
