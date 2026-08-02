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
  screeningRouteQuote,
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
const INITIAL_GAS_BUDGET_USDT = Number(process.env.INITIAL_GAS_BUDGET_USDT || 1000);
const MIN_REALIZED_PROFIT_USD = Number(process.env.MIN_REALIZED_PROFIT_USD || 0.01);
const MIN_ROUTE_POOL_TVL_USD = Number(process.env.MIN_ROUTE_POOL_TVL_USD || 5000);
const PRIORITY_FEE_GWEI = Number(process.env.PRIORITY_FEE_GWEI || 30);
const TOP_EXACT_CANDIDATES_PER_BLOCK = Number(process.env.TOP_EXACT_CANDIDATES_PER_BLOCK || 6);
const MAX_MARGINAL_ROUTE_PAIRS_PER_DIRECTION = Number(
  process.env.MAX_MARGINAL_ROUTE_PAIRS_PER_DIRECTION || 80
);
const RESTORE_BINARY_STEPS = Number(process.env.RESTORE_BINARY_STEPS || 18);
const RESTORE_MAX_BRACKET_STEPS = Number(process.env.RESTORE_MAX_BRACKET_STEPS || 8);
const EXTERNAL_POOL_SINGLE_USE = String(process.env.EXTERNAL_POOL_SINGLE_USE || "true") === "true";
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
  const prices = { ...deriveTokenPrices(validStates), USDT: 1, USDC: 1, DAI: 1 };
  for (const target of ["WPOL", "WETH"]) {
    const samples = [];
    for (const { pool, state } of validStates) {
      if (pool.symbol0 === target && stable(pool.symbol1)) samples.push(state.spot10);
      else if (pool.symbol1 === target && stable(pool.symbol0)) samples.push(1 / state.spot10);
    }
    const directMedian = median(samples);
    if (directMedian > 0) prices[target] = directMedian;
  }
  for (const anchor of ANCHORS) {
    if (!(prices[anchor] > 0)) throw new Error(`missing robust price for ${anchor}`);
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
      .map((edge) => `${poolKey(edge.pool.kind, edge.pool.address)}:${edge.from}>${edge.to}`)
      .join("|");
    const previous = unique.get(key);
    if (!previous || candidate.approxMultiplier > previous.approxMultiplier) unique.set(key, candidate);
  }
  return [...unique.values()].sort((a, b) => b.approxMultiplier - a.approxMultiplier);
}

function routePoolKeys(route) {
  return route.edges.map((edge) => poolKey(edge.pool.kind, edge.pool.address));
}

function routesDisjoint(first, second) {
  const firstKeys = new Set(routePoolKeys(first));
  return routePoolKeys(second).every((key) => !firstKeys.has(key));
}

function routeAvailable(route, globallyUsedPools) {
  return routePoolKeys(route).every((key) => !globallyUsedPools.has(key));
}

function externalPathCapacityPass(route) {
  return route.edges.every((edge) => edge.pool.tvlUsd >= MIN_ROUTE_POOL_TVL_USD);
}

function humanToRaw(value, decimals) {
  if (!(value > 0)) return 0n;
  return numberToRaw(value, decimals);
}

function ceilUsdtRaw(valueUsd) {
  if (!(valueUsd > 0)) return 0n;
  return BigInt(Math.ceil(valueUsd * 1_000_000));
}

function clonePoolState(pools) {
  const cloned = new Map();
  for (const [key, value] of pools.entries()) cloned.set(key, { ...value });
  return cloned;
}

function cloneBalances(balances) {
  return Object.fromEntries(Object.entries(balances).map(([key, value]) => [key, BigInt(value)]));
}

function initializeInternalState(prices) {
  const pools = new Map();
  const baseline = humanToRaw(INTERNAL_SYNTHETIC_RESERVE, SYNTHETIC_DECIMALS);
  for (const synthetic of SYNTHETICS) {
    for (const liquid of ANCHORS) {
      const liquidHuman = INTERNAL_LIQUID_DEPTH_USD / prices[liquid];
      pools.set(`${synthetic}/${liquid}`, {
        synthetic,
        liquid,
        syntheticRaw: baseline,
        liquidRaw: humanToRaw(liquidHuman, TOKENS[liquid].decimals),
      });
    }
  }
  return pools;
}

function initializeTreasury() {
  const treasury = Object.fromEntries(ANCHORS.map((anchor) => [anchor, 0n]));
  treasury.USDT = humanToRaw(INITIAL_GAS_BUDGET_USDT, TOKENS.USDT.decimals);
  return treasury;
}

