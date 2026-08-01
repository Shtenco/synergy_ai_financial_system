"use strict";

const fs = require("node:fs");
const path = require("node:path");
const { ethers } = require("ethers");

const RPC_URL = process.env.POLYGON_RPC_URL || "https://polygon.drpc.org";
const BLOCK_COUNT = Number(process.env.BLOCK_COUNT || 100);
const CONFIRMATIONS = Number(process.env.CONFIRMATIONS || 12);
const TARGET_POOL_COUNT = Number(process.env.EXTERNAL_POOL_TARGET || 50);
const MAX_HOPS = Number(process.env.MAX_HOPS || 4);
const TOP_APPROX_ROUTES = Number(process.env.TOP_APPROX_ROUTES || 12);
const INTERNAL_SYN_RESERVE = Number(process.env.INTERNAL_SYN_RESERVE || 5000);
const INTERNAL_USDT_RESERVE = Number(process.env.INTERNAL_USDT_RESERVE || 5000);
const INTERNAL_FEE_BPS = Number(process.env.INTERNAL_FEE_BPS || 30);
const FLASH_PREMIUM_BPS = Number(process.env.FLASH_PREMIUM_BPS || 5);
const MIN_NET_PROFIT_USDT = Number(process.env.MIN_NET_PROFIT_USDT || 0.25);
const PRIORITY_FEE_GWEI = Number(process.env.PRIORITY_FEE_GWEI || 30);
const QUOTE_SIZES_USDT = (process.env.QUOTE_SIZES_USDT || "25,50,100,250,500,750,1000")
  .split(",")
  .map(Number)
  .filter((v) => Number.isFinite(v) && v > 0 && v < INTERNAL_USDT_RESERVE * 0.5);

const QUICKSWAP_V2_FACTORY = "0x5757371414417b8C6CAad45bAeF941aBc7d3Ab32";
const QUICKSWAP_V3_FACTORY = "0x411b0fAcC3489691f28ad58c47006AF5E3Ab3A28";
const QUICKSWAP_V3_QUOTER = "0xa15F0D7377B2A0C0c10db057f641beD21028FC89";

const TOKENS = {
  WPOL: { address: "0x0d500B1d8E8eF31E21C99d1Db9A6444d3ADf1270", decimals: 18 },
  USDT: { address: "0xc2132D05D31c914a87C6611C10748AEb04B58e8F", decimals: 6 },
  USDC: { address: "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174", decimals: 6 },
  DAI: { address: "0x8f3Cf7ad23Cd3CaDbD9735AFf958023239c6A063", decimals: 18 },
  WETH: { address: "0x7ceB23fD6bC0adD59E62ac25578270cFf1b9f619", decimals: 18 },
  WBTC: { address: "0x1BFD67037B42Cf73acF2047067bd4F2C47D9BfD6", decimals: 8 },
  LINK: { address: "0x53E0bca35eC356BD5ddDFebBD1Fc0fD03FaBad39", decimals: 18 },
  AAVE: { address: "0xD6DF932A45C0f255f85145f286eA0B292B21C90B", decimals: 18 },
  CRV: { address: "0x172370d5Cd63279eFa6d502DAB29171933a610AF", decimals: 18 },
  GHST: { address: "0x385Eeac5cB85A38A9a07A70c73e0A3271CfB54A7", decimals: 18 },
  SUSHI: { address: "0x0b3F868E0BE5597D5DB7fEB59E1CADBb0fdDa50a", decimals: 18 },
  UNI: { address: "0xb33EaAd8d922B1083446DC23f610c2567fB5180f", decimals: 18 },
  BAL: { address: "0x9a71012B13CA4d3D0Cdc72A177DF3ef03b0E76A3", decimals: 18 },
  GRT: { address: "0x5fe2B58c013d7601147DcdD68C143A77499f5531", decimals: 18 },
};

for (const token of Object.values(TOKENS)) token.address = ethers.getAddress(token.address);
const SYMBOL_BY_ADDRESS = Object.fromEntries(
  Object.entries(TOKENS).map(([symbol, data]) => [data.address.toLowerCase(), symbol])
);

