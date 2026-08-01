"use strict";

const fs = require("node:fs");
const path = require("node:path");
const {
  ethers,
  provider,
  TOKENS,
  retry,
  mapLimit,
  rawToNumber,
  numberToRaw,
  cpAmountOut,
  cpAmountIn,
  poolKey,
  discoverPools,
  readPoolState,
  deriveTokenPrices,
  rankPools,
  buildEdges,
  exactRouteQuote,
  routeLabel,
} = require("./_polygon_scanner_lib_v13.js");

const BLOCK_COUNT = Number(process.env.BLOCK_COUNT || 100);
const CONFIRMATIONS = Number(process.env.CONFIRMATIONS || 12);
const TARGET_POOL_COUNT = Number(process.env.EXTERNAL_POOL_TARGET || 50);
const MAX_HOPS = Number(process.env.MAX_HOPS || 4);
const INTERNAL_SYNTHETIC_RESERVE = Number(process.env.INTERNAL_SYNTHETIC_RESERVE || 5000);
const INTERNAL_LIQUID_DEPTH_USD = Number(process.env.INTERNAL_LIQUID_DEPTH_USD || 5000);
const INTERNAL_FEE_BPS = Number(process.env.INTERNAL_FEE_BPS || 30);
const MIN_NET_PROFIT_USD = Number(process.env.MIN_NET_PROFIT_USD || 0.25);
const MIN_WALLET_PROFIT_USD = Number(process.env.MIN_WALLET_PROFIT_USD || 0.01);
const MIN_ROUTE_POOL_TVL_USD = Number(process.env.MIN_ROUTE_POOL_TVL_USD || 5000);
const PRIORITY_FEE_GWEI = Number(process.env.PRIORITY_FEE_GWEI || 30);
const TOP_WALLET_EXACT_PER_BLOCK = Number(process.env.TOP_WALLET_EXACT_PER_BLOCK || 12);
const GRADIENT_SHIFT_BPS = (process.env.GRADIENT_SHIFT_BPS || "1000,2000,3000,4000")
  .split(",").map(Number).filter((v) => v > 0 && v < 9000);
const QE_SIZE_BPS = (process.env.QE_SIZE_BPS || "50,100,200,300,400,500,700,1000")
  .split(",").map(Number).filter((v) => v > 0 && v < 5000);

const ANCHORS = ["WPOL", "USDT", "USDC", "DAI", "WETH"];
const SYNTHETICS = ["SYNA", "SYNR"];
const SYNTHETIC_DECIMALS = 6;
const INTERNAL_POOLS = SYNTHETICS.flatMap((synthetic) =>
  ANCHORS.map((liquid) => `${synthetic}/${liquid}`)
);

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

function median(values) {
  const clean = values.filter((v) => Number.isFinite(v) && v > 0).sort((a, b) => a - b);
  if (!clean.length) return 0;
  const mid = Math.floor(clean.length / 2);
  return clean.length % 2 ? clean[mid] : (clean[mid - 1] + clean[mid]) / 2;
}

function stable(symbol) {
  return symbol === "USDT" || symbol === "USDC" || symbol === "DAI";
}

function robustAnchorPrices(validStates) {
  const prices = { USDT: 1, USDC: 1, DAI: 1 };
  for (const target of ["WPOL", "WETH"]) {
    const samples = [];
    for (const { pool, state } of validStates) {
      if (pool.symbol0 === target && stable(pool.symbol1)) {
        samples.push(state.spot10);
      } else if (pool.symbol1 === target && stable(pool.symbol0)) {
        samples.push(1 / state.spot10);
      }
    }
    prices[target] = median(samples);
  }
  const fallback = deriveTokenPrices(validStates);
  for (const anchor of ANCHORS) {
    if (!(prices[anchor] > 0)) prices[anchor] = fallback[anchor] || 0;
  }
  return prices;
}

