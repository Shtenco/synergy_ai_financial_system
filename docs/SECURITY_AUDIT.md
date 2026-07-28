# Repository security review

## Status: experimental, not deployment ready

There is no "iron" MEV immunity on a transparent public mempool. Contract rules
cannot identify an arbitrary address as a bot, reverse a valid AMM trade, or take
funds the address never bonded. The strongest practical boundary is encrypted
order flow plus atomic limits and objective solver slashing.

## Remediations in this revision

- LP burning was removed from `LiquidityGrowthCycle`.
- All remove, swap, and add-liquidity legs now require caller-supplied minima.
- Arbitrary execution targets are pinned to the codehash approved by controller.
- Registered protocol assets must not decrease across graph execution.
- Every successful graph execution sends 20% of realized settlement profit to
  treasury; a reference migration token applies a uniform 20–30% transfer tax.
- MEV vesting cannot be claimed twice and its early-exit sink is no longer caller
  controlled.
- Solver bonds are bounded and objectively slashable only after expiry.

## Remaining external assurance blockers

The revision adds policy pause/cancel, an independent guardian, a 24-hour
N-of-M timelocked controller, and an ERC-3156 executor that atomically consumes
policy, enforces daily notional, validates a fresh bounded oracle price, checks
principal+premium+profit, and taxes realized profit. The remaining blockers are:

1. Compile and test all Solidity and fuzz reentrancy/token edge cases.
2. Run the pinned archival Polygon preflight against exact deployed bytecode.
3. Extend the fork suite with funded route fixtures and adversarial ordering.
4. Obtain multiple independent audits before funding.
5. Do not use any key posted in chat.

Uniform 20% transfer tax makes a two-hop round trip retain at most 64% before DEX
fees and slippage. It may suppress arbitrage but also fragments liquidity and can
make price correction impossible. Deploy it only after a separate market-impact
review; do not describe it as selective anti-bot protection.