const FACTORY_V2_ABI = ["function getPair(address,address) view returns(address)"];
const FACTORY_V3_ABI = ["function poolByPair(address,address) view returns(address)"];
const V2_PAIR_ABI = [
  "function token0() view returns(address)",
  "function token1() view returns(address)",
  "function getReserves() view returns(uint112 reserve0,uint112 reserve1,uint32 blockTimestampLast)",
];
const V3_POOL_ABI = [
  "function token0() view returns(address)",
  "function token1() view returns(address)",
  "function globalState() view returns(uint160 price,int24 tick,uint16 fee,uint16 timepointIndex,uint8 communityFeeToken0,uint8 communityFeeToken1,bool unlocked)",
  "function liquidity() view returns(uint128)",
];
const ERC20_ABI = ["function balanceOf(address) view returns(uint256)"];
const V3_QUOTER_ABI = [
  "function quoteExactInputSingle(address tokenIn,address tokenOut,uint256 amountIn,uint160 limitSqrtPrice) returns(uint256 amountOut,uint16 fee)",
];

const provider = new ethers.JsonRpcProvider(RPC_URL, 137, { staticNetwork: true });
const v2Factory = new ethers.Contract(QUICKSWAP_V2_FACTORY, FACTORY_V2_ABI, provider);
const v3Factory = new ethers.Contract(QUICKSWAP_V3_FACTORY, FACTORY_V3_ABI, provider);
const v3Quoter = new ethers.Contract(QUICKSWAP_V3_QUOTER, V3_QUOTER_ABI, provider);

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function retry(label, fn, attempts = 5) {
  let last;
  for (let i = 0; i < attempts; i += 1) {
    try {
      return await fn();
    } catch (error) {
      last = error;
      if (i + 1 < attempts) await sleep(250 * 2 ** i);
    }
  }
  throw new Error(`${label}: ${last?.message || last}`);
}

async function mapLimit(items, limit, fn) {
  const output = new Array(items.length);
  let cursor = 0;
  async function worker() {
    while (true) {
      const index = cursor;
      cursor += 1;
      if (index >= items.length) return;
      output[index] = await fn(items[index], index);
    }
  }
  await Promise.all(Array.from({ length: Math.min(limit, items.length) }, worker));
  return output;
}

function rawToNumber(raw, decimals) {
  return Number(ethers.formatUnits(raw, decimals));
}

function numberToRaw(value, decimals) {
  return ethers.parseUnits(value.toFixed(Math.min(decimals, 12)), decimals);
}

function cpAmountOut(amountIn, reserveIn, reserveOut, feeBps = 30) {
  const effective = amountIn * BigInt(10_000 - feeBps);
  return (effective * reserveOut) / (reserveIn * 10_000n + effective);
}

function cpAmountIn(amountOut, reserveIn, reserveOut, feeBps = 30) {
  if (amountOut <= 0n || amountOut >= reserveOut) return null;
  return (reserveIn * amountOut * 10_000n) / ((reserveOut - amountOut) * BigInt(10_000 - feeBps)) + 1n;
}

function internalRoundTrip(extractedUsdt) {
  const syn0 = numberToRaw(INTERNAL_SYN_RESERVE, 6);
  const usdt0 = numberToRaw(INTERNAL_USDT_RESERVE, 6);
  const extracted = numberToRaw(extractedUsdt, 6);
  const qeMint = cpAmountIn(extracted, syn0, usdt0, INTERNAL_FEE_BPS);
  if (qeMint === null) return null;
  const synAfter = syn0 + qeMint;
  const usdtAfter = usdt0 - extracted;
  const buybackUsdt = cpAmountIn(qeMint, usdtAfter, synAfter, INTERNAL_FEE_BPS);
  if (buybackUsdt === null) return null;
  return {
    qeMintRaw: qeMint,
    qeMint: rawToNumber(qeMint, 6),
    extractedRaw: extracted,
    buybackRaw: buybackUsdt,
    buybackUsdt: rawToNumber(buybackUsdt, 6),
  };
}

function v3SpotPriceToken1PerToken0(sqrtPriceX96, decimals0, decimals1) {
  const sqrt = Number(sqrtPriceX96) / 2 ** 96;
  return sqrt * sqrt * 10 ** (decimals0 - decimals1);
}

function poolKey(kind, address) {
  return `${kind}:${address.toLowerCase()}`;
}

