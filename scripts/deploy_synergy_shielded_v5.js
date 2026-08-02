#!/usr/bin/env node
"use strict";

const fs = require("fs");
const path = require("path");
const hre = require("hardhat");
const { ethers } = hre;

const ARM_PHRASE = "DEPLOY_SYNERGY_SHIELDED_V5_MAINNET";
const ROTATED_ACK = "I_CREATED_A_NEW_UNSHARED_KEY";
const PRIVATE_ACK = "I_USE_A_PRIVATE_POLYGON_RPC";
const USDT = "0xc2132D05D31c914a87C6611C10748AEb04B58e8F";
const REQUIRED_USDT = 2_000_000n;
const MAX_RUNTIME_BYTES = 24_576;

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
    report.runtimeSizePassed === true &&
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

  const privateRpc = String(process.env.PRIVATE_POLYGON_RPC_URL || "").trim();
  const publicRpc = String(process.env.POLYGON_RPC_URL || "").trim();
  if (executionMode === "execute") {
    if (required("PRIVATE_TX_ACK") !== PRIVATE_ACK) {
      throw new Error("Private Polygon RPC acknowledgement missing");
    }
    if (!privateRpc || privateRpc === publicRpc) {
      throw new Error("A distinct PRIVATE_POLYGON_RPC_URL is required for execution");
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
      "function allowance(address,address) view returns(uint256)",
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

  const pendingNonce = await ethers.provider.getTransactionCount(signerAddress, "pending");
  const predictedBootstrap = ethers.getCreateAddress({
    from: signerAddress,
    nonce: pendingNonce + 1
  });
  if ((await ethers.provider.getCode(predictedBootstrap)) !== "0x") {
    throw new Error("Predicted bootstrap address already contains code");
  }

  const preflight = {
    chainId: 137,
    signer: signerAddress,
    executionMode,
    privateRpcConfigured: Boolean(privateRpc),
    privateRpcDistinctFromPublic: Boolean(privateRpc && privateRpc !== publicRpc),
    polBalance: ethers.formatEther(polBalance),
    usdtBalance: ethers.formatUnits(usdtBalance, 6),
    predictedBootstrap,
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

  const approveReceipt = await (
    await usdt.approve(predictedBootstrap, REQUIRED_USDT)
  ).wait(confirmations);
  setupGasWei += receiptCost(approveReceipt);
  if ((await usdt.allowance(signerAddress, predictedBootstrap)) < REQUIRED_USDT) {
    throw new Error("Predicted bootstrap USDT allowance missing");
  }

  const secretSalt = ethers.hexlify(ethers.randomBytes(32));
  const Bootstrap = await ethers.getContractFactory("SynergyQuickSwapBootstrapV5", signer);
  const unsignedDeploy = await Bootstrap.getDeployTransaction(signerAddress, secretSalt);
  const estimatedGas = await ethers.provider.estimateGas({
    ...unsignedDeploy,
    from: signerAddress
  });
  const gasLimit = estimatedGas * 120n / 100n + 100_000n;
  const maxDeployGas = BigInt(process.env.MAX_DEPLOY_GAS_LIMIT || "28000000");
  if (gasLimit > maxDeployGas) {
    throw new Error(`Deployment gas ${gasLimit} exceeds configured maximum ${maxDeployGas}`);
  }

  const bootstrap = await Bootstrap.deploy(signerAddress, secretSalt, { gasLimit });
  await bootstrap.waitForDeployment();
  if ((await bootstrap.getAddress()).toLowerCase() !== predictedBootstrap.toLowerCase()) {
    throw new Error("Bootstrap deployed at unexpected address");
  }
  const deployReceipt = await bootstrap.deploymentTransaction().wait(confirmations);
  setupGasWei += receiptCost(deployReceipt);

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
  const bootstrapCode = await ethers.provider.getCode(await bootstrap.getAddress());
  const bootstrapRuntimeBytes = (bootstrapCode.length - 2) / 2;
  if (bootstrapRuntimeBytes > MAX_RUNTIME_BYTES) {
    throw new Error(`Bootstrap runtime too large: ${bootstrapRuntimeBytes}`);
  }
  const freeFloat = await token.balanceOf(signerAddress);
  if (freeFloat === 0n) throw new Error("Free-float SYNA was not delivered");

  const report = {
    ...preflight,
    executionMode: "execute",
    bootstrap: await bootstrap.getAddress(),
    token: tokenAddress,
    controller: controllerAddress,
    pair: pairAddress,
    bootstrapRuntimeBytes,
    deploymentGasEstimate: estimatedGas.toString(),
    deploymentGasLimit: gasLimit.toString(),
    setupGasWei: setupGasWei.toString(),
    setupGasPol: ethers.formatEther(setupGasWei),
    tokenName: await token.name(),
    tokenSymbol: await token.symbol(),
    freeFloatSyna: ethers.formatEther(freeFloat),
    initialMetricUsdt: ethers.formatUnits(await controller.systemMetricUsdt(), 6),
    create2SaltCommitment: ethers.keccak256(secretSalt),
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
