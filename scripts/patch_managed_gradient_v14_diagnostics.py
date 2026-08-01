#!/usr/bin/env python3
"""Add fail-closed rejection diagnostics to the V14 stateful scanner.

This patch does not change candidate acceptance. It records why exact candidates
fail and preserves the strongest exact near-miss for economic analysis.
"""
from pathlib import Path

path = Path("scripts/scan_managed_gradient_v14_stateful.js")
text = path.read_text(encoding="utf-8")

old = '''  let exactAttempts = 0;
  let exactFailures = 0;
  let bestAccepted = null;
'''
new = '''  let exactAttempts = 0;
  let exactFailures = 0;
  const rejectionCounts = {
    forwardQuoteFailure: 0,
    restorationQuoteFailure: 0,
    atomicBuybackFundingFailure: 0,
    reverseRouteFundingFailure: 0,
    gasBudgetFailure: 0,
    realizedProfitFailure: 0,
    accountingFailure: 0,
    invariantFailure: 0,
  };
  let bestAccepted = null;
  let bestExactNearMiss = null;
  let bestReverseFundingNearMiss = null;
'''
if old not in text:
    raise SystemExit("V14 exact counter insertion point not found")
text = text.replace(old, new, 1)

old = '''    if (forwardOutputRaw === null || forwardOutputRaw <= 0n) {
      exactFailures += 1;
      continue;
    }
'''
new = '''    if (forwardOutputRaw === null || forwardOutputRaw <= 0n) {
      exactFailures += 1;
      rejectionCounts.forwardQuoteFailure += 1;
      continue;
    }
'''
if old not in text:
    raise SystemExit("V14 forward quote failure block not found")
text = text.replace(old, new, 1)

old = '''    if (!restoration) {
      exactFailures += 1;
      continue;
    }
'''
new = '''    if (!restoration) {
      exactFailures += 1;
      rejectionCounts.restorationQuoteFailure += 1;
      continue;
    }
'''
if old not in text:
    raise SystemExit("V14 restoration quote failure block not found")
text = text.replace(old, new, 1)

old = '''    const walletAfterBuybackRaw = forwardOutputRaw - internal.buybackRaw;
    if (walletAfterBuybackRaw < 0n) continue;
    const walletAfterRestoreRaw = forwardOutputRaw - restoration.inputRaw;
    if (walletAfterRestoreRaw < 0n) continue;
'''
new = '''    const walletAfterBuybackRaw = forwardOutputRaw - internal.buybackRaw;
    if (walletAfterBuybackRaw < 0n) {
      rejectionCounts.atomicBuybackFundingFailure += 1;
      continue;
    }
    const walletAfterRestoreRaw = forwardOutputRaw - restoration.inputRaw;
    if (walletAfterRestoreRaw < 0n) {
      rejectionCounts.reverseRouteFundingFailure += 1;
      const deficitRaw = -walletAfterRestoreRaw;
      const deficitHuman = rawToNumber(deficitRaw, TOKENS[internal.destination].decimals);
      const fundingNearMiss = {
        synthetic: internal.synthetic,
        source: internal.source,
        destination: internal.destination,
        shiftBps: internal.shiftBps,
        qeBps: internal.qeBps,
        forwardRoute: routeLabel(routePair.forward),
        restorationRoute: routeLabel(routePair.restore),
        forwardOutputDestination: rawToNumber(
          forwardOutputRaw,
          TOKENS[internal.destination].decimals
        ),
        exactBuybackDestination: rawToNumber(
          internal.buybackRaw,
          TOKENS[internal.destination].decimals
        ),
        restorationInputDestination: rawToNumber(
          restoration.inputRaw,
          TOKENS[internal.destination].decimals
        ),
        reverseFundingDeficitDestination: deficitHuman,
        reverseFundingDeficitUsd: deficitHuman * prices[internal.destination],
        gasUsd: candidate.gasUsd,
      };
      if (
        !bestReverseFundingNearMiss
        || fundingNearMiss.reverseFundingDeficitUsd
          < bestReverseFundingNearMiss.reverseFundingDeficitUsd
      ) {
        bestReverseFundingNearMiss = fundingNearMiss;
      }
      continue;
    }
'''
if old not in text:
    raise SystemExit("V14 patched wallet funding block not found")
text = text.replace(old, new, 1)