async function discoverPools(blockTag) {
  const symbols = Object.keys(TOKENS);
  const pairSpecs = [];
  for (let i = 0; i < symbols.length; i += 1) {
    for (let j = i + 1; j < symbols.length; j += 1) pairSpecs.push([symbols[i], symbols[j]]);
  }

  const discovered = [];
  await mapLimit(pairSpecs, 8, async ([symbolA, symbolB]) => {
    const tokenA = TOKENS[symbolA].address;
    const tokenB = TOKENS[symbolB].address;
    const [v2, v3] = await Promise.all([
      retry(`getPair ${symbolA}/${symbolB}`, () => v2Factory.getPair(tokenA, tokenB, { blockTag })),
      retry(`poolByPair ${symbolA}/${symbolB}`, () => v3Factory.poolByPair(tokenA, tokenB, { blockTag })),
    ]);
    for (const [kind, address] of [["v2", v2], ["v3", v3]]) {
      if (address === ethers.ZeroAddress) continue;
      const code = await retry(`getCode ${address}`, () => provider.getCode(address, blockTag));
      if (code === "0x") continue;
      discovered.push({ kind, address: ethers.getAddress(address), symbolA, symbolB });
    }
  });

  const unique = [...new Map(discovered.map((pool) => [poolKey(pool.kind, pool.address), pool])).values()];
  const hydrated = (await mapLimit(unique, 8, async (pool) => {
    try {
      const abi = pool.kind === "v2" ? V2_PAIR_ABI : V3_POOL_ABI;
      const contract = new ethers.Contract(pool.address, abi, provider);
      const [token0, token1] = await Promise.all([
        retry(`token0 ${pool.address}`, () => contract.token0({ blockTag })),
        retry(`token1 ${pool.address}`, () => contract.token1({ blockTag })),
      ]);
      const symbol0 = SYMBOL_BY_ADDRESS[token0.toLowerCase()];
      const symbol1 = SYMBOL_BY_ADDRESS[token1.toLowerCase()];
      if (!symbol0 || !symbol1) return null;
      const [balance0, balance1] = await Promise.all([
        retry(`balance0 ${pool.address}`, () => new ethers.Contract(token0, ERC20_ABI, provider).balanceOf(pool.address, { blockTag })),
        retry(`balance1 ${pool.address}`, () => new ethers.Contract(token1, ERC20_ABI, provider).balanceOf(pool.address, { blockTag })),
      ]);
      if (balance0 === 0n || balance1 === 0n) return null;
      return {
        ...pool,
        token0: ethers.getAddress(token0),
        token1: ethers.getAddress(token1),
        symbol0,
        symbol1,
        decimals0: TOKENS[symbol0].decimals,
        decimals1: TOKENS[symbol1].decimals,
        endBalance0: rawToNumber(balance0, TOKENS[symbol0].decimals),
        endBalance1: rawToNumber(balance1, TOKENS[symbol1].decimals),
      };
    } catch (_) {
      return null;
    }
  })).filter(Boolean);

  if (hydrated.length < TARGET_POOL_COUNT) {
    throw new Error(`Only ${hydrated.length} live pools discovered; target=${TARGET_POOL_COUNT}`);
  }
  return hydrated;
}

async function readPoolState(pool, blockTag) {
  if (pool.kind === "v2") {
    const contract = new ethers.Contract(pool.address, V2_PAIR_ABI, provider);
    const reserves = await retry(`reserves ${pool.address}@${blockTag}`, () => contract.getReserves({ blockTag }));
    const reserve0 = reserves[0];
    const reserve1 = reserves[1];
    if (reserve0 === 0n || reserve1 === 0n) return null;
    const spot10 = rawToNumber(reserve1, pool.decimals1) / rawToNumber(reserve0, pool.decimals0);
    return { reserve0, reserve1, spot10, feePpm: 3000 };
  }
  const contract = new ethers.Contract(pool.address, V3_POOL_ABI, provider);
  const [globalState, liquidity] = await Promise.all([
    retry(`globalState ${pool.address}@${blockTag}`, () => contract.globalState({ blockTag })),
    retry(`liquidity ${pool.address}@${blockTag}`, () => contract.liquidity({ blockTag })),
  ]);
  if (globalState[0] === 0n || liquidity === 0n) return null;
  return {
    sqrtPriceX96: globalState[0],
    tick: Number(globalState[1]),
    feePpm: Number(globalState[2]),
    liquidity,
    spot10: v3SpotPriceToken1PerToken0(globalState[0], pool.decimals0, pool.decimals1),
  };
}