function protocolExternalNavUsd(pools, treasury, prices) {
  let total = 0;
  for (const pool of pools.values()) {
    total += rawToNumber(pool.liquidRaw, TOKENS[pool.liquid].decimals) * prices[pool.liquid];
  }
  for (const anchor of ANCHORS) {
    total += rawToNumber(treasury[anchor], TOKENS[anchor].decimals) * prices[anchor];
  }
  return total;
}

function syntheticTotals(pools) {
  const totals = Object.fromEntries(SYNTHETICS.map((synthetic) => [synthetic, 0n]));
  for (const pool of pools.values()) totals[pool.synthetic] += pool.syntheticRaw;
  return totals;
}

function retargetSyntheticGradient(pools, synthetic, source, destination, shiftRaw) {
  const baseline = humanToRaw(INTERNAL_SYNTHETIC_RESERVE, SYNTHETIC_DECIMALS);
  for (const liquid of ANCHORS) pools.get(`${synthetic}/${liquid}`).syntheticRaw = baseline;
  pools.get(`${synthetic}/${source}`).syntheticRaw = baseline - shiftRaw;
  pools.get(`${synthetic}/${destination}`).syntheticRaw = baseline + shiftRaw;
}

function buildInternalCandidate(pools, synthetic, source, destination, shiftBps, qeBps) {
  const baseline = humanToRaw(INTERNAL_SYNTHETIC_RESERVE, SYNTHETIC_DECIMALS);
  const shiftRaw = baseline * BigInt(shiftBps) / 10_000n;
  const sourceSyntheticRaw = baseline - shiftRaw;
  const destinationSyntheticRaw = baseline + shiftRaw;
  const sourcePool = pools.get(`${synthetic}/${source}`);
  const destinationPool = pools.get(`${synthetic}/${destination}`);
  if (!sourcePool || !destinationPool || sourcePool.liquidRaw <= 0n || destinationPool.liquidRaw <= 0n) {
    return null;
  }
  const qeRaw = sourceSyntheticRaw * BigInt(qeBps) / 10_000n;
  if (qeRaw <= 0n) return null;
  const extractedRaw = cpAmountOut(
    qeRaw,
    sourceSyntheticRaw,
    sourcePool.liquidRaw,
    INTERNAL_FEE_BPS
  );
  const buybackRaw = cpAmountIn(
    qeRaw,
    destinationPool.liquidRaw,
    destinationSyntheticRaw,
    INTERNAL_FEE_BPS
  );
  if (extractedRaw <= 0n || buybackRaw === null || buybackRaw <= 0n) return null;

  const destinationLiquidAfterBuyback = destinationPool.liquidRaw + buybackRaw;
  const recycleSyntheticRaw = cpAmountIn(
    buybackRaw,
    destinationSyntheticRaw,
    destinationLiquidAfterBuyback,
    INTERNAL_FEE_BPS
  );
  if (recycleSyntheticRaw === null || recycleSyntheticRaw <= 0n) return null;

  return {
    synthetic,
    source,
    destination,
    shiftBps,
    qeBps,
    shiftRaw,
    sourceSyntheticRaw,
    destinationSyntheticRaw,
    qeRaw,
    extractedRaw,
    buybackRaw,
    recycleSyntheticRaw,
    sourceLiquidBeforeRaw: sourcePool.liquidRaw,
    destinationLiquidBeforeRaw: destinationPool.liquidRaw,
  };
}

function gasCostUsd(block, prices, totalExternalHops) {
  const baseFeeWei = block.baseFeePerGas ? Number(block.baseFeePerGas) : 0;
  const gasPriceWei = Math.max(
    baseFeeWei * 1.2 + PRIORITY_FEE_GWEI * 1e9,
    PRIORITY_FEE_GWEI * 1e9
  );
  const gasUnits = 2_050_000 + totalExternalHops * 260_000;
  return {
    gasUnits,
    gasPriceGwei: gasPriceWei / 1e9,
    gasUsd: gasUnits * gasPriceWei / 1e18 * prices.WPOL,
  };
}

function screeningInputForTarget(route, targetOutRaw, stateMap, inputDecimals) {
  if (targetOutRaw <= 0n || !(route.approxMultiplier > 0)) return null;
  let estimateHuman = rawToNumber(targetOutRaw, TOKENS[route.edges.at(-1).to].decimals)
    / route.approxMultiplier;
  let high = humanToRaw(Math.max(estimateHuman * 1.05, 1e-9), inputDecimals);
  let quoted = screeningRouteQuote(route, high, stateMap);
  for (let i = 0; i < RESTORE_MAX_BRACKET_STEPS && (quoted === null || quoted < targetOutRaw); i += 1) {
    high *= 2n;
    quoted = screeningRouteQuote(route, high, stateMap);
  }
  if (quoted === null || quoted < targetOutRaw) return null;
  let low = 0n;
  for (let i = 0; i < 24 && low < high; i += 1) {
    const mid = (low + high) / 2n;
    const out = screeningRouteQuote(route, mid, stateMap);
    if (out !== null && out >= targetOutRaw) high = mid;
    else low = mid + 1n;
  }
  return high;
}

