/**
 * Read-only historical-state collector for the exact SYNERGY V7 economic model.
 *
 * Run against an archive-capable Polygon fork pinned to block 90,790,000.
 * It captures the external QuickSwap V2/V3 WPOL-USDT state omitted from the
 * original V7 evidence artifact. No transaction is sent.
 */
const fs = require("node:fs");
const path = require("node:path");
const { ethers } = require("hardhat");

const FORK_BLOCK = Number(process.env.FORK_BLOCK_NUMBER || "90790000");
const WPOL = "0x0d500B1d8E8eF31E21C99d1Db9A6444d3ADf1270";
const USDT = "0xc2132D05D31c914a87C6611C10748AEb04B58e8F";
const EXTERNAL_V2 = "0x604229c960e5CACF2aaEAc8Be68Ac07BA9dF81c3";
const EXTERNAL_V3 = "0x5b41EEDCfC8e0AE47493d4945Aa1AE4fe05430ff";

const ERC20 = new ethers.Interface([
  "function balanceOf(address) view returns(uint256)",
  "function decimals() view returns(uint8)"
]);
const V2 = new ethers.Interface([
  "function token0() view returns(address)",
  "function token1() view returns(address)",
  "function getReserves() view returns(uint112 reserve0,uint112 reserve1,uint32 blockTimestampLast)"
]);
const V3 = new ethers.Interface([
  "function token0() view returns(address)",
  "function token1() view returns(address)",
  "function liquidity() view returns(uint128)",
  "function tickSpacing() view returns(int24)",
  "function ticks(int24) view returns(uint128 liquidityTotal,int128 liquidityDelta,uint256 outerFeeGrowth0Token,uint256 outerFeeGrowth1Token,int56 outerTickCumulative,uint160 outerSecondsPerLiquidity,uint32 outerSecondsSpent,bool initialized)"
]);

async function rawCall(address, iface, method, args = []) {
  const data = iface.encodeFunctionData(method, args);
  const result = await ethers.provider.call({ to: address, data }, FORK_BLOCK);
  return iface.decodeFunctionResult(method, result);
}

async function tokenMeta(address) {
  const decimals = Number((await rawCall(address, ERC20, "decimals"))[0]);
  let symbol;
  if (address.toLowerCase() === WPOL.toLowerCase()) symbol = "WPOL";
  else if (address.toLowerCase() === USDT.toLowerCase()) symbol = "USDT";
  else throw new Error(`Unexpected external token ${address}`);
  return { address, symbol, decimals };
}

async function decodeGlobalState(pool) {
  const selector = ethers.id("globalState()").slice(0, 10);
  const encoded = await ethers.provider.call({ to: pool, data: selector }, FORK_BLOCK);
  const words = (encoded.length - 2) / 64;
  const abi = ethers.AbiCoder.defaultAbiCoder();

  if (words >= 8) {
    const decoded = abi.decode(
      ["uint160", "int24", "uint16", "uint16", "uint16", "uint8", "uint8", "bool"],
      encoded
    );
    return {
      sqrtPriceX96: decoded[0].toString(),
      tick: Number(decoded[1]),
      feeZto: Number(decoded[2]),
      feeOtz: Number(decoded[3]),
      timepointIndex: Number(decoded[4]),
      communityFeeToken0: Number(decoded[5]),
      communityFeeToken1: Number(decoded[6]),
      unlocked: decoded[7],
      globalStateWords: words
    };
  }

  if (words >= 7) {
    const decoded = abi.decode(
      ["uint160", "int24", "uint16", "uint16", "uint8", "uint8", "bool"],
      encoded
    );
    return {
      sqrtPriceX96: decoded[0].toString(),
      tick: Number(decoded[1]),
      feeZto: Number(decoded[2]),
      feeOtz: Number(decoded[2]),
      timepointIndex: Number(decoded[3]),
      communityFeeToken0: Number(decoded[4]),
      communityFeeToken1: Number(decoded[5]),
      unlocked: decoded[6],
      globalStateWords: words
    };
  }

  throw new Error(`Unsupported globalState payload: ${words} words`);
}

