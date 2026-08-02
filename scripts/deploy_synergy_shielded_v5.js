#!/usr/bin/env node
"use strict";

const fs = require("fs");
const path = require("path");
const hre = require("hardhat");
const { ethers } = hre;

const ARM_PHRASE = "DEPLOY_SYNERGY_SHIELDED_V5_MAINNET";
const ROTATED_ACK = "I_CREATED_A_NEW_UNSHARED_KEY";
const PRIVATE_ACK = "I_USE_A_PRIVATE_POLYGON_RPC";
const USDT = "0xc2132d05d31c914a87c6611c10748aeb04b58e8f";
const REQUIRED_USDT = 2_000_000n;

function required(name) {
  const value = String(process.env[name] || "").trim();
  if (!value) throw new Error(`Missing ${name}`);
  return value;
}

function receiptCost(receipt) {
  return receipt.gasUsed * (receipt.gasPrice || 0n);
}

function requireGate() {
  const reportPath = path.resolve(
    process.cwd(),
    process.env.MAINNET_GATE_REPORT || "reports/synergy_shielded_v5_mainnet_gate.json"
  );
  if (!fs.existsSync(reportPath)) throw new Error("Shielded V5 gate report missing");
  const report = JSON.parse(fs.readFileSync(reportPath, "utf8"));
  const allowed =
    report.decision === "ALLOW_MAINNET_DEPLOYMENT" &&
    report.economicsPassed === true &&
    report.routerZeroProtectionPassed === true &&
    report.frontRunProtectionPassed === true &&
    report.atomicBootstrapPassed === true &&
    report.refillRegressionPassed === true &&
    report.privateKeyLoaded === false &&
    report.transactionBroadcast === false;
  if (!allowed) throw new Error("Shielded V5 mainnet gate is not green");
  return report;
}

async function main() {
  const executionMode = required("EXECUTION_MODE");
  if (!["dry-run", "execute"].includes(executionMode)) {
    throw new Error("EXECUTION_MODE must be dry-run or execute");
  }
  if (required("KEY_ROTATED_ACK") !== ROTATED_ACK) {
    throw new Error("Fresh never-shared key acknowledgement missing");
  }
  if (executionMode === "execute") {
    if (required("PRIVATE_TX_ACK") !== PRIVATE_ACK) {
      throw new Error("Private Polygon RPC acknowledgement missing");
    }
    if (!process.env.PRIVATE_POLYGON_RPC_URL) {
      throw new Error("PRIVATE_POLYGON_RPC_URL is required for execution");
    }
    if (required("MAINNET_ARM_PHRASE") !== ARM_PHRASE) {
      throw new Error("Mainnet arm phrase incorrect");
    }
    requireGate();
  }

  const network = await ethers.provider.getNetwork();
  if (Number(network.chainId) !== 137) {
    throw new Error(`Expected Polygon chainId 137, got ${network.chainId}`);
  }
  const [signer] = await ethers.getSigners();
  const signerAddress = await signer.getAddress();
  const expected = ethers.getAddress(required("EXPECTED_DEPLOYER_ADDRESS"));
  if (signerAddress.toLowerCase() !== expected.toLowerCase()) {
    throw new Error("Signer mismatch");
  }

  const usdt = new ethers.Contract(
    USDT,
    [
      "function balanceOf(address) view returns(uint256)",
      "function approve(address,uint256) returns(bool)"
    ],
    signer
  );
  const [polBalance, usdtBalance] = await Promise.all([
    ethers.provider.getBalance(signerAddress),
    usdt.balanceOf(signerAddress)
  ]);
  const minPol = ethers.parseEther(process.env.MIN_DEPLOYER_POL || "3");
  if (polBalance < minPol) throw new Error("Insufficient POL safety balance");
  if (usdtBalance < REQUIRED_USDT) throw new Error("At least 2 USDT required");

  const preflight = {
    chainId: 137,
    signer: signerAddress,
    executionMode,
    privateRpcConfigured: Boolean(process.env.PRIVATE_POLYGON_RPC_URL),
    polBalance: ethers.formatEther(polBalance),
    usdtBalance: ethers.formatUnits(usdtBalance, 6),
    tokenName: "Synergy Coin",
    tokenSymbol: "SYNA",
    pool: "SYNA/USDT QuickSwap V2",
    privateKeyPrinted: false,
    transactionSigned: false,
    transactionBroadcast: false
  };
  console.log(JSON.stringify(preflight, null, 2));
  if (executionMode === "dry-run") return;

  const confirmations = Number(process.env.DEPLOY_CONFIRMATIONS || "2");
  let setupGasWei = 0n;

  const Bootstrap = await ethers.getContractFactory("SynergyQuickSwapBootstrapV5", signer);
  const bootstrap = await Bootstrap.deploy(signerAddress);
  await bootstrap.waitForDeployment();
  setupGasWei += receiptCost(await bootstrap.deploymentTransaction().wait(confirmations));

  setupGasWei += receiptCost(
    await (await usdt.approve(await bootstrap.getAddress(), REQUIRED_USDT)).wait(confirmations)
  );

  const latest = await ethers.provider.getBlock("latest");
  const deadline = latest.timestamp + 90;
  const bootstrapTx = await bootstrap.bootstrap(deadline);
  setupGasWei += receiptCost(await bootstrapTx.wait(confirmations));

  const tokenAddress = await bootstrap.token();
  const controllerAddress = await bootstrap.controller();
  const pairAddress = await bootstrap.pair();
  const token = await ethers.getContractAt("RebaseSynaExactV3", tokenAddress, signer);
  const controller = await ethers.getContractAt(
    "BullishQuickSwapShieldedV5",
    controllerAddress,
    signer
  );

  if ((await token.name()) !== "Synergy Coin") throw new Error("Token name mismatch");
  if ((await token.symbol()) !== "SYNA") throw new Error("Token symbol mismatch");
  if ((await controller.DEAL_SCALE_BPS()) !== 17_500n) {
    throw new Error("Deal scale mismatch");
  }
  if ((await ethers.provider.getCode(pairAddress)) === "0x") {
    throw new Error("QuickSwap pair not created");
  }

  const report = {
    ...preflight,
    executionMode: "execute",
    bootstrap: await bootstrap.getAddress(),
    token: tokenAddress,
    controller: controllerAddress,
    pair: pairAddress,
    setupGasWei: setupGasWei.toString(),
    setupGasPol: ethers.formatEther(setupGasWei),
    tokenName: await token.name(),
    tokenSymbol: await token.symbol(),
    initialMetricUsdt: ethers.formatUnits(await controller.systemMetricUsdt(), 6),
    transactionSigned: true,
    transactionBroadcast: true,
    timestamp: new Date().toISOString()
  };

  const outDir = path.join(process.cwd(), "deployments");
  fs.mkdirSync(outDir, { recursive: true });
  const out = path.join(outDir, "synergy_shielded_v5_polygon.json");
  fs.writeFileSync(out, JSON.stringify(report, null, 2));
  console.log(JSON.stringify(report, null, 2));
}

main().catch((error) => {
  console.error(error.stack || error.message || String(error));
  process.exitCode = 1;
});