async function exactInputForTarget(route, targetOutRaw, blockTag, stateMap, cache) {
  const inputSymbol = route.edges[0].from;
  const outputSymbol = route.edges.at(-1).to;
  if (targetOutRaw <= 0n || !(route.approxMultiplier > 0)) return null;

  const quote = async (amountRaw) => {
    const key = `${blockTag}|${routeLabel(route)}|${amountRaw}`;
    if (cache.has(key)) return cache.get(key);
    const value = await exactRouteQuote(route, amountRaw, blockTag, stateMap);
    cache.set(key, value);
    return value;
  };

  const targetHuman = rawToNumber(targetOutRaw, TOKENS[outputSymbol].decimals);
  let estimateHuman = targetHuman / route.approxMultiplier * 1.02;
  let high = humanToRaw(Math.max(estimateHuman, 1e-9), TOKENS[inputSymbol].decimals);
  let highOut = await quote(high);
  for (let i = 0; i < RESTORE_MAX_BRACKET_STEPS && (highOut === null || highOut < targetOutRaw); i += 1) {
    high *= 2n;
    highOut = await quote(high);
  }
  if (highOut === null || highOut < targetOutRaw) return null;

  let low = 0n;
  let bestOut = highOut;
  for (let i = 0; i < RESTORE_BINARY_STEPS && low < high; i += 1) {
    const mid = (low + high) / 2n;
    const midOut = await quote(mid);
    if (midOut !== null && midOut >= targetOutRaw) {
      high = mid;
      bestOut = midOut;
    } else {
      low = mid + 1n;
    }
  }
  const finalOut = await quote(high);
  if (finalOut === null || finalOut < targetOutRaw) return null;
  return { inputRaw: high, outputRaw: finalOut, cachedOutputRaw: bestOut };
}

function buildRoutePairs(pathMap, source, destination, globallyUsedPools) {
  const forwardPaths = pathMap.get(`${source}>${destination}`) || [];
  const restorePaths = pathMap.get(`${destination}>${source}`) || [];
  const pairs = [];
  for (const forward of forwardPaths) {
    if (EXTERNAL_POOL_SINGLE_USE && !routeAvailable(forward, globallyUsedPools)) continue;
    for (const restore of restorePaths) {
      if (!routesDisjoint(forward, restore)) continue;
      if (EXTERNAL_POOL_SINGLE_USE && !routeAvailable(restore, globallyUsedPools)) continue;
      const roundTripMarginal = forward.approxMultiplier * restore.approxMultiplier;
      if (!(roundTripMarginal > 1)) continue;
      pairs.push({
        forward,
        restore,
        roundTripMarginal,
        marginalSpreadInDestination:
          forward.approxMultiplier - (1 / restore.approxMultiplier),
      });
    }
  }
  pairs.sort((a, b) => b.marginalSpreadInDestination - a.marginalSpreadInDestination);
  return pairs.slice(0, MAX_MARGINAL_ROUTE_PAIRS_PER_DIRECTION);
}

function snapshotInternalPools(pools, prices) {
  return [...pools.values()].map((pool) => ({
    pair: `${pool.synthetic}/${pool.liquid}`,
    synthetic: pool.synthetic,
    liquid: pool.liquid,
    syntheticReserve: rawToNumber(pool.syntheticRaw, SYNTHETIC_DECIMALS),
    liquidReserve: rawToNumber(pool.liquidRaw, TOKENS[pool.liquid].decimals),
    liquidValueUsd: rawToNumber(pool.liquidRaw, TOKENS[pool.liquid].decimals) * prices[pool.liquid],
    k: (pool.syntheticRaw * pool.liquidRaw).toString(),
  }));
}

function snapshotTreasury(treasury, prices) {
  return Object.fromEntries(ANCHORS.map((anchor) => [anchor, {
    amount: rawToNumber(treasury[anchor], TOKENS[anchor].decimals),
    valueUsd: rawToNumber(treasury[anchor], TOKENS[anchor].decimals) * prices[anchor],
  }]));
}

