"use strict";

/**
 * Collect an actual transaction-level Polygon panel for the first V15.3 market:
 * QuickSwap V2 USDC -> WPOL victim flow with a Uniswap V3 -> QuickSwap V2
 * counter-route. Exact same-block outcomes are added by the strict replay stage.
 */
const fs = require("node:fs");
const path = require("node:path");
const { ethers } = require("ethers");

const SPEC_PATH = process.env.V153_PANEL_SPEC || "economics/v15_3_transaction_panel_spec.json";
const OUTPUT_PATH = process.env.V153_RAW_PANEL || "reports/v15_3_transaction_panel_raw.jsonl";
const SUMMARY_PATH = process.env.V153_RAW_SUMMARY || "reports/v15_3_transaction_panel_raw_summary.json";
const RPC_URL = process.env.POLYGON_RPC_URL || "https://polygon.drpc.org";

const spec = JSON.parse(fs.readFileSync(SPEC_PATH, "utf8"));
const market = spec.market;
const START_BLOCK = Number(process.env.V153_START_BLOCK || market.defaultStartBlock);
const END_BLOCK = Number(process.env.V153_END_BLOCK || market.defaultEndBlock);
const MIN_AMOUNT_IN = ethers.parseUnits(
  process.env.V153_MIN_VICTIM_USDC || String(market.minimumVictimUsdc),
  market.settlementDecimals
);
const MAX_ROWS = Number(process.env.V153_MAX_RAW_ROWS || spec.estimation.maximumRawRows);
const VOLATILITY_LOOKBACK = Number(
  process.env.V153_VOLATILITY_LOOKBACK || spec.estimation.volatilityLookbackBlocks
);
const PROBE_SHARE_BPS = BigInt(
  process.env.V153_PROBE_SHARE_BPS || spec.estimation.probeReserveShareBps
);
const ESTIMATED_ROUTE_GAS_UNITS = Number(
  process.env.V153_ESTIMATED_ROUTE_GAS_UNITS || spec.estimation.estimatedRouteGasUnits
);

const USDC = ethers.getAddress(market.settlementToken);
const WPOL = ethers.getAddress(market.intermediateToken);
const QS_V2_ROUTER = ethers.getAddress(market.targetVenue.router);
const QS_V2_FACTORY = ethers.getAddress(market.targetVenue.factory);
const UNI_V3_FACTORY = ethers.getAddress(market.sourceVenue.factory);
const UNI_V3_QUOTER = ethers.getAddress(market.sourceVenue.quoter);
const V3_FEES = market.sourceVenue.feeCandidates.map(Number);

const provider = new ethers.JsonRpcProvider(RPC_URL, spec.chainId, { staticNetwork: true });
const routerInterface = new ethers.Interface([
  "function swapExactTokensForTokens(uint256 amountIn,uint256 amountOutMin,address[] path,address to,uint256 deadline)",
  "function swapExactTokensForTokensSupportingFeeOnTransferTokens(uint256 amountIn,uint256 amountOutMin,address[] path,address to,uint256 deadline)"
]);
const V2_FACTORY_ABI = ["function getPair(address,address) view returns(address)"];
const V2_PAIR_ABI = [
  "function token0() view returns(address)",
  "function token1() view returns(address)",
  "function getReserves() view returns(uint112 reserve0,uint112 reserve1,uint32 blockTimestampLast)"
];
const V2_ROUTER_ABI = ["function getAmountsOut(uint256,address[]) view returns(uint256[])"];
const V3_FACTORY_ABI = ["function getPool(address,address,uint24) view returns(address)"];
const QUOTER_ABI = [
  "function quoteExactInputSingle(address,address,uint24,uint256,uint160) returns(uint256)"
];
const SWAP_TOPIC_V2 = ethers.id("Swap(address,uint256,uint256,uint256,uint256,address)");
const swapEvent = new ethers.Interface([
  "event Swap(address indexed sender,uint256 amount0In,uint256 amount1In,uint256 amount0Out,uint256 amount1Out,address indexed to)"
]);

function lower(value) {
  return String(value || "").toLowerCase();
}

function finite(value, fallback = 0) {
  return Number.isFinite(value) ? value : fallback;
}

