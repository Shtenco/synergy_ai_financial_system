#!/usr/bin/env node
"use strict";

const fs = require("fs");
const path = require("path");
const hre = require("hardhat");
const { ethers } = hre;

function required(name) {
  const value = String(process.env[name] || "").trim();
  if (!value) throw new Error(`Missing ${name}`);
  return value;
}

async function main() {
  const network = await ethers.provider.getNetwork();
  if (Number(network.chainId) !== 137) throw new Error(`Expected chainId 137, got ${network.chainId}`);
  if (required("EXECUTION_MODE") !== "execute") throw new Error("EXECUTION_MODE must be execute");
  if (required("KEY_ROTATED_ACK") !== "I_CREATED_A_NEW_UNSHARED_KEY") {
    throw new Error("Fresh unshared key acknowledgement missing");
  }
  if (required("FIRST10_ARM_PHRASE") !== "RUN_FIRST_10_BULLISH_QS_V2_CYCLES") {
    throw new Error("FIRST10_ARM_PHRASE is incorrect");
  }

  const deploymentPath = path.resolve(process.env.DEPLOYMENT_FILE || "deployments/bullish_qs_v2_polygon.json");
  const deployment = JSON.parse(fs.readFileSync(deploymentPath, "utf8"));
  const [signer] = await ethers.getSigners();
  const signerAddress = await signer.getAddress();
  if (signerAddress.toLowerCase() !== deployment.signer.toLowerCase()) throw new Error("Deployment signer mismatch");

  const controller = await ethers.getContractAt(
    "BullishQuickSwapCentralBankV2",
    deployment.controller,
    signer
  );
  const router = new ethers.Contract(
    deployment.router,
    [
      "function getAmountsOut(uint256,address[]) view returns(uint256[])",
      "function getAmountsIn(uint256,address[]) view returns(uint256[])"
    ],
    signer
  );
  const usdtAddress = ethers.getAddress(deployment.usdtAddress || process.env.POLYGON_USDT);
  const wpolAddress = ethers.getAddress(deployment.wpol);
  const confirmations = Number(process.env.CYCLE_CONFIRMATIONS || "2");
  const keeperFloor = ethers.parseEther(process.env.KEEPER_POL_FLOOR || "0.25");
  const exactGasTopup = ethers.parseEther(process.env.GAS_REFILL_POL || "2");
  const refillSlippageBps = BigInt(process.env.GAS_REFILL_SLIPPAGE_BPS || "100");

  const initialMetric = await controller.systemMetricUsdt();
  const initialPrice = await controller.spotPriceX18();
  let totalGasWei = 0n;
  const cycles = [];

  for (let i = 0; i < 10; i += 1) {
    const nativeBalance = await ethers.provider.getBalance(signerAddress);
    if (nativeBalance < keeperFloor) {
      const treasury = await controller.treasuryUsdt();
      const pathToPol = [usdtAddress, wpolAddress];
      const quote = await router.getAmountsIn(exactGasTopup, pathToPol);
      const maxUsdtIn = quote[0] * (10_000n + refillSlippageBps) / 10_000n + 1n;
      if (treasury < maxUsdtIn) throw new Error("Keeper gas below floor and treasury cannot fund exact refill");
      const deadline = Math.floor(Date.now() / 1000) + 600;
      const refillTx = await controller.refillKeeperGas(exactGasTopup, maxUsdtIn, deadline);
      const refillReceipt = await refillTx.wait(confirmations);
      totalGasWei += refillReceipt.gasUsed * (refillReceipt.gasPrice || 0n);
    }

    const nonce = await controller.nonce();
    const deadline = Math.floor(Date.now() / 1000) + 600;
    const tx = await controller.executeCycle(nonce, deadline, 0);
    const receipt = await tx.wait(confirmations);
    const gasWei = receipt.gasUsed * (receipt.gasPrice || 0n);
    totalGasWei += gasWei;
    cycles.push({
      cycle: i + 1,
      txHash: receipt.hash,
      blockNumber: receipt.blockNumber,
      gasWei: gasWei.toString(),
      metricUsdt: ethers.formatUnits(await controller.systemMetricUsdt(), 6),
      tvlUsdt: ethers.formatUnits(await controller.poolTvlUsdt(), 6),
      robotUsdt: ethers.formatUnits(await controller.robotBalanceUsdt(), 6),
      cbUsdt: ethers.formatUnits(await controller.treasuryUsdt(), 6),
    });
  }

  const finalMetric = await controller.systemMetricUsdt();
  const finalPrice = await controller.spotPriceX18();
  const gasQuote = await router.getAmountsOut(totalGasWei, [wpolAddress, usdtAddress]);
  const gasUsdt = gasQuote[1];
  const grossGrowth = finalMetric - initialMetric;
  const netGrowth = BigInt(grossGrowth) - BigInt(gasUsdt);
  const positive = netGrowth > 0n;

  let pauseTxHash = null;
  if (!positive) {
    const pauseTx = await controller.pause("FIRST_10_NET_NON_POSITIVE");
    const pauseReceipt = await pauseTx.wait(confirmations);
    pauseTxHash = pauseReceipt.hash;
  }

  const report = {
    chainId: 137,
    cyclesCompleted: 10,
    criterion: "DELTA_TVL_PLUS_ROBOT_PLUS_CB_MINUS_GAS_GREATER_THAN_ZERO",
    initialMetricUsdt: ethers.formatUnits(initialMetric, 6),
    finalMetricUsdt: ethers.formatUnits(finalMetric, 6),
    grossGrowthUsdt: ethers.formatUnits(grossGrowth, 6),
    gasPol: ethers.formatEther(totalGasWei),
    gasUsdt: ethers.formatUnits(gasUsdt, 6),
    netGrowthAfterGasUsdt: ethers.formatUnits(netGrowth, 6),
    initialPriceX18: initialPrice.toString(),
    finalPriceX18: finalPrice.toString(),
    verdict: positive ? "PASS_POSITIVE_FIRST_10" : "STOPPED_FIRST_10_NON_POSITIVE",
    paused: !positive,
    pauseTxHash,
    cycles,
    privateKeyPrinted: false,
  };
  const outDir = path.join(process.cwd(), "reports");
  fs.mkdirSync(outDir, { recursive: true });
  const out = path.join(outDir, "bullish_qs_v2_first10_polygon.json");
  fs.writeFileSync(out, JSON.stringify(report, null, 2));
  console.log(JSON.stringify(report, null, 2));
  if (!positive) process.exitCode = 2;
}

main().catch((error) => {
  console.error(error.stack || error.message || String(error));
  process.exitCode = 1;
});