function deriveTokenPrices(poolsWithState) {
  const prices = { USDT: 1, USDC: 1, DAI: 1 };
  for (let pass = 0; pass < 5; pass += 1) {
    let changed = false;
    for (const { pool, state } of poolsWithState) {
      const { symbol0, symbol1 } = pool;
      const p10 = state.spot10;
      if (!(p10 > 0 && Number.isFinite(p10))) continue;
      if (prices[symbol0] && !prices[symbol1]) {
        prices[symbol1] = prices[symbol0] / p10;
        changed = true;
      }
      if (prices[symbol1] && !prices[symbol0]) {
        prices[symbol0] = prices[symbol1] * p10;
        changed = true;
      }
    }
    if (!changed) break;
  }
  return prices;
}

function rankPools(poolsWithState, prices) {
  return poolsWithState
    .map(({ pool, state }) => {
      let balance0;
      let balance1;
      if (pool.kind === "v2") {
        balance0 = rawToNumber(state.reserve0, pool.decimals0);
        balance1 = rawToNumber(state.reserve1, pool.decimals1);
      } else {
        balance0 = pool.endBalance0;
        balance1 = pool.endBalance1;
      }
      const price0 = prices[pool.symbol0] || 0;
      const price1 = prices[pool.symbol1] || 0;
      const tvlUsd = balance0 * price0 + balance1 * price1;
      return { ...pool, tvlUsd, endSpot10: state.spot10, feePpm: state.feePpm };
    })
    .filter((pool) => pool.tvlUsd > 100)
    .sort((a, b) => b.tvlUsd - a.tvlUsd)
    .slice(0, TARGET_POOL_COUNT);
}

function buildEdges(selectedPools, stateMap) {
  const edges = [];
  for (const pool of selectedPools) {
    const state = stateMap.get(poolKey(pool.kind, pool.address));
    if (!state || !(state.spot10 > 0)) continue;
    const feeFactor = 1 - Math.min(Math.max(state.feePpm, 0), 100_000) / 1_000_000;
    edges.push({ pool, from: pool.symbol0, to: pool.symbol1, approxRate: state.spot10 * feeFactor });
    edges.push({ pool, from: pool.symbol1, to: pool.symbol0, approxRate: (1 / state.spot10) * feeFactor });
  }
  return edges;
}

function enumerateCycles(edges, start = "USDT", maxHops = 4) {
  const adjacency = new Map();
  for (const edge of edges) {
    if (!adjacency.has(edge.from)) adjacency.set(edge.from, []);
    adjacency.get(edge.from).push(edge);
  }
  const cycles = [];
  function dfs(current, route, visited, rate) {
    if (route.length >= 2 && current === start) {
      cycles.push({ edges: [...route], approxMultiplier: rate });
      return;
    }
    if (route.length >= maxHops) return;
    for (const edge of adjacency.get(current) || []) {
      if (edge.to === start && route.length >= 1) {
        dfs(start, [...route, edge], visited, rate * edge.approxRate);
      } else if (!visited.has(edge.to)) {
        const nextVisited = new Set(visited);
        nextVisited.add(edge.to);
        dfs(edge.to, [...route, edge], nextVisited, rate * edge.approxRate);
      }
    }
  }
  dfs(start, [], new Set([start]), 1);
  const unique = new Map();
  for (const cycle of cycles) {
    const key = cycle.edges.map((e) => `${e.pool.kind}:${e.pool.address}:${e.from}>${e.to}`).join("|");
    const previous = unique.get(key);
    if (!previous || cycle.approxMultiplier > previous.approxMultiplier) unique.set(key, cycle);
  }
  return [...unique.values()].sort((a, b) => b.approxMultiplier - a.approxMultiplier);
}

async function exactEdgeQuote(edge, amountInRaw, blockTag, stateMap) {
  const pool = edge.pool;
  if (pool.kind === "v2") {
    const state = stateMap.get(poolKey(pool.kind, pool.address));
    if (!state) return null;
    const zeroForOne = edge.from === pool.symbol0;
    const reserveIn = zeroForOne ? state.reserve0 : state.reserve1;
    const reserveOut = zeroForOne ? state.reserve1 : state.reserve0;
    return cpAmountOut(amountInRaw, reserveIn, reserveOut, 30);
  }
  const tokenIn = TOKENS[edge.from].address;
  const tokenOut = TOKENS[edge.to].address;
  try {
    const quote = await retry(`v3 quote ${edge.from}/${edge.to}@${blockTag}`, () =>
      v3Quoter.quoteExactInputSingle.staticCall(tokenIn, tokenOut, amountInRaw, 0, { blockTag }), 3
    );
    return quote[0];
  } catch (_) {
    return null;
  }
}