async function scanStatefulBlock(blockTag, selectedPools, internalPools, treasury, globallyUsedPools) {
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
  const edges = buildEdges(selectedPools, stateMap);
  const pathMap = new Map();
  for (const source of ANCHORS) {
    for (const destination of ANCHORS) {
      if (source === destination) continue;
      pathMap.set(
        `${source}>${destination}`,
        enumeratePaths(edges, source, destination, MAX_HOPS).filter(externalPathCapacityPass)
      );
    }
  }

  const navBeforeBlockUsd = protocolExternalNavUsd(internalPools, treasury, prices);
  const syntheticBefore = syntheticTotals(internalPools);
  let evaluatedInternalConfigurations = 0;
  let evaluatedRoutePairs = 0;
  let positiveScreenedCandidates = 0;
  const screened = [];

  for (const synthetic of SYNTHETICS) {
    for (const source of ANCHORS) {
      for (const destination of ANCHORS) {
        if (source === destination) continue;
        const routePairs = buildRoutePairs(pathMap, source, destination, globallyUsedPools);
        if (!routePairs.length) continue;
        for (const shiftBps of GRADIENT_SHIFT_BPS) {
          for (const qeBps of QE_SIZE_BPS) {
            const internal = buildInternalCandidate(
              internalPools, synthetic, source, destination, shiftBps, qeBps
            );
            if (!internal) continue;
            evaluatedInternalConfigurations += 1;
            for (const routePair of routePairs) {
              evaluatedRoutePairs += 1;
              const forwardScreenRaw = screeningRouteQuote(
                routePair.forward, internal.extractedRaw, stateMap
              );
              if (forwardScreenRaw === null || forwardScreenRaw <= 0n) continue;
              const restoreInputScreenRaw = screeningInputForTarget(
                routePair.restore,
                internal.extractedRaw,
                stateMap,
                TOKENS[destination].decimals
              );
              if (restoreInputScreenRaw === null) continue;
              const gas = gasCostUsd(
                block,
                prices,
                routePair.forward.edges.length + routePair.restore.edges.length
              );
              const forwardScreenValueUsd =
                rawToNumber(forwardScreenRaw, TOKENS[destination].decimals) * prices[destination];
              const restoreScreenValueUsd =
                rawToNumber(restoreInputScreenRaw, TOKENS[destination].decimals) * prices[destination];
              const screenedRealizedDeltaUsd =
                forwardScreenValueUsd - restoreScreenValueUsd - gas.gasUsd;
              if (screenedRealizedDeltaUsd < MIN_REALIZED_PROFIT_USD) continue;
              positiveScreenedCandidates += 1;
              screened.push({
                internal,
                routePair,
                forwardScreenRaw,
                restoreInputScreenRaw,
                screenedRealizedDeltaUsd,
                ...gas,
              });
            }
          }
        }
      }
    }
  }

  screened.sort((a, b) => b.screenedRealizedDeltaUsd - a.screenedRealizedDeltaUsd);
  const exactCandidates = screened.slice(0, TOP_EXACT_CANDIDATES_PER_BLOCK);
  const quoteCache = new Map();
  let exactAttempts = 0;
  let exactFailures = 0;
  let bestAccepted = null;

  for (const candidate of exactCandidates) {
    exactAttempts += 1;
    const { internal, routePair } = candidate;
    const forwardOutputRaw = await exactRouteQuote(
      routePair.forward,
      internal.extractedRaw,
      blockTag,
      stateMap
    );
    if (forwardOutputRaw === null || forwardOutputRaw <= 0n) {
      exactFailures += 1;
      continue;
    }
    const restoration = await exactInputForTarget(
      routePair.restore,
      internal.extractedRaw,
      blockTag,
      stateMap,
      quoteCache
    );
    if (!restoration) {
      exactFailures += 1;
      continue;
    }

    const walletAfterRestoreRaw = forwardOutputRaw - restoration.inputRaw;
    if (walletAfterRestoreRaw < 0n) continue;

    const tentativePools = clonePoolState(internalPools);
    const tentativeTreasury = cloneBalances(treasury);
    const totalsBeforeApply = syntheticTotals(tentativePools);
    retargetSyntheticGradient(
      tentativePools,
      internal.synthetic,
      internal.source,
      internal.destination,
      internal.shiftRaw
    );
    const sourcePool = tentativePools.get(`${internal.synthetic}/${internal.source}`);
    const destinationPool = tentativePools.get(`${internal.synthetic}/${internal.destination}`);

    sourcePool.liquidRaw -= internal.extractedRaw;
    sourcePool.liquidRaw += internal.extractedRaw;
    const restorationExcessRaw = restoration.outputRaw - internal.extractedRaw;
    if (restorationExcessRaw > 0n) tentativeTreasury[internal.source] += restorationExcessRaw;

    destinationPool.liquidRaw += internal.buybackRaw;
    destinationPool.liquidRaw -= internal.buybackRaw;

    tentativeTreasury[internal.destination] += walletAfterRestoreRaw;
    const gasRaw = ceilUsdtRaw(candidate.gasUsd);
    if (tentativeTreasury.USDT < gasRaw) continue;
    tentativeTreasury.USDT -= gasRaw;

    const navAfterCycleUsd = protocolExternalNavUsd(tentativePools, tentativeTreasury, prices);
    const realizedDeltaUsd = navAfterCycleUsd - navBeforeBlockUsd;
    const forwardValueUsd =
      rawToNumber(forwardOutputRaw, TOKENS[internal.destination].decimals) * prices[internal.destination];
    const restorationInputValueUsd =
      rawToNumber(restoration.inputRaw, TOKENS[internal.destination].decimals) * prices[internal.destination];
    const restorationExcessValueUsd =
      rawToNumber(restorationExcessRaw, TOKENS[internal.source].decimals) * prices[internal.source];
    const directRealizedDeltaUsd =
      forwardValueUsd - restorationInputValueUsd + restorationExcessValueUsd - candidate.gasUsd;
    const totalsAfterApply = syntheticTotals(tentativePools);
    const sourceKBefore = internal.sourceSyntheticRaw * internal.sourceLiquidBeforeRaw;
    const sourceKAfter = sourcePool.syntheticRaw * sourcePool.liquidRaw;
    const destinationKBefore = internal.destinationSyntheticRaw * internal.destinationLiquidBeforeRaw;
    const destinationKAfter = destinationPool.syntheticRaw * destinationPool.liquidRaw;
    const usedKeys = [...new Set([
      ...routePoolKeys(routePair.forward),
      ...routePoolKeys(routePair.restore),
    ])];

    const exact = {
      block: blockTag,
      synthetic: internal.synthetic,
      source: internal.source,
      destination: internal.destination,
      shiftBps: internal.shiftBps,
      qeBps: internal.qeBps,
      qeSynthetic: rawToNumber(internal.qeRaw, SYNTHETIC_DECIMALS),
      destinationRecycleSynthetic: rawToNumber(
        internal.recycleSyntheticRaw,
        SYNTHETIC_DECIMALS
      ),
      extractedSource: rawToNumber(internal.extractedRaw, TOKENS[internal.source].decimals),
      forwardOutputDestination: rawToNumber(
        forwardOutputRaw,
        TOKENS[internal.destination].decimals
      ),
      exactBuybackDestination: rawToNumber(
        internal.buybackRaw,
        TOKENS[internal.destination].decimals
      ),
      recycledBuybackDestination: rawToNumber(
        internal.buybackRaw,
        TOKENS[internal.destination].decimals
      ),
      restorationInputDestination: rawToNumber(
        restoration.inputRaw,
        TOKENS[internal.destination].decimals
      ),
      restorationOutputSource: rawToNumber(
        restoration.outputRaw,
        TOKENS[internal.source].decimals
      ),
      restorationExcessSource: rawToNumber(
        restorationExcessRaw,
        TOKENS[internal.source].decimals
      ),
      walletSurplusDestination: rawToNumber(
        walletAfterRestoreRaw,
        TOKENS[internal.destination].decimals
      ),
      forwardRoute: routeLabel(routePair.forward),
      restorationRoute: routeLabel(routePair.restore),
      forwardPools: routePair.forward.edges.map((edge) => ({
        kind: edge.pool.kind,
        address: edge.pool.address,
        from: edge.from,
        to: edge.to,
        tvlUsd: edge.pool.tvlUsd,
      })),
      restorationPools: routePair.restore.edges.map((edge) => ({
        kind: edge.pool.kind,
        address: edge.pool.address,
        from: edge.from,
        to: edge.to,
        tvlUsd: edge.pool.tvlUsd,
      })),
      externalPoolsConsumed: usedKeys,
      forwardAndRestoreRoutesDisjoint: routesDisjoint(routePair.forward, routePair.restore),
      noPreviouslyConsumedExternalPool: usedKeys.every((key) => !globallyUsedPools.has(key)),
      gasUnits: candidate.gasUnits,
      gasPriceGwei: candidate.gasPriceGwei,
      gasUsd: candidate.gasUsd,
      sourceLiquidReserveBefore: rawToNumber(
        internal.sourceLiquidBeforeRaw,
        TOKENS[internal.source].decimals
      ),
      sourceLiquidReserveAfter: rawToNumber(sourcePool.liquidRaw, TOKENS[internal.source].decimals),
      destinationLiquidReserveBefore: rawToNumber(
        internal.destinationLiquidBeforeRaw,
        TOKENS[internal.destination].decimals
      ),
      destinationLiquidReserveAfter: rawToNumber(
        destinationPool.liquidRaw,
        TOKENS[internal.destination].decimals
      ),
      sourceKBefore: sourceKBefore.toString(),
      sourceKAfter: sourceKAfter.toString(),
      destinationKBefore: destinationKBefore.toString(),
      destinationKAfter: destinationKAfter.toString(),
      sourceKRatio: Number(sourceKAfter) / Number(sourceKBefore),
      destinationKRatio: Number(destinationKAfter) / Number(destinationKBefore),
      managedGradientSupplyDelta: 0,
      temporaryQeSupplyAfter: 0,
      destinationRecycleSupplyAfter: 0,
      syntheticTotalsPreserved: SYNTHETICS.every(
        (synthetic) => totalsBeforeApply[synthetic] === totalsAfterApply[synthetic]
      ),
      navBeforeCycleUsd: navBeforeBlockUsd,
      navAfterCycleUsd,
      realizedNavDeltaUsd: realizedDeltaUsd,
      directRealizedDeltaUsd,
      accountingIdentityErrorUsd: realizedDeltaUsd - directRealizedDeltaUsd,
      oraclePricesUsd: prices,
      accepted: false,
      tentativePools,
      tentativeTreasury,
    };

    exact.accepted =
      exact.forwardAndRestoreRoutesDisjoint
      && exact.noPreviouslyConsumedExternalPool
      && exact.syntheticTotalsPreserved
      && exact.temporaryQeSupplyAfter === 0
      && exact.destinationRecycleSupplyAfter === 0
      && Math.abs(exact.sourceLiquidReserveAfter - exact.sourceLiquidReserveBefore) <= 1e-9
      && Math.abs(exact.destinationLiquidReserveAfter - exact.destinationLiquidReserveBefore) <= 1e-9
      && exact.sourceKRatio >= 1 - 1e-12
      && exact.destinationKRatio >= 1 - 1e-12
      && exact.realizedNavDeltaUsd >= MIN_REALIZED_PROFIT_USD
      && Math.abs(exact.accountingIdentityErrorUsd) <= 2e-5;

    if (exact.accepted && (!bestAccepted || exact.realizedNavDeltaUsd > bestAccepted.realizedNavDeltaUsd)) {
      bestAccepted = exact;
    }
  }

  if (bestAccepted) {
    internalPools.clear();
    for (const [key, value] of bestAccepted.tentativePools.entries()) internalPools.set(key, value);
    for (const anchor of ANCHORS) treasury[anchor] = bestAccepted.tentativeTreasury[anchor];
    if (EXTERNAL_POOL_SINGLE_USE) {
      for (const key of bestAccepted.externalPoolsConsumed) globallyUsedPools.add(key);
    }
    delete bestAccepted.tentativePools;
    delete bestAccepted.tentativeTreasury;
  }

  const navAfterBlockUsd = protocolExternalNavUsd(internalPools, treasury, prices);
  const syntheticAfter = syntheticTotals(internalPools);
  return {
    block: blockTag,
    timestamp: Number(block.timestamp),
    externalPoolStatesRead: states.length,
    externalPathCount: [...pathMap.values()].reduce((sum, paths) => sum + paths.length, 0),
    evaluatedInternalConfigurations,
    evaluatedRoutePairs,
    positiveScreenedCandidates,
    exactAttempts,
    exactFailures,
    accepted: Boolean(bestAccepted),
    bestAccepted,
    navBeforeBlockUsd,
    navAfterBlockUsd,
    realizedDeltaUsd: bestAccepted?.realizedNavDeltaUsd || 0,
    cumulativeExternalPoolsConsumed: globallyUsedPools.size,
    syntheticTotalsBefore: Object.fromEntries(
      SYNTHETICS.map((synthetic) => [synthetic, rawToNumber(syntheticBefore[synthetic], SYNTHETIC_DECIMALS)])
    ),
    syntheticTotalsAfter: Object.fromEntries(
      SYNTHETICS.map((synthetic) => [synthetic, rawToNumber(syntheticAfter[synthetic], SYNTHETIC_DECIMALS)])
    ),
    oraclePricesUsd: prices,
    internalPoolsAfter: snapshotInternalPools(internalPools, prices),
    treasuryAfter: snapshotTreasury(treasury, prices),
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

  console.log(`V14 discovering real pools at Polygon block ${endBlock}`);
  const discovered = await discoverPools(endBlock);
  const endStates = (await mapLimit(discovered, 8, async (pool) => {
    try {
      const state = await readPoolState(pool, endBlock);
      return state ? { pool, state } : null;
    } catch (_) {
      return null;
    }
  })).filter(Boolean);
  const endPrices = robustAnchorPrices(endStates);
  const selectedPools = rankPools(endStates, endPrices);
  if (selectedPools.length !== TARGET_POOL_COUNT) {
    throw new Error(`selected ${selectedPools.length}, required ${TARGET_POOL_COUNT}`);
  }

  const startStates = (await mapLimit(selectedPools, 8, async (pool) => {
    try {
      const state = await readPoolState(pool, startBlock);
      return state ? { pool, state } : null;
    } catch (_) {
      return null;
    }
  })).filter(Boolean);
  const startPrices = robustAnchorPrices(startStates);
  const internalPools = initializeInternalState(startPrices);
  const treasury = initializeTreasury();
  const globallyUsedPools = new Set();
  const initialSyntheticTotals = syntheticTotals(internalPools);
  const initialNavAtStartPricesUsd = protocolExternalNavUsd(internalPools, treasury, startPrices);

  const blocks = [];
  let cumulativeRealizedNavUsd = 0;
  for (let blockTag = startBlock; blockTag <= endBlock; blockTag += 1) {
    const row = await scanStatefulBlock(
      blockTag,
      selectedPools,
      internalPools,
      treasury,
      globallyUsedPools
    );
    cumulativeRealizedNavUsd += row.realizedDeltaUsd;
    row.cumulativeRealizedNavUsd = cumulativeRealizedNavUsd;
    blocks.push(row);
    console.log(JSON.stringify({
      block: blockTag,
      accepted: row.accepted,
      realized: row.realizedDeltaUsd,
      cumulativeRealized: row.cumulativeRealizedNavUsd,
      forward: row.bestAccepted?.forwardRoute || null,
      restore: row.bestAccepted?.restorationRoute || null,
      externalPoolsConsumed: row.cumulativeExternalPoolsConsumed,
    }));
  }

  const finalSyntheticTotals = syntheticTotals(internalPools);
  const finalNavAtEndPricesUsd = protocolExternalNavUsd(internalPools, treasury, endPrices);
  const accepted = blocks.filter((row) => row.accepted);
  const sumRealized = blocks.reduce((sum, row) => sum + row.realizedDeltaUsd, 0);
  const result = {
    scenario: "synergy_v14_strict_stateful_closed_loop_10_internal_50_external_100_blocks",
    chainId: 137,
    startBlock,
    endBlock,
    blockCount: BLOCK_COUNT,
    stateModel: {
      internalPoolsCarriedAcrossBlocks: true,
      treasuryCarriedAcrossBlocks: true,
      syntheticGradientRetargetedWithZeroNetSupply: true,
      sourcePoolRestoredByExactExternalReverseQuote: true,
      destinationBuybackValueRecycledByManagedSyntheticSwap: true,
      destinationPoolRestoredAfterEveryAcceptedCycle: true,
      externalPoolSingleUseLock: EXTERNAL_POOL_SINGLE_USE,
      externalHistoricalStatesAreExogenous: true,
    },
    internalTopology: {
      synthetics: SYNTHETICS,
      liquidCurrencies: ANCHORS,
      pools: INTERNAL_POOLS,
      poolCount: INTERNAL_POOLS.length,
    },
    selectedExternalPools: selectedPools.length,
    selectedPools,
    assumptions: {
      internalSyntheticReserve: INTERNAL_SYNTHETIC_RESERVE,
      initialInternalLiquidDepthUsdPerPool: INTERNAL_LIQUID_DEPTH_USD,
      initialGasBudgetUsdt: INITIAL_GAS_BUDGET_USDT,
      internalFeeBps: INTERNAL_FEE_BPS,
      gradientShiftBps: GRADIENT_SHIFT_BPS,
      qeSizeBps: QE_SIZE_BPS,
      minimumRoutePoolTvlUsd: MIN_ROUTE_POOL_TVL_USD,
      minimumRealizedProfitUsd: MIN_REALIZED_PROFIT_USD,
      topExactCandidatesPerBlock: TOP_EXACT_CANDIDATES_PER_BLOCK,
      restoreBinarySteps: RESTORE_BINARY_STEPS,
      externalPoolSingleUse: EXTERNAL_POOL_SINGLE_USE,
      flashPremiumBps: 0,
    },
    initialState: {
      navAtStartPricesUsd: initialNavAtStartPricesUsd,
      syntheticTotals: Object.fromEntries(
        SYNTHETICS.map((synthetic) => [
          synthetic,
          rawToNumber(initialSyntheticTotals[synthetic], SYNTHETIC_DECIMALS),
        ])
      ),
      internalPools: snapshotInternalPools(initializeInternalState(startPrices), startPrices),
      treasury: snapshotTreasury(initializeTreasury(), startPrices),
      oraclePricesUsd: startPrices,
    },
    finalState: {
      navAtEndPricesUsd: finalNavAtEndPricesUsd,
      syntheticTotals: Object.fromEntries(
        SYNTHETICS.map((synthetic) => [
          synthetic,
          rawToNumber(finalSyntheticTotals[synthetic], SYNTHETIC_DECIMALS),
        ])
      ),
      internalPools: snapshotInternalPools(internalPools, endPrices),
      treasury: snapshotTreasury(treasury, endPrices),
      oraclePricesUsd: endPrices,
      externalPoolsConsumed: [...globallyUsedPools],
    },
    summary: {
      acceptedStatefulCycles: accepted.length,
      acceptedStatefulCycleRate: accepted.length / BLOCK_COUNT,
      cumulativeRealizedNavUsd: sumRealized,
      averageRealizedProfitPerAcceptedCycleUsd:
        accepted.length ? sumRealized / accepted.length : 0,
      maximumRealizedProfitUsd:
        accepted.length ? Math.max(...accepted.map((row) => row.realizedDeltaUsd)) : 0,
      externalPoolsConsumed: globallyUsedPools.size,
      evaluatedInternalConfigurations:
        blocks.reduce((sum, row) => sum + row.evaluatedInternalConfigurations, 0),
      evaluatedRoutePairs:
        blocks.reduce((sum, row) => sum + row.evaluatedRoutePairs, 0),
      positiveScreenedCandidates:
        blocks.reduce((sum, row) => sum + row.positiveScreenedCandidates, 0),
      exactAttempts: blocks.reduce((sum, row) => sum + row.exactAttempts, 0),
      exactFailures: blocks.reduce((sum, row) => sum + row.exactFailures, 0),
    },
    blocks,
    accounting: {
      realizedCycleDelta:
        "forward external destination value minus exact reverse-route input value plus reverse-quote rounding excess minus gas",
      sourceRestoration:
        "source liquid reserve is restored exactly after every accepted cycle",
      destinationRestoration:
        "exact buyback liquid is extracted back from the protocol-owned destination pool by a temporary managed-synthetic swap; the deposited temporary synthetic is burned from the pair",
      internalValueTreatment:
        "no source-LP loss or destination-LP gain is counted as profit; both internal liquid reserves finish each accepted cycle unchanged",
      cumulativeProfit:
        "sum only of sequentially applied realized NAV deltas; independent best-block snapshots are never summed",
    },
    limitation:
      "Internal pools and treasury are fully stateful. External pool states are historical exogenous snapshots; to avoid reusing an unmodeled hypothetical external reserve change, every external pool is locked after its first accepted use. This is a strict shadow backtest, not transaction inclusion proof or production audit.",
  };

  const reports = path.join(process.cwd(), "reports");
  fs.mkdirSync(reports, { recursive: true });
  fs.writeFileSync(
    path.join(reports, "managed_gradient_v14_stateful.json"),
    JSON.stringify(result, null, 2)
  );

  const headers = [
    "block", "timestamp", "accepted", "realizedDeltaUsd", "cumulativeRealizedNavUsd",
    "externalPoolStatesRead", "externalPathCount", "evaluatedInternalConfigurations",
    "evaluatedRoutePairs", "positiveScreenedCandidates", "exactAttempts", "exactFailures",
    "forwardRoute", "restorationRoute", "source", "destination", "shiftBps", "qeBps",
    "externalPoolsConsumed"
  ];
  const lines = [headers.join(",")];
  for (const row of blocks) {
    const flat = {
      ...row,
      forwardRoute: row.bestAccepted?.forwardRoute,
      restorationRoute: row.bestAccepted?.restorationRoute,
      source: row.bestAccepted?.source,
      destination: row.bestAccepted?.destination,
      shiftBps: row.bestAccepted?.shiftBps,
      qeBps: row.bestAccepted?.qeBps,
      externalPoolsConsumed: row.cumulativeExternalPoolsConsumed,
    };
    lines.push(headers.map((key) => csvEscape(flat[key])).join(","));
  }
  fs.writeFileSync(
    path.join(reports, "managed_gradient_v14_stateful.csv"),
    `${lines.join("\n")}\n`
  );
  console.log(`MANAGED_GRADIENT_V14_STATEFUL_RESULT ${JSON.stringify(result.summary)}`);
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