function median(values) {
  const clean = values.filter(Number.isFinite).sort((a, b) => a - b);
  if (!clean.length) return 0;
  const middle = Math.floor(clean.length / 2);
  return clean.length % 2 ? clean[middle] : (clean[middle - 1] + clean[middle]) / 2;
}

function stddev(values) {
  if (values.length < 2) return 0;
  const avg = values.reduce((sum, value) => sum + value, 0) / values.length;
  return Math.sqrt(values.reduce((sum, value) => sum + (value - avg) ** 2, 0) / (values.length - 1));
}

function normalizeReserves(raw, token0) {
  const reserve0 = BigInt(raw.reserve0 ?? raw[0]);
  const reserve1 = BigInt(raw.reserve1 ?? raw[1]);
  if (lower(token0) === lower(USDC)) return { usdcRaw: reserve0, wpolRaw: reserve1 };
  return { usdcRaw: reserve1, wpolRaw: reserve0 };
}

function reserveMetrics(reserves) {
  const usdc = Number(ethers.formatUnits(reserves.usdcRaw, market.settlementDecimals));
  const wpol = Number(ethers.formatUnits(reserves.wpolRaw, market.intermediateDecimals));
  const usdcPerWpol = wpol > 0 ? usdc / wpol : 0;
  const tvlUsdc = usdcPerWpol > 0 ? usdc + wpol * usdcPerWpol : 0;
  return { usdc, wpol, usdcPerWpol, tvlUsdc };
}

function executionMetrics(amountInRaw, amountOutRaw, prePriceUsdcPerWpol) {
  const amountInUsdc = Number(ethers.formatUnits(amountInRaw, market.settlementDecimals));
  const amountOutWpol = Number(ethers.formatUnits(amountOutRaw, market.intermediateDecimals));
  const executionWpolPerUsdc = amountInUsdc > 0 ? amountOutWpol / amountInUsdc : 0;
  const referenceWpolPerUsdc = prePriceUsdcPerWpol > 0 ? 1 / prePriceUsdcPerWpol : 0;
  const priceImpactBps = referenceWpolPerUsdc > 0
    ? (referenceWpolPerUsdc - executionWpolPerUsdc) / referenceWpolPerUsdc * 10_000
    : 0;
  return { amountInUsdc, amountOutWpol, executionWpolPerUsdc, priceImpactBps };
}

async function retry(label, fn, attempts = 4) {
  let last;
  for (let attempt = 0; attempt < attempts; attempt += 1) {
    try {
      return await fn();
    } catch (error) {
      last = error;
      await new Promise((resolve) => setTimeout(resolve, 300 * (attempt + 1)));
    }
  }
  throw new Error(`${label}: ${last?.message || last}`);
}

async function discoverVenues() {
  const v2Factory = new ethers.Contract(QS_V2_FACTORY, V2_FACTORY_ABI, provider);
  const v3Factory = new ethers.Contract(UNI_V3_FACTORY, V3_FACTORY_ABI, provider);
  const pair = ethers.getAddress(await v2Factory.getPair(USDC, WPOL, { blockTag: END_BLOCK }));
  if (pair === ethers.ZeroAddress || await provider.getCode(pair, END_BLOCK) === "0x") {
    throw new Error("QuickSwap V2 USDC/WPOL pair unavailable at end block");
  }
  let sourcePool = ethers.ZeroAddress;
  let sourceFee = 0;
  for (const fee of V3_FEES) {
    const candidate = ethers.getAddress(
      await v3Factory.getPool(USDC, WPOL, fee, { blockTag: END_BLOCK })
    );
    if (candidate !== ethers.ZeroAddress && await provider.getCode(candidate, END_BLOCK) !== "0x") {
      sourcePool = candidate;
      sourceFee = fee;
      break;
    }
  }
  if (sourcePool === ethers.ZeroAddress) throw new Error("Uniswap V3 USDC/WPOL source pool unavailable");
  const pairContract = new ethers.Contract(pair, V2_PAIR_ABI, provider);
  const token0 = await pairContract.token0({ blockTag: END_BLOCK });
  const token1 = await pairContract.token1({ blockTag: END_BLOCK });
  return { pair, pairContract, token0, token1, sourcePool, sourceFee };
}

async function reservesAt(venue, blockTag, cache) {
  const key = String(blockTag);
  if (cache.has(key)) return cache.get(key);
  const raw = await retry(`getReserves@${blockTag}`, () => venue.pairContract.getReserves({ blockTag }));
  const value = normalizeReserves(raw, venue.token0);
  cache.set(key, value);
  return value;
}