async function exactRouteQuote(route, amountInRaw, blockTag, stateMap) {
  let amount = amountInRaw;
  for (const edge of route.edges) {
    amount = await exactEdgeQuote(edge, amount, blockTag, stateMap);
    if (amount === null || amount <= 0n) return null;
  }
  return amount;
}

function routeLabel(route) {
  if (!route.edges.length) return "";
  return [route.edges[0].from, ...route.edges.map((edge) => `${edge.to}[${edge.pool.kind}]`)].join("→");
}

async function scanBlock(blockTag, selectedPools) {
  const block = await retry(`block ${blockTag}`, () => provider.getBlock(blockTag));
  const states = await mapLimit(selectedPools, 8, async (pool) => {
    try {
      const state = await readPoolState(pool, blockTag);
      return state ? { pool, state } : null;
    } catch (_) {
      return null;
    }
  });
  const valid = states.filter(Boolean);
  const stateMap = new Map(valid.map(({ pool, state }) => [poolKey(pool.kind, pool.address), state]));
  const edges = buildEdges(selectedPools, stateMap);
  const cycles = enumerateCycles(edges, "USDT", MAX_HOPS)
    .filter((cycle) => cycle.approxMultiplier > 1.00005)
    .slice(0, TOP_APPROX_ROUTES);

  const prices = deriveTokenPrices(valid);
  const polPrice = prices.WPOL || 0;
  const baseFeeWei = block.baseFeePerGas ? Number(block.baseFeePerGas) : 0;
  const gasPriceWei = Math.max(baseFeeWei * 1.2 + PRIORITY_FEE_GWEI * 1e9, PRIORITY_FEE_GWEI * 1e9);

  let best = null;
  let exactCandidates = 0;
  for (const route of cycles) {
    for (const size of QUOTE_SIZES_USDT) {
      const internal = internalRoundTrip(size);
      if (!internal) continue;
      const amountOutRaw = await exactRouteQuote(route, internal.extractedRaw, blockTag, stateMap);
      if (amountOutRaw === null) continue;
      exactCandidates += 1;
      const externalOut = rawToNumber(amountOutRaw, TOKENS.USDT.decimals);
      const flashPremium = size * FLASH_PREMIUM_BPS / 10_000;
      const gasUnits = 450_000 + route.edges.length * 220_000;
      const gasUsdt = gasUnits * gasPriceWei / 1e18 * polPrice;
      const netProfit = externalOut - internal.buybackUsdt - flashPremium - gasUsdt;
      const profitBps = netProfit / size * 10_000;
      const record = {
        route: routeLabel(route),
        hops: route.edges.length,
        pools: route.edges.map((edge) => ({ kind: edge.pool.kind, address: edge.pool.address, from: edge.from, to: edge.to })),
        sizeUsdt: size,
        qeMint: internal.qeMint,
        buybackUsdt: internal.buybackUsdt,
        externalOutUsdt: externalOut,
        flashPremiumUsdt: flashPremium,
        gasUsdt,
        netProfitUsdt: netProfit,
        profitBps,
        approximateMultiplier: route.approxMultiplier,
      };
      if (!best || record.netProfitUsdt > best.netProfitUsdt) best = record;
    }
  }

  const accepted = Boolean(best && best.netProfitUsdt >= MIN_NET_PROFIT_USDT);
  return {
    block: blockTag,
    timestamp: Number(block.timestamp),
    poolStatesRead: valid.length,
    approximateCycles: cycles.length,
    exactCandidates,
    polPriceUsdt: polPrice,
    gasPriceGwei: gasPriceWei / 1e9,
    accepted,
    best,
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
  if (endBlock < startBlock || endBlock - startBlock + 1 !== BLOCK_COUNT) {
    throw new Error(`Invalid block range ${startBlock}-${endBlock}; expected ${BLOCK_COUNT} blocks`);
  }

  console.log(`Discovering pools at Polygon block ${endBlock}...`);
  const discovered = await discoverPools(endBlock);
  const endStates = (await mapLimit(discovered, 8, async (pool) => {
    try {
      const state = await readPoolState(pool, endBlock);
      return state ? { pool, state } : null;
    } catch (_) {
      return null;
    }
  })).filter(Boolean);
  const prices = deriveTokenPrices(endStates);
  const selectedPools = rankPools(endStates, prices);
  if (selectedPools.length !== TARGET_POOL_COUNT) throw new Error(`Ranked ${selectedPools.length} pools, expected ${TARGET_POOL_COUNT}`);

  console.log(`Scanning ${BLOCK_COUNT} real blocks across ${selectedPools.length} selected pools...`);
  const blocks = [];
  for (let block = startBlock; block <= endBlock; block += 1) {
    const row = await scanBlock(block, selectedPools);
    blocks.push(row);
    console.log(JSON.stringify({ block, accepted: row.accepted, net: row.best?.netProfitUsdt ?? null, route: row.best?.route ?? null }));
  }

  const accepted = blocks.filter((row) => row.accepted);
  const profitableBlocks = accepted.length;
  const independentEpisodes = [];
  for (const row of accepted) {
    const previous = independentEpisodes.at(-1);
    if (!previous || row.block > previous.endBlock + 1) independentEpisodes.push({ startBlock: row.block, endBlock: row.block, count: 1 });
    else { previous.endBlock = row.block; previous.count += 1; }
  }
  const profits = accepted.map((row) => row.best.netProfitUsdt).sort((a, b) => a - b);
  const sum = profits.reduce((a, b) => a + b, 0);
  const median = profits.length ? profits[Math.floor(profits.length / 2)] : 0;
  const routeCounts = {};
  for (const row of accepted) routeCounts[row.best.route] = (routeCounts[row.best.route] || 0) + 1;

  const result = {
    scenario: "synergy_v9_real_polygon_50_pool_100_block_scan",
    rpc: RPC_URL.replace(/:\/\/.*@/, "://***@"),
    chainId: 137,
    startBlock,
    endBlock,
    blockCount: BLOCK_COUNT,
    tokenCount: Object.keys(TOKENS).length,
    discoveredLivePools: discovered.length,
    selectedExternalPools: selectedPools.length,
    maxHops: MAX_HOPS,
    quoteSizesUsdt: QUOTE_SIZES_USDT,
    internalModel: {
      synReserve: INTERNAL_SYN_RESERVE,
      usdtReserve: INTERNAL_USDT_RESERVE,
      internalFeeBps: INTERNAL_FEE_BPS,
      flashPremiumBps: FLASH_PREMIUM_BPS,
      minimumNetProfitUsdt: MIN_NET_PROFIT_USDT,
    },
    selectedPools,
    summary: {
      profitableBlocks,
      profitableBlockRate: profitableBlocks / BLOCK_COUNT,
      pausedBlocks: BLOCK_COUNT - profitableBlocks,
      independentEpisodes: independentEpisodes.length,
      episodes: independentEpisodes,
      totalBestNetProfitUsdt: sum,
      averageBestNetProfitUsdt: profits.length ? sum / profits.length : 0,
      medianBestNetProfitUsdt: median,
      minimumBestNetProfitUsdt: profits.length ? profits[0] : 0,
      maximumBestNetProfitUsdt: profits.length ? profits.at(-1) : 0,
      routeCounts,
    },
    blocks,
    methodology: {
      poolPrices: "Real QuickSwap V2 reserves and QuickSwap V3 Algebra globalState at each historical Polygon block",
      routeSearch: "All simple USDT cycles up to MAX_HOPS over 50 selected real pools; approximate screen followed by exact V2 math and historical V3 quoter calls",
      acceptance: "External output minus exact internal QE/QT buyback, flash premium and gas converted through real WPOL/USDT price",
      warning: "Historical quote availability and public-RPC rate limits can reduce exactCandidates; accepted opportunities are modelled executable quotes, not guaranteed private-orderflow fills",
    },
  };

  const reports = path.join(process.cwd(), "reports");
  fs.mkdirSync(reports, { recursive: true });
  fs.writeFileSync(path.join(reports, "polygon_50_pool_100_block_scan.json"), JSON.stringify(result, null, 2));
  const headers = ["block", "timestamp", "accepted", "poolStatesRead", "approximateCycles", "exactCandidates", "route", "hops", "sizeUsdt", "externalOutUsdt", "buybackUsdt", "flashPremiumUsdt", "gasUsdt", "netProfitUsdt", "profitBps", "polPriceUsdt", "gasPriceGwei"];
  const lines = [headers.join(",")];
  for (const row of blocks) {
    const best = row.best || {};
    lines.push(headers.map((header) => csvEscape({ ...row, ...best }[header])).join(","));
  }
  fs.writeFileSync(path.join(reports, "polygon_50_pool_100_block_scan.csv"), `${lines.join("\n")}\n`);
  console.log(`POLYGON_50_POOL_SCAN_RESULT ${JSON.stringify({ startBlock, endBlock, selectedExternalPools: selectedPools.length, ...result.summary })}`);
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