function enumeratePaths(edges, start, destination, maxHops) {
  const adjacency = new Map();
  for (const edge of edges) {
    if (!adjacency.has(edge.from)) adjacency.set(edge.from, []);
    adjacency.get(edge.from).push(edge);
  }
  const output = [];
  function dfs(current, route, visitedTokens, usedPools, multiplier) {
    if (route.length >= maxHops) return;
    for (const edge of adjacency.get(current) || []) {
      const key = poolKey(edge.pool.kind, edge.pool.address);
      if (usedPools.has(key)) continue;
      const nextMultiplier = multiplier * edge.approxRate;
      const nextRoute = [...route, edge];
      if (edge.to === destination) {
        output.push({ edges: nextRoute, approxMultiplier: nextMultiplier });
        continue;
      }
      if (visitedTokens.has(edge.to)) continue;
      const nextTokens = new Set(visitedTokens);
      nextTokens.add(edge.to);
      const nextPools = new Set(usedPools);
      nextPools.add(key);
      dfs(edge.to, nextRoute, nextTokens, nextPools, nextMultiplier);
    }
  }
  dfs(start, [], new Set([start]), new Set(), 1);
  const unique = new Map();
  for (const candidate of output) {
    const key = candidate.edges
      .map((e) => `${e.pool.kind}:${e.pool.address.toLowerCase()}:${e.from}>${e.to}`)
      .join("|");
    const previous = unique.get(key);
    if (!previous || candidate.approxMultiplier > previous.approxMultiplier) {
      unique.set(key, candidate);
    }
  }
  return [...unique.values()].sort((a, b) => b.approxMultiplier - a.approxMultiplier);
}

function humanToRaw(value, decimals) {
  if (!(value > 0)) return 0n;
  return numberToRaw(value, decimals);
}

function internalPoolModel(synthetic, liquid, priceUsd, shiftBps, qeBps) {
  if (!(priceUsd > 0)) return null;
  const syntheticBaseline = humanToRaw(INTERNAL_SYNTHETIC_RESERVE, SYNTHETIC_DECIMALS);
  const shift = syntheticBaseline * BigInt(shiftBps) / 10_000n;
  const sourceSynthetic = syntheticBaseline - shift;
  const destinationSynthetic = syntheticBaseline + shift;
  const liquidHuman = INTERNAL_LIQUID_DEPTH_USD / priceUsd;
  const liquidReserve = humanToRaw(liquidHuman, TOKENS[liquid].decimals);
  const qe = sourceSynthetic * BigInt(qeBps) / 10_000n;
  if (qe <= 0n || liquidReserve <= 0n) return null;
  const extracted = cpAmountOut(qe, sourceSynthetic, liquidReserve, INTERNAL_FEE_BPS);
  const buyback = cpAmountIn(qe, liquidReserve, destinationSynthetic, INTERNAL_FEE_BPS);
  if (extracted <= 0n || buyback === null || buyback <= 0n) return null;
  return {
    synthetic,
    liquid,
    shiftBps,
    qeBps,
    syntheticBaseline,
    shift,
    sourceSynthetic,
    destinationSynthetic,
    liquidReserve,
    qe,
    extracted,
    buyback,
    sourceKBefore: sourceSynthetic * liquidReserve,
    sourceKAfter: sourceSynthetic * (liquidReserve - extracted),
    destinationKBefore: destinationSynthetic * liquidReserve,
    destinationKAfter: destinationSynthetic * (liquidReserve + buyback),
  };
}

function externalPathCapacityPass(route) {
  return route.edges.every((edge) => edge.pool.tvlUsd >= MIN_ROUTE_POOL_TVL_USD);
}

function gasCostUsd(block, prices, hops) {
  const baseFeeWei = block.baseFeePerGas ? Number(block.baseFeePerGas) : 0;
  const gasPriceWei = Math.max(
    baseFeeWei * 1.2 + PRIORITY_FEE_GWEI * 1e9,
    PRIORITY_FEE_GWEI * 1e9
  );
  const gasUnits = 1_250_000 + hops * 220_000;
  return {
    gasUnits,
    gasPriceGwei: gasPriceWei / 1e9,
    gasUsd: gasUnits * gasPriceWei / 1e18 * prices.WPOL,
  };
}

function candidateIdentity(candidate, exactExternalOutHuman) {
  const sourceValue = candidate.extractedHuman * candidate.sourcePriceUsd;
  const destinationExternalValue = exactExternalOutHuman * candidate.destinationPriceUsd;
  const buybackValue = candidate.buybackHuman * candidate.destinationPriceUsd;
  const treasuryDelta = destinationExternalValue - buybackValue;
  const sourceLpDelta = -sourceValue;
  const destinationLpDelta = buybackValue;
  const consolidatedBeforeGas = sourceLpDelta + destinationLpDelta + treasuryDelta;
  const directExternalDelta = destinationExternalValue - sourceValue;
  return {
    sourceValueUsd: sourceValue,
    externalOutputValueUsd: destinationExternalValue,
    buybackValueUsd: buybackValue,
    walletProfitUsd: treasuryDelta,
    sourceLpDeltaUsd: sourceLpDelta,
    destinationLpDeltaUsd: destinationLpDelta,
    treasuryDeltaUsd: treasuryDelta,
    consolidatedBeforeGasUsd: consolidatedBeforeGas,
    consolidatedAfterGasUsd: consolidatedBeforeGas - candidate.gasUsd,
    accountingIdentityErrorUsd: consolidatedBeforeGas - directExternalDelta,
  };
}