async function rollingVolatilityBps(venue, blockNumber, reserveCache) {
  const prices = [];
  const first = Math.max(1, blockNumber - VOLATILITY_LOOKBACK);
  for (let blockTag = first; blockTag < blockNumber; blockTag += 1) {
    try {
      const metrics = reserveMetrics(await reservesAt(venue, blockTag, reserveCache));
      if (metrics.usdcPerWpol > 0) prices.push(metrics.usdcPerWpol);
    } catch (_) {
      // Missing archive state reduces the recorded observation count.
    }
  }
  const returns = [];
  for (let index = 1; index < prices.length; index += 1) {
    returns.push(Math.log(prices[index] / prices[index - 1]) * 10_000);
  }
  return { volatilityBps: stddev(returns), observations: returns.length };
}

async function roundtripQuote({ venue, amountInRaw, blockTag, qsRouter, quoter }) {
  if (amountInRaw <= 0n) return null;
  try {
    const mid = await quoter.quoteExactInputSingle.staticCall(
      USDC, WPOL, venue.sourceFee, amountInRaw, 0n, { blockTag }
    );
    const amounts = await qsRouter.getAmountsOut.staticCall(mid, [WPOL, USDC], { blockTag });
    const finalOut = BigInt(amounts[1]);
    const gross = finalOut - amountInRaw;
    return {
      amountInRaw: amountInRaw.toString(),
      midOutRaw: BigInt(mid).toString(),
      finalOutRaw: finalOut.toString(),
      grossProfitRaw: gross.toString(),
      grossEdgeBps: finite(Number(gross) / Number(amountInRaw) * 10_000)
    };
  } catch (_) {
    return null;
  }
}

async function victimOutputFromReceipt(receipt, venue) {
  for (const log of receipt.logs) {
    if (lower(log.address) !== lower(venue.pair) || lower(log.topics?.[0]) !== lower(SWAP_TOPIC_V2)) continue;
    try {
      const decoded = swapEvent.parseLog(log);
      const amount0Out = BigInt(decoded.args.amount0Out);
      const amount1Out = BigInt(decoded.args.amount1Out);
      return lower(venue.token0) === lower(WPOL) ? amount0Out : amount1Out;
    } catch (_) {
      return 0n;
    }
  }
  return 0n;
}

