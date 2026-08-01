#!/usr/bin/env python3
"""Cache identical historical external quotes in the V13 scanner."""
from pathlib import Path

path = Path("scripts/scan_managed_gradient_v13.js")
text = path.read_text(encoding="utf-8")
old = '''  let bestAccepted = null;
  let bestWallet = null;
  let exactQuotes = 0;
  let exactFailures = 0;
  for (const candidate of exactMap.values()) {
    const outputRaw = await exactRouteQuote(
      candidate.route,
      candidate.extractedRaw,
      blockTag,
      stateMap
    );
    if (outputRaw === null) {
      exactFailures += 1;
      continue;
    }
    exactQuotes += 1;
'''
new = '''  let bestAccepted = null;
  let bestWallet = null;
  let exactQuotes = 0;
  let exactFailures = 0;
  let uniqueExternalQuoteCalls = 0;
  const externalQuoteCache = new Map();
  for (const candidate of exactMap.values()) {
    const quoteKey = `${candidate.source}|${candidate.destination}|${candidate.routeLabel}|${candidate.extractedRaw}`;
    let outputRaw;
    if (externalQuoteCache.has(quoteKey)) {
      outputRaw = externalQuoteCache.get(quoteKey);
    } else {
      outputRaw = await exactRouteQuote(
        candidate.route,
        candidate.extractedRaw,
        blockTag,
        stateMap
      );
      externalQuoteCache.set(quoteKey, outputRaw);
      uniqueExternalQuoteCalls += 1;
    }
    if (outputRaw === null) {
      exactFailures += 1;
      continue;
    }
    exactQuotes += 1;
'''
if old not in text:
    raise SystemExit("exact quote loop not found")
text = text.replace(old, new)
text = text.replace(
    '''    exactQuotes,
    exactFailures,
    accepted: Boolean(bestAccepted),''',
    '''    exactQuotes,
    exactFailures,
    uniqueExternalQuoteCalls,
    accepted: Boolean(bestAccepted),'''
)
text = text.replace(
    '''      totalExactQuotes:
        blocks.reduce((sumValue, row) => sumValue + row.exactQuotes, 0),
      positiveConsolidatedUpperBounds:''',
    '''      totalExactQuotes:
        blocks.reduce((sumValue, row) => sumValue + row.exactQuotes, 0),
      totalUniqueExternalQuoteCalls:
        blocks.reduce((sumValue, row) => sumValue + row.uniqueExternalQuoteCalls, 0),
      positiveConsolidatedUpperBounds:'''
)
path.write_text(text, encoding="utf-8")
