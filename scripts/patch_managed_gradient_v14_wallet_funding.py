#!/usr/bin/env python3
"""Add the strict atomic buyback-funding gate to the V14 scanner source."""
from pathlib import Path

path = Path("scripts/scan_managed_gradient_v14_stateful.js")
text = path.read_text(encoding="utf-8")

old = '''    const walletAfterRestoreRaw = forwardOutputRaw - restoration.inputRaw;
    if (walletAfterRestoreRaw < 0n) continue;
'''
new = '''    const walletAfterBuybackRaw = forwardOutputRaw - internal.buybackRaw;
    if (walletAfterBuybackRaw < 0n) continue;
    const walletAfterRestoreRaw = forwardOutputRaw - restoration.inputRaw;
    if (walletAfterRestoreRaw < 0n) continue;
'''
if old not in text:
    raise SystemExit("V14 wallet restoration gate not found")
text = text.replace(old, new, 1)

old = '''      walletSurplusDestination: rawToNumber(
        walletAfterRestoreRaw,
        TOKENS[internal.destination].decimals
      ),
'''
new = '''      walletAfterBuybackDestination: rawToNumber(
        walletAfterBuybackRaw,
        TOKENS[internal.destination].decimals
      ),
      walletSurplusDestination: rawToNumber(
        walletAfterRestoreRaw,
        TOKENS[internal.destination].decimals
      ),
'''
if old not in text:
    raise SystemExit("V14 wallet output record not found")
text = text.replace(old, new, 1)

old = '''      && exact.destinationRecycleSupplyAfter === 0
      && Math.abs(exact.sourceLiquidReserveAfter - exact.sourceLiquidReserveBefore) <= 1e-9
'''
new = '''      && exact.destinationRecycleSupplyAfter === 0
      && exact.walletAfterBuybackDestination >= 0
      && Math.abs(exact.sourceLiquidReserveAfter - exact.sourceLiquidReserveBefore) <= 1e-9
'''
if old not in text:
    raise SystemExit("V14 acceptance invariant insertion point not found")
text = text.replace(old, new, 1)

path.write_text(text, encoding="utf-8")