async function main() {
  if (!Number.isInteger(START_BLOCK) || !Number.isInteger(END_BLOCK) || START_BLOCK <= 0 || END_BLOCK < START_BLOCK) {
    throw new Error(`invalid block range ${START_BLOCK}-${END_BLOCK}`);
  }
  const venue = await discoverVenues();
  const qsRouter = new ethers.Contract(QS_V2_ROUTER, V2_ROUTER_ABI, provider);
  const quoter = new ethers.Contract(UNI_V3_QUOTER, QUOTER_ABI, provider);
  const reserveCache = new Map();
  const rows = [];
  const errors = [];

  for (let blockNumber = START_BLOCK; blockNumber <= END_BLOCK && rows.length < MAX_ROWS; blockNumber += 1) {
    let rawBlock;
    try {
      rawBlock = await retry(`block ${blockNumber}`, () => provider.send(
        "eth_getBlockByNumber", [ethers.toQuantity(blockNumber), true]
      ));
    } catch (error) {
      errors.push({ blockNumber, stage: "block", error: error.message });
      continue;
    }
    if (!rawBlock || !Array.isArray(rawBlock.transactions)) continue;
    const block = await provider.getBlock(blockNumber);

    for (const tx of rawBlock.transactions) {
      if (rows.length >= MAX_ROWS) break;
      if (lower(tx.to) !== lower(QS_V2_ROUTER) || !tx.input || tx.input === "0x") continue;
      let decoded;
      try {
        decoded = routerInterface.parseTransaction({ data: tx.input, value: BigInt(tx.value || "0x0") });
      } catch (_) {
        continue;
      }
      if (!decoded) continue;
      const amountInRaw = BigInt(decoded.args.amountIn);
      const swapPath = Array.from(decoded.args.path).map(ethers.getAddress);
      if (
        amountInRaw < MIN_AMOUNT_IN
        || swapPath.length !== 2
        || lower(swapPath[0]) !== lower(USDC)
        || lower(swapPath[1]) !== lower(WPOL)
      ) continue;

      try {
        const receipt = await retry(`receipt ${tx.hash}`, () => provider.getTransactionReceipt(tx.hash));
        if (!receipt || receipt.status !== 1) continue;
        const outputRaw = await victimOutputFromReceipt(receipt, venue);
        if (outputRaw <= 0n) continue;

        const preRaw = await reservesAt(venue, blockNumber - 1, reserveCache);
        const postRaw = await reservesAt(venue, blockNumber, reserveCache);
        const pre = reserveMetrics(preRaw);
        const post = reserveMetrics(postRaw);
        const execution = executionMetrics(amountInRaw, outputRaw, pre.usdcPerWpol);
        const reserveProbe = preRaw.usdcRaw * PROBE_SHARE_BPS / 10_000n;
        const probeAmountRaw = reserveProbe > 0n ? reserveProbe : MIN_AMOUNT_IN;
        const preQuote = await roundtripQuote({ venue, amountInRaw: probeAmountRaw, blockTag: blockNumber - 1, qsRouter, quoter });
        const postQuote = await roundtripQuote({ venue, amountInRaw: probeAmountRaw, blockTag: blockNumber, qsRouter, quoter });
        const volatility = await rollingVolatilityBps(venue, blockNumber, reserveCache);

        const effectiveGasPrice = BigInt(receipt.gasPrice ?? tx.gasPrice ?? "0x0");
        const gasWei = BigInt(receipt.gasUsed) * effectiveGasPrice;
        const gasWpol = Number(ethers.formatEther(gasWei));
        const gasUsdc = gasWpol * pre.usdcPerWpol;
        const baseFeeWei = BigInt(block?.baseFeePerGas || 0n);
        const priorityFeeWei = effectiveGasPrice > baseFeeWei ? effectiveGasPrice - baseFeeWei : 0n;
        const amountToTvlBps = pre.tvlUsdc > 0 ? execution.amountInUsdc / pre.tvlUsdc * 10_000 : 0;
        const estimatedRouteGasUsdc = Number(ethers.formatUnits(baseFeeWei + priorityFeeWei, "gwei"))
          * ESTIMATED_ROUTE_GAS_UNITS / 1e9 * pre.usdcPerWpol;
        const estimatedRouteGasBps = execution.amountInUsdc > 0
          ? estimatedRouteGasUsdc / execution.amountInUsdc * 10_000
          : 0;
        const postDisplacementBps = pre.usdcPerWpol > 0
          ? (post.usdcPerWpol / pre.usdcPerWpol - 1) * 10_000
          : 0;

        rows.push({
          schemaVersion: spec.schemaVersion,
          evidenceClass: "ACTUAL_POLYGON_TRANSACTION_BLOCK_BOUNDARY_FEATURES",
          chainId: spec.chainId,
          marketId: market.id,
          transactionHash: tx.hash,
          blockNumber,
          timestamp: Number.parseInt(rawBlock.timestamp, 16),
          transactionIndex: Number.parseInt(tx.transactionIndex || "0x0", 16),
          blockTransactionCount: rawBlock.transactions.length,
          sender: tx.from,
          target: tx.to,
          method: decoded.name,
          calldataHash: ethers.keccak256(tx.input),
          victim: {
            amountInUsdcRaw: amountInRaw.toString(),
            amountInUsdc: execution.amountInUsdc,
            amountOutWpolRaw: outputRaw.toString(),
            amountOutWpol: execution.amountOutWpol,
            amountToTargetTvlBps: amountToTvlBps,
            executionWpolPerUsdc: execution.executionWpolPerUsdc,
            priceImpactBps: execution.priceImpactBps
          },
          targetVenue: {
            kind: "QUICKSWAP_V2",
            pair: venue.pair,
            preUsdcReserve: pre.usdc,
            preWpolReserve: pre.wpol,
            preUsdcPerWpol: pre.usdcPerWpol,
            preTvlUsdc: pre.tvlUsdc,
            postUsdcReserve: post.usdc,
            postWpolReserve: post.wpol,
            postUsdcPerWpol: post.usdcPerWpol,
            postTvlUsdc: post.tvlUsdc,
            blockBoundaryDisplacementBps: postDisplacementBps,
            stateGranularity: "block_start_and_block_end"
          },
          sourceVenue: {
            kind: "UNISWAP_V3",
            pool: venue.sourcePool,
            feePpm: venue.sourceFee
          },
          probe: {
            amountInUsdcRaw: probeAmountRaw.toString(),
            amountInUsdc: Number(ethers.formatUnits(probeAmountRaw, market.settlementDecimals)),
            preVictimBlockRoundtrip: preQuote,
            postVictimBlockRoundtrip: postQuote,
            postMinusPreGrossEdgeBps:
              postQuote && preQuote ? postQuote.grossEdgeBps - preQuote.grossEdgeBps : null
          },
          volatility: {
            lookbackBlocks: VOLATILITY_LOOKBACK,
            realizedLogReturnVolatilityBps: volatility.volatilityBps,
            observations: volatility.observations
          },
          gas: {
            gasUsed: BigInt(receipt.gasUsed).toString(),
            effectiveGasPriceWei: effectiveGasPrice.toString(),
            effectiveGasPriceGwei: Number(ethers.formatUnits(effectiveGasPrice, "gwei")),
            baseFeeGwei: Number(ethers.formatUnits(baseFeeWei, "gwei")),
            priorityFeeGwei: Number(ethers.formatUnits(priorityFeeWei, "gwei")),
            gasWpol,
            gasUsdc,
            estimatedRouteGasUnits: ESTIMATED_ROUTE_GAS_UNITS,
            estimatedRouteGasUsdc,
            estimatedRouteGasBps
          },
          forkReplayOutcome: null,
          strictNetEdgeThresholdBps: spec.policy.strictNetEdgeBps,
          reinvestmentShare: spec.policy.reinvestmentShare,
          countedRevenueRaw: "0",
          limitations: [
            "Pool features are block-start/block-end observations, not transaction-index state.",
            "No quoted or marked edge is counted as revenue until strict fork replay executes and closes the route.",
            "Fixture principal used by replay is excluded from revenue."
          ]
        });
      } catch (error) {
        errors.push({ blockNumber, transactionHash: tx.hash, stage: "row", error: error.message });
      }
    }
    if ((blockNumber - START_BLOCK) % 100 === 0) {
      console.log(`V15_3_PANEL_PROGRESS block=${blockNumber} rows=${rows.length}`);
    }
  }

  rows.sort((a, b) => a.blockNumber - b.blockNumber || a.transactionIndex - b.transactionIndex);
  fs.mkdirSync(path.dirname(OUTPUT_PATH), { recursive: true });
  fs.writeFileSync(OUTPUT_PATH, rows.map((row) => JSON.stringify(row)).join("\n") + (rows.length ? "\n" : ""));
  const summary = {
    scenario: "synergy_v15_3_actual_polygon_transaction_panel",
    schemaVersion: spec.schemaVersion,
    chainId: spec.chainId,
    rpcHostname: new URL(RPC_URL).hostname,
    startBlock: START_BLOCK,
    endBlock: END_BLOCK,
    rows: rows.length,
    maximumRows: MAX_ROWS,
    minimumVictimUsdc: Number(ethers.formatUnits(MIN_AMOUNT_IN, market.settlementDecimals)),
    venue: {
      quickswapV2Pair: venue.pair,
      uniswapV3Pool: venue.sourcePool,
      uniswapV3FeePpm: venue.sourceFee
    },
    medianVictimUsdc: median(rows.map((row) => row.victim.amountInUsdc)),
    medianVictimImpactBps: median(rows.map((row) => row.victim.priceImpactBps)),
    medianBlockBoundaryEdgeChangeBps: median(
      rows.map((row) => row.probe.postMinusPreGrossEdgeBps).filter(Number.isFinite)
    ),
    errors: errors.slice(0, 100),
    errorCount: errors.length,
    evidenceStatus: rows.length ? "RAW_TRANSACTION_PANEL_COLLECTED" : "NO_ELIGIBLE_TRANSACTIONS_IN_RANGE",
    strictInterpretation:
      "Raw rows are historical transaction facts and block-boundary covariates. Only V15.1 fork replay may populate realized net edge and counted revenue."
  };
  fs.writeFileSync(SUMMARY_PATH, JSON.stringify(summary, null, 2));
  console.log(`V15_3_RAW_PANEL ${JSON.stringify(summary)}`);
  if (!rows.length) process.exitCode = 2;
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