async function readV2() {
  const token0 = (await rawCall(EXTERNAL_V2, V2, "token0"))[0];
  const token1 = (await rawCall(EXTERNAL_V2, V2, "token1"))[0];
  const reserves = await rawCall(EXTERNAL_V2, V2, "getReserves");
  const meta0 = await tokenMeta(token0);
  const meta1 = await tokenMeta(token1);
  return {
    address: EXTERNAL_V2,
    token0,
    token1,
    token0Symbol: meta0.symbol,
    token1Symbol: meta1.symbol,
    token0Decimals: meta0.decimals,
    token1Decimals: meta1.decimals,
    reserve0: reserves[0].toString(),
    reserve1: reserves[1].toString(),
    blockTimestampLast: Number(reserves[2]),
    feeBps: 30
  };
}

async function readV3() {
  const token0 = (await rawCall(EXTERNAL_V3, V3, "token0"))[0];
  const token1 = (await rawCall(EXTERNAL_V3, V3, "token1"))[0];
  const liquidity = (await rawCall(EXTERNAL_V3, V3, "liquidity"))[0];
  const tickSpacing = Math.abs(Number((await rawCall(EXTERNAL_V3, V3, "tickSpacing"))[0]));
  const global = await decodeGlobalState(EXTERNAL_V3);
  const meta0 = await tokenMeta(token0);
  const meta1 = await tokenMeta(token1);
  const balance0 = (await rawCall(token0, ERC20, "balanceOf", [EXTERNAL_V3]))[0];
  const balance1 = (await rawCall(token1, ERC20, "balanceOf", [EXTERNAL_V3]))[0];

  const scanDistance = Number(process.env.V3_SCAN_DISTANCE_TICKS || "30000");
  const center = Math.floor(global.tick / tickSpacing) * tickSpacing;
  const initializedTicks = [];

  for (let tick = center - scanDistance; tick <= center + scanDistance; tick += tickSpacing) {
    if (tick < -887272 || tick > 887272) continue;
    const row = await rawCall(EXTERNAL_V3, V3, "ticks", [tick]);
    if (row[7]) {
      initializedTicks.push({
        tick,
        liquidityTotal: row[0].toString(),
        liquidityDelta: row[1].toString()
      });
    }
  }

  const below = initializedTicks
    .filter((row) => row.tick <= global.tick)
    .sort((a, b) => b.tick - a.tick)[0];
  const above = initializedTicks
    .filter((row) => row.tick > global.tick)
    .sort((a, b) => a.tick - b.tick)[0];

  if (!below || !above) {
    throw new Error("Nearest initialized ticks not found; increase V3_SCAN_DISTANCE_TICKS");
  }

  return {
    address: EXTERNAL_V3,
    token0,
    token1,
    token0Symbol: meta0.symbol,
    token1Symbol: meta1.symbol,
    token0Decimals: meta0.decimals,
    token1Decimals: meta1.decimals,
    ...global,
    liquidity: liquidity.toString(),
    tickSpacing,
    balance0: balance0.toString(),
    balance1: balance1.toString(),
    nearestInitializedTickBelow: below.tick,
    nearestInitializedTickAbove: above.tick,
    initializedTicks
  };
}

async function main() {
  const block = await ethers.provider.getBlock(FORK_BLOCK);
  if (!block) throw new Error(`Archive block ${FORK_BLOCK} unavailable`);
  const [externalV2, externalV3] = await Promise.all([readV2(), readV3()]);
  const snapshot = {
    schema: "synergy-v7-fork-snapshot-v1",
    chainId: 137,
    forkBlock: FORK_BLOCK,
    blockHash: block.hash,
    blockTimestamp: block.timestamp,
    capturedAt: new Date().toISOString(),
    externalV2,
    externalV3
  };
  fs.mkdirSync(path.join(process.cwd(), "reports"), { recursive: true });
  const output = path.join(process.cwd(), "reports", "synergy_v7_snapshot.json");
  fs.writeFileSync(output, JSON.stringify(snapshot, null, 2));
  console.log(JSON.stringify(snapshot, null, 2));
  console.log(`Snapshot written to ${output}`);
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