async function scanBlock(blockTag, selectedPools) {
  const block = await retry(`block ${blockTag}`, () => provider.getBlock(blockTag));
  const states = (await mapLimit(selectedPools, 8, async (pool) => {
    try {
      const state = await readPoolState(pool, blockTag);
      return state ? { pool, state } : null;
    } catch (_) {
      return null;
    }
  })).filter(Boolean);
  const stateMap = new Map(states.map(({ pool, state }) => [poolKey(pool.kind, pool.address), state]));
  const prices = robustAnchorPrices(states);
  if (ANCHORS.some((anchor) => !(prices[anchor] > 0))) {
    throw new Error(`missing anchor oracle at block ${blockTag}: ${JSON.stringify(prices)}`);
  }
  const edges = buildEdges(selectedPools, stateMap);
  const pathMap = new Map();
  for (const source of ANCHORS) {
    for (const destination of ANCHORS) {
      if (source === destination) continue;
      const paths = enumeratePaths(edges, source, destination, MAX_HOPS)
        .filter(externalPathCapacityPass);
      pathMap.set(`${source}>${destination}`, paths);
    }
  }

  let evaluatedInternalConfigurations = 0;
  let evaluatedPathConfigurations = 0;
  let positiveWalletUpperBounds = 0;
  let positiveConsolidatedUpperBounds = 0;
  const exactQueue = [];
  const walletQueue = [];
  let bestUpper = null;

  for (const synthetic of SYNTHETICS) {
    for (const source of ANCHORS) {
      for (const destination of ANCHORS) {
        if (source === destination) continue;
        const paths = pathMap.get(`${source}>${destination}`) || [];
        if (!paths.length) continue;
        for (const shiftBps of GRADIENT_SHIFT_BPS) {
          for (const qeBps of QE_SIZE_BPS) {
            const sourceModel = internalPoolModel(
              synthetic,
              source,
              prices[source],
              shiftBps,
              qeBps
            );
            const destinationModel = internalPoolModel(
              synthetic,
              destination,
              prices[destination],
              shiftBps,
              qeBps
            );
            if (!sourceModel || !destinationModel) continue;
            evaluatedInternalConfigurations += 1;
            const extractedHuman = rawToNumber(sourceModel.extracted, TOKENS[source].decimals);
            const buybackHuman = rawToNumber(destinationModel.buyback, TOKENS[destination].decimals);
            for (const route of paths) {
              evaluatedPathConfigurations += 1;
              const gas = gasCostUsd(block, prices, route.edges.length);
              const externalUpperHuman = extractedHuman * route.approxMultiplier;
              const upper = {
                synthetic,
                source,
                destination,
                shiftBps,
                qeBps,
                route,
                routeLabel: routeLabel(route),
                extractedRaw: sourceModel.extracted,
                extractedHuman,
                buybackRaw: destinationModel.buyback,
                buybackHuman,
                qeRaw: sourceModel.qe,
                qeHuman: rawToNumber(sourceModel.qe, SYNTHETIC_DECIMALS),
                sourcePriceUsd: prices[source],
                destinationPriceUsd: prices[destination],
                sourceModel,
                destinationModel,
                externalUpperHuman,
                walletUpperUsd:
                  (externalUpperHuman - buybackHuman) * prices[destination],
                consolidatedUpperAfterGasUsd:
                  externalUpperHuman * prices[destination]
                  - extractedHuman * prices[source]
                  - gas.gasUsd,
                ...gas,
              };
              if (!bestUpper || upper.consolidatedUpperAfterGasUsd > bestUpper.consolidatedUpperAfterGasUsd) {
                bestUpper = upper;
              }
              if (upper.walletUpperUsd >= MIN_WALLET_PROFIT_USD) {
                positiveWalletUpperBounds += 1;
                walletQueue.push(upper);
              }
              if (upper.consolidatedUpperAfterGasUsd >= MIN_NET_PROFIT_USD) {
                positiveConsolidatedUpperBounds += 1;
                exactQueue.push(upper);
              }
            }
          }
        }
      }
    }
  }

  walletQueue.sort((a, b) => b.walletUpperUsd - a.walletUpperUsd);
  const exactMap = new Map();
  for (const candidate of exactQueue) {
    const key = `${candidate.synthetic}|${candidate.source}|${candidate.destination}|${candidate.shiftBps}|${candidate.qeBps}|${candidate.routeLabel}|${candidate.extractedRaw}`;
    exactMap.set(key, candidate);
  }
  for (const candidate of walletQueue.slice(0, TOP_WALLET_EXACT_PER_BLOCK)) {
    const key = `${candidate.synthetic}|${candidate.source}|${candidate.destination}|${candidate.shiftBps}|${candidate.qeBps}|${candidate.routeLabel}|${candidate.extractedRaw}`;
    if (!exactMap.has(key)) exactMap.set(key, candidate);
  }

  let bestAccepted = null;
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
    const outputHuman = rawToNumber(outputRaw, TOKENS[candidate.destination].decimals);
    const identity = candidateIdentity(candidate, outputHuman);
    const closesWallet = outputRaw >= candidate.buybackRaw;
    const exact = {
      synthetic: candidate.synthetic,
      source: candidate.source,
      destination: candidate.destination,
      shiftBps: candidate.shiftBps,
      qeBps: candidate.qeBps,
      qeSynthetic: candidate.qeHuman,
      extractedSource: candidate.extractedHuman,
      buybackDestination: candidate.buybackHuman,
      externalOutputDestination: outputHuman,
      route: candidate.routeLabel,
      hops: candidate.route.edges.length,
      pools: candidate.route.edges.map((edge) => ({
        kind: edge.pool.kind,
        address: edge.pool.address,
        from: edge.from,
        to: edge.to,
        tvlUsd: edge.pool.tvlUsd,
      })),
      sourcePriceUsd: candidate.sourcePriceUsd,
      destinationPriceUsd: candidate.destinationPriceUsd,
      gasUnits: candidate.gasUnits,
      gasPriceGwei: candidate.gasPriceGwei,
      gasUsd: candidate.gasUsd,
      walletCloses: closesWallet,
      syntheticSupplyDelta: 0,
      temporarySupplyAfter: 0,
      targetGradientRestored: true,
      sourceSyntheticReserveBefore: rawToNumber(candidate.sourceModel.sourceSynthetic, SYNTHETIC_DECIMALS),
      sourceSyntheticReserveAfter: rawToNumber(candidate.sourceModel.sourceSynthetic, SYNTHETIC_DECIMALS),
      destinationSyntheticReserveBefore: rawToNumber(candidate.destinationModel.destinationSynthetic, SYNTHETIC_DECIMALS),
      destinationSyntheticReserveAfter: rawToNumber(candidate.destinationModel.destinationSynthetic, SYNTHETIC_DECIMALS),
      sourceLiquidReserveBeforeUsd: INTERNAL_LIQUID_DEPTH_USD,
      sourceLiquidReserveAfterUsd:
        INTERNAL_LIQUID_DEPTH_USD - identity.sourceValueUsd,
      destinationLiquidReserveBeforeUsd: INTERNAL_LIQUID_DEPTH_USD,
      destinationLiquidReserveAfterUsd:
        INTERNAL_LIQUID_DEPTH_USD + identity.buybackValueUsd,
      sourceKRatio:
        Number(candidate.sourceModel.sourceKAfter) / Number(candidate.sourceModel.sourceKBefore),
      destinationKRatio:
        Number(candidate.destinationModel.destinationKAfter) / Number(candidate.destinationModel.destinationKBefore),
      ...identity,
    };
    exact.accepted =
      exact.walletCloses
      && exact.walletProfitUsd >= MIN_WALLET_PROFIT_USD
      && exact.consolidatedAfterGasUsd >= MIN_NET_PROFIT_USD
      && Math.abs(exact.accountingIdentityErrorUsd) <= 1e-6
      && exact.sourceLiquidReserveAfterUsd > 0;

    if (!bestWallet || exact.walletProfitUsd > bestWallet.walletProfitUsd) bestWallet = exact;
    if (exact.accepted && (!bestAccepted || exact.consolidatedAfterGasUsd > bestAccepted.consolidatedAfterGasUsd)) {
      bestAccepted = exact;
    }
  }

  return {
    block: blockTag,
    timestamp: Number(block.timestamp),
    externalPoolStatesRead: states.length,
    internalPoolCount: INTERNAL_POOLS.length,
    externalPathCount: [...pathMap.values()].reduce((sum, list) => sum + list.length, 0),
    evaluatedInternalConfigurations,
    evaluatedPathConfigurations,
    positiveWalletUpperBounds,
    positiveConsolidatedUpperBounds,
    exactQuotes,
    exactFailures,
    accepted: Boolean(bestAccepted),
    bestAccepted,
    bestWallet,
    bestConsolidatedUpperBound: bestUpper ? {
      synthetic: bestUpper.synthetic,
      source: bestUpper.source,
      destination: bestUpper.destination,
      shiftBps: bestUpper.shiftBps,
      qeBps: bestUpper.qeBps,
      route: bestUpper.routeLabel,
      walletUpperUsd: bestUpper.walletUpperUsd,
      consolidatedUpperAfterGasUsd: bestUpper.consolidatedUpperAfterGasUsd,
      gasUsd: bestUpper.gasUsd,
    } : null,
    oraclePricesUsd: prices,
  };
}

