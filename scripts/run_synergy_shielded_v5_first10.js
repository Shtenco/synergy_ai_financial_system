#!/usr/bin/env node
"use strict";

const fs = require("fs");
const path = require("path");
const hre = require("hardhat");
const { ethers } = hre;

const ARM_PHRASE = "RUN_FIRST_10_SYNERGY_SHIELDED_V5_CYCLES";
const KEY_ACK = "I_CREATED_A_NEW_UNSHARED_KEY";
const PRIVATE_ACK = "I_USE_A_PRIVATE_POLYGON_RPC";
const WPOL = "0x0d500B1d8E8eF31E21C99d1Db9A6444d3ADf1270";
const USDT = "0xc2132D05D31c914a87C6611C10748AEb04B58e8F";

function required(name) {
  const value = String(process.env[name] || "").trim();
  if (!value) throw new Error(`Missing ${name}`);
  return value;
}

function receiptCost(receipt) {
  return receipt.gasUsed * (receipt.gasPrice || 0n);
}

async function freshLatestBlock(provider) {
  const raw = await provider.send("eth_getBlockByNumber", ["latest", false]);
  if (!raw || !raw.hash || !raw.timestamp) throw new Error("Fresh latest block unavailable");
  return {
    hash: raw.hash,
    timestamp: Number(BigInt(raw.timestamp)),
    number: Number(BigInt(raw.number)),
  };
}

async function protectedFees(provider, hardCeilingWei) {
  const fee = await provider.getFeeData();
  const maxFee = fee.maxFeePerGas || fee.gasPrice;
  if (!maxFee || maxFee <= 0n) throw new Error("Provider returned no usable gas price");
  if (maxFee > hardCeilingWei) {
    throw new Error(`Network maxFeePerGas ${maxFee} exceeds shield ceiling ${hardCeilingWei}`);
  }
  const priority = fee.maxPriorityFeePerGas || 0n;
  return {
    protectedMaximum: maxFee,
    overrides: {
      maxFeePerGas: maxFee,
      maxPriorityFeePerGas: priority > maxFee ? maxFee : priority,
    },
  };
}