old = '''    const gasRaw = ceilUsdtRaw(candidate.gasUsd);
    if (tentativeTreasury.USDT < gasRaw) continue;
'''
new = '''    const gasRaw = ceilUsdtRaw(candidate.gasUsd);
    if (tentativeTreasury.USDT < gasRaw) {
      rejectionCounts.gasBudgetFailure += 1;
      continue;
    }
'''
if old not in text:
    raise SystemExit("V14 gas budget block not found")
text = text.replace(old, new, 1)

old = '''    if (exact.accepted && (!bestAccepted || exact.realizedNavDeltaUsd > bestAccepted.realizedNavDeltaUsd)) {
      bestAccepted = exact;
    }
'''
new = '''    const nearMissSummary = {
      synthetic: exact.synthetic,
      source: exact.source,
      destination: exact.destination,
      shiftBps: exact.shiftBps,
      qeBps: exact.qeBps,
      forwardRoute: exact.forwardRoute,
      restorationRoute: exact.restorationRoute,
      forwardOutputDestination: exact.forwardOutputDestination,
      exactBuybackDestination: exact.exactBuybackDestination,
      restorationInputDestination: exact.restorationInputDestination,
      walletAfterBuybackDestination: exact.walletAfterBuybackDestination,
      walletSurplusDestination: exact.walletSurplusDestination,
      restorationExcessSource: exact.restorationExcessSource,
      gasUsd: exact.gasUsd,
      realizedNavDeltaUsd: exact.realizedNavDeltaUsd,
      directRealizedDeltaUsd: exact.directRealizedDeltaUsd,
      accountingIdentityErrorUsd: exact.accountingIdentityErrorUsd,
      sourceKRatio: exact.sourceKRatio,
      destinationKRatio: exact.destinationKRatio,
      accepted: exact.accepted,
    };
    if (
      !bestExactNearMiss
      || nearMissSummary.realizedNavDeltaUsd > bestExactNearMiss.realizedNavDeltaUsd
    ) {
      bestExactNearMiss = nearMissSummary;
    }

    if (!exact.accepted) {
      if (exact.realizedNavDeltaUsd < MIN_REALIZED_PROFIT_USD) {
        rejectionCounts.realizedProfitFailure += 1;
      } else if (Math.abs(exact.accountingIdentityErrorUsd) > 2e-5) {
        rejectionCounts.accountingFailure += 1;
      } else {
        rejectionCounts.invariantFailure += 1;
      }
    }

    if (exact.accepted && (!bestAccepted || exact.realizedNavDeltaUsd > bestAccepted.realizedNavDeltaUsd)) {
      bestAccepted = exact;
    }
'''
if old not in text:
    raise SystemExit("V14 accepted candidate block not found")
text = text.replace(old, new, 1)

old = '''    exactAttempts,
    exactFailures,
    accepted: Boolean(bestAccepted),
'''
new = '''    exactAttempts,
    exactFailures,
    rejectionCounts,
    bestExactNearMiss,
    bestReverseFundingNearMiss,
    accepted: Boolean(bestAccepted),
'''
if old not in text:
    raise SystemExit("V14 block return diagnostic insertion point not found")
text = text.replace(old, new, 1)

old = '''      exactAttempts: blocks.reduce((sum, row) => sum + row.exactAttempts, 0),
      exactFailures: blocks.reduce((sum, row) => sum + row.exactFailures, 0),
    },
'''
new = '''      exactAttempts: blocks.reduce((sum, row) => sum + row.exactAttempts, 0),
      exactFailures: blocks.reduce((sum, row) => sum + row.exactFailures, 0),
      exactRejectionCounts: blocks.reduce((totals, row) => {
        for (const [key, value] of Object.entries(row.rejectionCounts || {})) {
          totals[key] = (totals[key] || 0) + value;
        }
        return totals;
      }, {}),
      bestExactNearMiss: blocks
        .map((row) => row.bestExactNearMiss)
        .filter(Boolean)
        .sort((a, b) => b.realizedNavDeltaUsd - a.realizedNavDeltaUsd)[0] || null,
      bestReverseFundingNearMiss: blocks
        .map((row) => row.bestReverseFundingNearMiss)
        .filter(Boolean)
        .sort((a, b) => a.reverseFundingDeficitUsd - b.reverseFundingDeficitUsd)[0] || null,
    },
'''
if old not in text:
    raise SystemExit("V14 summary diagnostic insertion point not found")
text = text.replace(old, new, 1)

path.write_text(text, encoding="utf-8")
