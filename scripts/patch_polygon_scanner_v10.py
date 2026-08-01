#!/usr/bin/env python3
"""Upgrade the V9 scanner to V10 exhaustive upper-bound pruning.

Every simple graph cycle and configured trade size is checked. The fee-adjusted
marginal route price is an upper bound on average AMM execution because every
swap moves price against the trader. Routes whose theoretical maximum cannot
cover exact QE/QT buyback, flash premium, gas and minimum profit are rigorously
pruned. Every remaining candidate receives an historical exact quote.
"""
from pathlib import Path

PATH = Path("scripts/scan_polygon_50_pool_100_blocks.js")
text = PATH.read_text(encoding="utf-8")

start_marker = "  const screened = [];\n"
end_marker = "\n  const accepted = Boolean(best && best.netProfitUsdt >= MIN_NET_PROFIT_USDT);"
start = text.index(start_marker, text.index("async function scanBlock"))
end = text.index(end_marker, start)

replacement = r'''  const eligibleCycles = allCycles.filter((route) =>
    route.edges.every((edge) => edge.pool.tvlUsd >= MIN_ROUTE_POOL_TVL_USD)
  );
  const upperBoundCandidates = [];
  let bestTheoretical = null;
  for (const route of eligibleCycles) {
    for (const size of QUOTE_SIZES_USDT) {
      const internal = internalRoundTrip(size);
      if (!internal) continue;
      const flashPremium = size * FLASH_PREMIUM_BPS / 10_000;
      const gasUnits = 450_000 + route.edges.length * 220_000;
      const gasUsdt = gasUnits * gasPriceWei / 1e18 * polPrice;
      // For a monotone AMM swap the current marginal, fee-adjusted spot rate is
      // an upper bound on average execution. Slippage can only reduce output.
      const spotUpperOut = size * route.approxMultiplier;
      const spotUpperNet = spotUpperOut - internal.buybackUsdt - flashPremium - gasUsdt;
      const candidate = { route, size, internal, flashPremium, gasUsdt, spotUpperOut, spotUpperNet };
      if (!bestTheoretical || spotUpperNet > bestTheoretical.spotUpperNet) bestTheoretical = candidate;
      if (spotUpperNet >= MIN_NET_PROFIT_USDT) upperBoundCandidates.push(candidate);
    }
  }
  upperBoundCandidates.sort((a, b) => b.spotUpperNet - a.spotUpperNet);

  let best = null;
  let exactCandidates = 0;
  for (const candidate of upperBoundCandidates) {
    const { route, size, internal, flashPremium, gasUsdt, spotUpperOut, spotUpperNet } = candidate;
    const amountOutRaw = await exactRouteQuote(route, internal.extractedRaw, blockTag, stateMap);
    if (amountOutRaw === null) continue;
    exactCandidates += 1;
    const externalOut = rawToNumber(amountOutRaw, TOKENS.USDT.decimals);
    const netProfit = externalOut - internal.buybackUsdt - flashPremium - gasUsdt;
    const profitBps = netProfit / size * 10_000;
    const record = {
      route: routeLabel(route),
      hops: route.edges.length,
      pools: route.edges.map((edge) => ({
        kind: edge.pool.kind,
        address: edge.pool.address,
        from: edge.from,
        to: edge.to,
        tvlUsd: edge.pool.tvlUsd,
      })),
      minimumRoutePoolTvlUsd: Math.min(...route.edges.map((edge) => edge.pool.tvlUsd)),
      sizeUsdt: size,
      qeMint: internal.qeMint,
      buybackUsdt: internal.buybackUsdt,
      spotUpperOutUsdt: spotUpperOut,
      spotUpperNetProfitUsdt: spotUpperNet,
      externalOutUsdt: externalOut,
      flashPremiumUsdt: flashPremium,
      gasUsdt,
      netProfitUsdt: netProfit,
      profitBps,
      approximateMultiplier: route.approxMultiplier,
    };
    if (!best || record.netProfitUsdt > best.netProfitUsdt) best = record;
  }
'''

text = text[:start] + replacement + text[end:]
text = text.replace(
    "    screenedCandidates: screened.length,",
    "    eligibleCycles: eligibleCycles.length,\n"
    "    upperBoundCandidates: upperBoundCandidates.length,\n"
    "    maximumSpotUpperBoundNetUsdt: bestTheoretical?.spotUpperNet ?? null,\n"
    "    maximumSpotUpperBoundRoute: bestTheoretical ? routeLabel(bestTheoretical.route) : null,\n"
    "    maximumSpotUpperBoundSizeUsdt: bestTheoretical?.size ?? null,",
)
text = text.replace(
    '"approximateCycles", "screenedCandidates", "exactCandidates"',
    '"approximateCycles", "eligibleCycles", "upperBoundCandidates", "exactCandidates", "maximumSpotUpperBoundNetUsdt"',
)
text = text.replace(
    "liquidity-capacity screen followed by exact V2 math and historical V3 quoter calls",
    "fee-adjusted marginal-price upper-bound pruning over every route/size, followed by exact V2 math and historical V3 quoter calls for every candidate whose theoretical maximum clears all costs",
)
text = text.replace(
    'scenario: "synergy_v9_real_polygon_50_pool_100_block_scan"',
    'scenario: "synergy_v10_exhaustive_upper_bound_polygon_50_pool_100_block_scan"',
)
PATH.write_text(text, encoding="utf-8")