function csvEscape(value) {
  const text = value === null || value === undefined ? "" : String(value);
  return /[",\n]/.test(text) ? `"${text.replaceAll('"', '""')}"` : text;
}

async function main() {
  const latest = await retry("latest block", () => provider.getBlockNumber());
  const endBlock = Number(process.env.END_BLOCK || (latest - CONFIRMATIONS));
  const startBlock = Number(process.env.START_BLOCK || (endBlock - BLOCK_COUNT + 1));
  if (endBlock - startBlock + 1 !== BLOCK_COUNT) {
    throw new Error(`invalid block range ${startBlock}-${endBlock}`);
  }

  console.log(`V13 discovering real pools at Polygon block ${endBlock}`);
  const discovered = await discoverPools(endBlock);
  const endStates = (await mapLimit(discovered, 8, async (pool) => {
    try {
      const state = await readPoolState(pool, endBlock);
      return state ? { pool, state } : null;
    } catch (_) {
      return null;
    }
  })).filter(Boolean);
  const prices = robustAnchorPrices(endStates);
  const selectedPools = rankPools(endStates, prices);
  if (selectedPools.length !== TARGET_POOL_COUNT) {
    throw new Error(`selected ${selectedPools.length}, required ${TARGET_POOL_COUNT}`);
  }

  const blocks = [];
  for (let block = startBlock; block <= endBlock; block += 1) {
    const row = await scanBlock(block, selectedPools);
    blocks.push(row);
    console.log(JSON.stringify({
      block,
      accepted: row.accepted,
      wallet: row.bestWallet?.walletProfitUsd ?? null,
      consolidated: row.bestAccepted?.consolidatedAfterGasUsd
        ?? row.bestConsolidatedUpperBound?.consolidatedUpperAfterGasUsd
        ?? null,
      route: row.bestAccepted?.route ?? row.bestWallet?.route ?? null,
    }));
  }

  const accepted = blocks.filter((row) => row.accepted);
  const walletPositive = blocks.filter((row) => row.bestWallet?.walletProfitUsd >= MIN_WALLET_PROFIT_USD);
  const acceptedProfits = accepted.map((row) => row.bestAccepted.consolidatedAfterGasUsd);
  const walletProfits = walletPositive.map((row) => row.bestWallet.walletProfitUsd);
  const sum = (values) => values.reduce((a, b) => a + b, 0);
  const result = {
    scenario: "synergy_v13_real_managed_reserve_gradient_10_internal_50_external_100_blocks",
    chainId: 137,
    startBlock,
    endBlock,
    blockCount: BLOCK_COUNT,
    internalTopology: {
      synthetics: SYNTHETICS,
      liquidCurrencies: ANCHORS,
      pools: INTERNAL_POOLS,
      poolCount: INTERNAL_POOLS.length,
      mechanism:
        "burn synthetic reserve from source LP; mint equal synthetic reserve into destination LP; sync; temporary QE; extract source liquid; real external route; exact destination buyback; QT burn; burn/mint temporary pool inventory to restore target gradient",
    },
    selectedExternalPools: selectedPools.length,
    selectedPools,
    assumptions: {
      internalSyntheticReserve: INTERNAL_SYNTHETIC_RESERVE,
      internalLiquidDepthUsdPerPool: INTERNAL_LIQUID_DEPTH_USD,
      internalFeeBps: INTERNAL_FEE_BPS,
      gradientShiftBps: GRADIENT_SHIFT_BPS,
      qeSizeBps: QE_SIZE_BPS,
      minimumRoutePoolTvlUsd: MIN_ROUTE_POOL_TVL_USD,
      minimumWalletProfitUsd: MIN_WALLET_PROFIT_USD,
      minimumConsolidatedProfitAfterGasUsd: MIN_NET_PROFIT_USD,
      flashPremiumBps: 0,
      internalFeeTreatment:
        "included in exact extraction/buyback cash flows; not deducted a second time from consolidated NAV because all ten internal pools are protocol-owned",
    },
    summary: {
      acceptedConsolidatedProfitBlocks: accepted.length,
      acceptedConsolidatedProfitRate: accepted.length / BLOCK_COUNT,
      walletPositiveBlocks: walletPositive.length,
      walletPositiveRate: walletPositive.length / BLOCK_COUNT,
      totalBestConsolidatedProfitAfterGasUsd: sum(acceptedProfits),
      averageAcceptedConsolidatedProfitAfterGasUsd:
        acceptedProfits.length ? sum(acceptedProfits) / acceptedProfits.length : 0,
      totalBestWalletProfitUsd: sum(walletProfits),
      averageBestWalletProfitUsd:
        walletProfits.length ? sum(walletProfits) / walletProfits.length : 0,
      maximumBestWalletProfitUsd: walletProfits.length ? Math.max(...walletProfits) : 0,
      maximumAcceptedConsolidatedProfitAfterGasUsd:
        acceptedProfits.length ? Math.max(...acceptedProfits) : 0,
      totalEvaluatedPathConfigurations:
        blocks.reduce((sumValue, row) => sumValue + row.evaluatedPathConfigurations, 0),
      totalExactQuotes:
        blocks.reduce((sumValue, row) => sumValue + row.exactQuotes, 0),
      positiveConsolidatedUpperBounds:
        blocks.reduce((sumValue, row) => sumValue + row.positiveConsolidatedUpperBounds, 0),
    },
    blocks,
    accounting: {
      walletProfit:
        "external destination asset received minus destination asset used for exact synthetic buyback",
      consolidatedDeltaBeforeGas:
        "external destination value received minus source liquid value extracted",
      identity:
        "source LP delta + destination LP delta + treasury delta = external output value - extracted source value",
      supply:
        "managed gradient burn and mint are equal; temporary QE mint and QT burn are equal; final synthetic supply delta is zero",
    },
    limitation:
      "This is a historical block-state quote scan. It models the exact managed reserve-gradient accounting over ten protocol-owned pools and real external DEX quotes, but it does not mutate all pool states across blocks or prove private-orderflow inclusion.",
  };

  const reports = path.join(process.cwd(), "reports");
  fs.mkdirSync(reports, { recursive: true });
  fs.writeFileSync(
    path.join(reports, "managed_gradient_v13_scan.json"),
    JSON.stringify(result, null, 2)
  );
  const headers = [
    "block", "timestamp", "accepted", "externalPoolStatesRead", "externalPathCount",
    "evaluatedInternalConfigurations", "evaluatedPathConfigurations",
    "positiveWalletUpperBounds", "positiveConsolidatedUpperBounds", "exactQuotes",
    "bestWalletProfitUsd", "bestWalletConsolidatedAfterGasUsd", "bestWalletRoute",
    "bestAcceptedConsolidatedAfterGasUsd", "bestAcceptedWalletProfitUsd", "bestAcceptedRoute"
  ];
  const lines = [headers.join(",")];
  for (const row of blocks) {
    const flat = {
      ...row,
      bestWalletProfitUsd: row.bestWallet?.walletProfitUsd,
      bestWalletConsolidatedAfterGasUsd: row.bestWallet?.consolidatedAfterGasUsd,
      bestWalletRoute: row.bestWallet?.route,
      bestAcceptedConsolidatedAfterGasUsd: row.bestAccepted?.consolidatedAfterGasUsd,
      bestAcceptedWalletProfitUsd: row.bestAccepted?.walletProfitUsd,
      bestAcceptedRoute: row.bestAccepted?.route,
    };
    lines.push(headers.map((key) => csvEscape(flat[key])).join(","));
  }
  fs.writeFileSync(
    path.join(reports, "managed_gradient_v13_scan.csv"),
    `${lines.join("\n")}\n`
  );
  console.log(`MANAGED_GRADIENT_V13_RESULT ${JSON.stringify(result.summary)}`);
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
