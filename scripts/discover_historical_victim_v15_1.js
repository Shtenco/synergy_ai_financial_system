"use strict";

const fs = require("node:fs");
const path = require("node:path");
const { ethers } = require("ethers");

const RPC_URL = process.env.POLYGON_RPC_URL || "https://polygon.drpc.org";
const START_BLOCK = Number(process.env.V151_SCAN_START_BLOCK || 91266209);
const END_BLOCK = Number(process.env.V151_SCAN_END_BLOCK || 91266308);
const MIN_AMOUNT_USDC = ethers.parseUnits(process.env.V151_MIN_VICTIM_USDC || "1000", 6);

const QS_V2_ROUTER = "0xa5E0829CaCEd8fFDD4De3c43696c57F7D7A678ff";
const USDC = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174";
const WPOL = "0x0d500B1d8E8eF31E21C99d1Db9A6444d3ADf1270";
const WETH = "0x7ceB23fD6bC0adD59E62ac25578270cFf1b9f619";

const routerInterface = new ethers.Interface([
  "function swapExactTokensForTokens(uint256 amountIn,uint256 amountOutMin,address[] path,address to,uint256 deadline)",
  "function swapExactTokensForTokensSupportingFeeOnTransferTokens(uint256 amountIn,uint256 amountOutMin,address[] path,address to,uint256 deadline)"
]);

function normalize(value) {
  return String(value || "").toLowerCase();
}

function appendGithubEnv(key, value) {
  const githubEnv = process.env.GITHUB_ENV;
  if (!githubEnv) return;
  fs.appendFileSync(githubEnv, `${key}=${value}\n`, "utf8");
}

async function main() {
  if (!Number.isInteger(START_BLOCK) || !Number.isInteger(END_BLOCK) || START_BLOCK <= 0 || END_BLOCK < START_BLOCK) {
    throw new Error("invalid V15.1 scan range");
  }

  const provider = new ethers.JsonRpcProvider(RPC_URL, 137, { staticNetwork: true });
  const candidates = [];

  for (let blockNumber = END_BLOCK; blockNumber >= START_BLOCK; blockNumber -= 1) {
    const rawBlock = await provider.send("eth_getBlockByNumber", [ethers.toQuantity(blockNumber), true]);
    if (!rawBlock || !Array.isArray(rawBlock.transactions)) continue;

    for (const tx of rawBlock.transactions) {
      if (normalize(tx.to) !== normalize(QS_V2_ROUTER) || !tx.input || tx.input === "0x") continue;
      let decoded;
      try {
        decoded = routerInterface.parseTransaction({ data: tx.input, value: BigInt(tx.value || "0x0") });
      } catch (_) {
        continue;
      }
      if (!decoded) continue;

      const amountIn = BigInt(decoded.args.amountIn);
      const swapPath = Array.from(decoded.args.path);
      if (
        amountIn < MIN_AMOUNT_USDC
          || swapPath.length !== 2
          || normalize(swapPath[0]) !== normalize(USDC)
          || ![normalize(WPOL), normalize(WETH)].includes(normalize(swapPath[1]))
      ) continue;

      const receipt = await provider.getTransactionReceipt(tx.hash);
      if (!receipt || receipt.status !== 1) continue;

      candidates.push({
        transactionHash: tx.hash,
        blockNumber,
        transactionIndex: Number.parseInt(tx.transactionIndex || "0x0", 16),
        from: tx.from,
        to: tx.to,
        value: BigInt(tx.value || "0x0").toString(),
        input: tx.input,
        gas: BigInt(tx.gas || "0x0").toString(),
        amountInUsdcRaw: amountIn.toString(),
        amountInUsdc: Number(ethers.formatUnits(amountIn, 6)),
        tokenMid: swapPath[1],
        method: decoded.name
      });
    }
  }

  candidates.sort((a, b) => {
    const amountA = BigInt(a.amountInUsdcRaw);
    const amountB = BigInt(b.amountInUsdcRaw);
    if (amountA === amountB) return a.blockNumber - b.blockNumber;
    return amountA > amountB ? -1 : 1;
  });

  const reportsDir = path.join(process.cwd(), "reports");
  fs.mkdirSync(reportsDir, { recursive: true });
  const result = {
    scenario: "synergy_v15_1_historical_victim_discovery",
    chainId: 137,
    rpcHostname: new URL(RPC_URL).hostname,
    scanStartBlock: START_BLOCK,
    scanEndBlock: END_BLOCK,
    minimumVictimUsdc: Number(ethers.formatUnits(MIN_AMOUNT_USDC, 6)),
    candidateCount: candidates.length,
    selected: candidates[0] || null,
    candidates: candidates.slice(0, 25)
  };
  fs.writeFileSync(
    path.join(reportsDir, "v15_1_historical_victim_discovery.json"),
    JSON.stringify(result, null, 2)
  );

  if (!result.selected) {
    console.log("V15_1_DISCOVERY NO_HISTORICAL_VICTIM_IN_RANGE");
    process.exitCode = 2;
    return;
  }

  appendGithubEnv("HISTORICAL_VICTIM_TX_HASH", result.selected.transactionHash);
  appendGithubEnv("HISTORICAL_VICTIM_BLOCK", String(result.selected.blockNumber));
  appendGithubEnv("FORK_BLOCK_NUMBER", String(result.selected.blockNumber - 1));
  appendGithubEnv("HISTORICAL_TOKEN_MID", result.selected.tokenMid);
  console.log(`V15_1_DISCOVERY ${JSON.stringify(result.selected)}`);
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