async function main() {
  if (required("EXECUTION_MODE") !== "execute") throw new Error("EXECUTION_MODE must be execute");
  if (required("KEY_ROTATED_ACK") !== KEY_ACK) throw new Error("Fresh key acknowledgement missing");
  if (required("PRIVATE_TX_ACK") !== PRIVATE_ACK) throw new Error("Private RPC acknowledgement missing");
  if (required("FIRST10_ARM_PHRASE") !== ARM_PHRASE) throw new Error("FIRST10_ARM_PHRASE incorrect");

  const privateRpc = required("PRIVATE_POLYGON_RPC_URL");
  const publicRpc = String(process.env.POLYGON_RPC_URL || "").trim();
  if (privateRpc === publicRpc) throw new Error("Private and public Polygon RPC endpoints must differ");

  const network = await ethers.provider.getNetwork();
  if (Number(network.chainId) !== 137) throw new Error(`Expected Polygon 137, got ${network.chainId}`);

  const deploymentPath = path.resolve(
    process.env.DEPLOYMENT_FILE || "deployments/synergy_shielded_v5_polygon.json"
  );
  if (!fs.existsSync(deploymentPath)) throw new Error("Shielded V5 deployment report missing");
  const deployment = JSON.parse(fs.readFileSync(deploymentPath, "utf8"));
  if (!deployment.bootstrap || !deployment.controller || !deployment.setupGasWei) {
    throw new Error("Incomplete deployment report");
  }

  const [signer] = await ethers.getSigners();
  const signerAddress = await signer.getAddress();
  if (signerAddress.toLowerCase() !== String(deployment.signer).toLowerCase()) {
    throw new Error("Deployment signer mismatch");
  }

  const bootstrap = await ethers.getContractAt(
    "SynergyQuickSwapBootstrapV5",
    deployment.bootstrap,
    signer
  );
  const controller = await ethers.getContractAt(
    "BullishQuickSwapShieldedV5",
    deployment.controller,
    signer
  );
  const router = new ethers.Contract(
    deployment.router || "0xa5E0829CaCEd8fFDD4De3c43696c57F7D7A678ff",
    ["function getAmountsOut(uint256,address[]) view returns(uint256[] memory)"],
    signer
  );

  if ((await bootstrap.admin()).toLowerCase() !== signerAddress.toLowerCase()) {
    throw new Error("Signer is not bootstrap admin");
  }
  if ((await controller.DEAL_SCALE_BPS()) !== 17_500n) throw new Error("Unexpected deal scale");

  const initialMetric = await controller.systemMetricUsdt();
  const initialPrice = await controller.spotPriceX18();
  const setupGasWei = BigInt(deployment.setupGasWei);
  const confirmations = Number(process.env.CYCLE_CONFIRMATIONS || "2");
  const gasCeiling = await controller.gasPriceCeilingWei();
  const keeperFloor = ethers.parseEther(process.env.KEEPER_POL_FLOOR || "0.5");
  let runtimeGasWei = 0n;
  const cycles = [];

  for (let i = 0; i < 10; i += 1) {
    const keeperPol = await ethers.provider.getBalance(signerAddress);
    if (keeperPol < keeperFloor) {
      throw new Error(
        `Keeper POL ${ethers.formatEther(keeperPol)} below safety floor; refuse to risk an underfunded cycle`
      );
    }

    const stateHash = await controller.currentExecutionStateHash();
    const expectedNonce = await controller.nonce();
    const block = await freshLatestBlock(ethers.provider);
    const fees = await protectedFees(ethers.provider, gasCeiling);
    const tx = await bootstrap.executeProtectedCycle(
      expectedNonce,
      stateHash,
      block.hash,
      block.timestamp + 60,
      fees.protectedMaximum,
      0,
      fees.overrides
    );
    const receipt = await tx.wait(confirmations);
    const gasWei = receiptCost(receipt);
    runtimeGasWei += gasWei;

    cycles.push({
      cycle: i + 1,
      txHash: receipt.hash,
      blockNumber: receipt.blockNumber,
      gasWei: gasWei.toString(),
      metricUsdt: ethers.formatUnits(await controller.systemMetricUsdt(), 6),
      tvlUsdt: ethers.formatUnits(await controller.poolTvlUsdt(), 6),
      robotUsdt: ethers.formatUnits(await controller.robotBalanceUsdt(), 6),
      cbUsdt: ethers.formatUnits(await controller.treasuryUsdt(), 6),
      priceX18: (await controller.spotPriceX18()).toString(),
    });
  }

  const finalMetric = await controller.systemMetricUsdt();
  const finalPrice = await controller.spotPriceX18();
  const fullGasWei = setupGasWei + runtimeGasWei;
  const gasQuote = await router.getAmountsOut(fullGasWei, [WPOL, USDT]);
  if (gasQuote.length !== 2 || gasQuote[1] <= 0n) throw new Error("Zero gas valuation quote");
  const fullGasUsdt = gasQuote[1];
  const grossGrowth = finalMetric - initialMetric;
  const netGrowth = grossGrowth - fullGasUsdt;
  const positive = netGrowth > 0n;

  let pauseTxHash = null;
  if (!positive) {
    const fees = await protectedFees(ethers.provider, gasCeiling);
    const pauseReceipt = await (
      await bootstrap.pause("FIRST_10_TVL_ROBOT_CB_MINUS_FULL_GAS_NON_POSITIVE", fees.overrides)
    ).wait(confirmations);
    pauseTxHash = pauseReceipt.hash;
  }

  const report = {
    network: "polygon-mainnet",
    chainId: 137,
    tokenName: "Synergy Coin",
    tokenSymbol: "SYNA",
    pair: deployment.pair,
    controller: deployment.controller,
    bootstrap: deployment.bootstrap,
    cyclesCompleted: 10,
    tradesCompleted: 70,
    criterion: "DELTA_TVL_PLUS_ROBOT_PLUS_CB_MINUS_COMPLETE_SETUP_AND_RUNTIME_GAS_GREATER_THAN_ZERO",
    initialMetricUsdt: ethers.formatUnits(initialMetric, 6),
    finalMetricUsdt: ethers.formatUnits(finalMetric, 6),
    grossGrowthUsdt: ethers.formatUnits(grossGrowth, 6),
    setupGasPol: ethers.formatEther(setupGasWei),
    runtimeGasPol: ethers.formatEther(runtimeGasWei),
    fullGasPol: ethers.formatEther(fullGasWei),
    fullGasUsdt: ethers.formatUnits(fullGasUsdt, 6),
    netGrowthAfterGasUsdt: ethers.formatUnits(netGrowth, 6),
    initialPriceX18: initialPrice.toString(),
    finalPriceX18: finalPrice.toString(),
    verdict: positive ? "PASS_POSITIVE_FIRST_10" : "STOPPED_FIRST_10_NON_POSITIVE",
    paused: !positive,
    pauseTxHash,
    cycles,
    privateKeyPrinted: false,
    timestamp: new Date().toISOString(),
  };

  const outDir = path.join(process.cwd(), "reports");
  fs.mkdirSync(outDir, { recursive: true });
  const outPath = path.join(outDir, "synergy_shielded_v5_first10_polygon.json");
  fs.writeFileSync(outPath, JSON.stringify(report, null, 2));
  console.log(JSON.stringify(report, null, 2));
  if (!positive) process.exitCode = 2;
}

main().catch((error) => {
  console.error(error.stack || error.message || String(error));
  process.exitCode = 1;
});
