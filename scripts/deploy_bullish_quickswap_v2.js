#!/usr/bin/env node
"use strict";

const fs = require("fs");
const path = require("path");
const hre = require("hardhat");
const { ethers } = hre;

const ARM_PHRASE = "DEPLOY_BULLISH_QS_V2_MAINNET";
const ROTATED_ACK = "I_CREATED_A_NEW_UNSHARED_KEY";

function required(name) {
  const value = String(process.env[name] || "").trim();
  if (!value) throw new Error(`Missing ${name}`);
  return value;
}

function asAddress(name) {
  return ethers.getAddress(required(name));
}

async function requireCode(provider, label, address) {
  const code = await provider.getCode(address);
  if (code === "0x") throw new Error(`${label} has no code: ${address}`);
}

function requirePositiveForkGate() {
  const reportPath = path.resolve(
    process.cwd(),
    process.env.MAINNET_GATE_REPORT || "reports/bullish_quickswap_mainnet_stop_first10.json"
  );
  if (!fs.existsSync(reportPath)) throw new Error("Mainnet gate report is missing");
  const report = JSON.parse(fs.readFileSync(reportPath, "utf8"));
  if (
    report.decision !== "ALLOW_MAINNET_DEPLOYMENT" ||
    Number(report.netGrowthAfterGasUsdt) <= 0 ||
    report.privateKeyLoaded !== false ||
    report.transactionBroadcast !== false
  ) {
    throw new Error("Mainnet blocked: first-ten fork growth did not exceed full gas");
  }
  return report;
}

async function main() {
  const network = await ethers.provider.getNetwork();
  if (Number(network.chainId) !== 137) throw new Error(`Expected Polygon chainId 137, got ${network.chainId}`);

  const executionMode = required("EXECUTION_MODE");
  if (!["dry-run", "execute"].includes(executionMode)) throw new Error("EXECUTION_MODE must be dry-run or execute");
  if (required("KEY_ROTATED_ACK") !== ROTATED_ACK) {
    throw new Error("Refusing deployment: create a new private key that has never been shared, then set KEY_ROTATED_ACK");
  }
  if (executionMode === "execute") {
    if (required("MAINNET_ARM_PHRASE") !== ARM_PHRASE) {
      throw new Error("Mainnet arm phrase is absent or incorrect");
    }
    requirePositiveForkGate();
  }

  const [signer] = await ethers.getSigners();
  const signerAddress = await signer.getAddress();
  const expected = asAddress("EXPECTED_DEPLOYER_ADDRESS");
  if (signerAddress.toLowerCase() !== expected.toLowerCase()) throw new Error("Signer does not match EXPECTED_DEPLOYER_ADDRESS");

  const routerAddress = asAddress("QUICKSWAP_V2_ROUTER");
  const usdtAddress = asAddress("POLYGON_USDT");
  const wpolAddress = asAddress("POLYGON_WPOL");
  await requireCode(ethers.provider, "router", routerAddress);
  await requireCode(ethers.provider, "USDT", usdtAddress);
  await requireCode(ethers.provider, "WPOL", wpolAddress);

  const router = new ethers.Contract(
    routerAddress,
    ["function factory() view returns(address)", "function WETH() view returns(address)"],
    signer
  );
  const [factoryAddress, routerWrapped] = await Promise.all([router.factory(), router.WETH()]);
  await requireCode(ethers.provider, "factory", factoryAddress);
  if (routerWrapped.toLowerCase() !== wpolAddress.toLowerCase()) throw new Error("Router wrapped-native token mismatch");

  const usdt = new ethers.Contract(usdtAddress, ["function balanceOf(address) view returns(uint256)"], signer);
  const [nativeBalance, usdtBalance] = await Promise.all([
    ethers.provider.getBalance(signerAddress),
    usdt.balanceOf(signerAddress),
  ]);
  const poolUsdt = ethers.parseUnits(process.env.INIT_POOL_USDT || "1", 6);
  const workingUsdt = ethers.parseUnits(process.env.INIT_ROBOT_USDT || "1", 6);
  if (usdtBalance < poolUsdt + workingUsdt) throw new Error("Insufficient USDT for pool and robot capital");
  const minimumPol = ethers.parseEther(process.env.MIN_DEPLOYER_POL || "1");
  if (nativeBalance < minimumPol) throw new Error("Insufficient POL for deployment safety floor");

  const preflight = {
    chainId: 137,
    signer: signerAddress,
    router: routerAddress,
    factory: factoryAddress,
    usdtAddress,
    wpol: wpolAddress,
    deployerPol: ethers.formatEther(nativeBalance),
    deployerUsdt: ethers.formatUnits(usdtBalance, 6),
    executionMode,
    tokenImplementation: "RebaseSynaExactV3",
    controllerImplementation: "BullishQuickSwapCentralBankV2",
    privateKeyPrinted: false,
  };
  console.log(JSON.stringify(preflight, null, 2));
  if (executionMode === "dry-run") {
    console.log("DRY-RUN PASS: no transaction signed or broadcast");
    return;
  }

  const confirmations = Number(process.env.DEPLOY_CONFIRMATIONS || "2");
  const totalSupply = ethers.parseEther(process.env.INIT_TOTAL_SUPPLY || "1000000");
  const poolToken = ethers.parseEther(process.env.INIT_POOL_SYNA || "500000");

  const Token = await ethers.getContractFactory("RebaseSynaExactV3", signer);
  const token = await Token.deploy(signerAddress);
  await token.waitForDeployment();
  await token.deploymentTransaction().wait(confirmations);

  const Controller = await ethers.getContractFactory("BullishQuickSwapCentralBankV2", signer);
  const controller = await Controller.deploy(
    signerAddress,
    routerAddress,
    usdtAddress,
    wpolAddress,
    await token.getAddress()
  );
  await controller.waitForDeployment();
  await controller.deploymentTransaction().wait(confirmations);

  await (await token.setController(await controller.getAddress())).wait(confirmations);
  const usdtWrite = new ethers.Contract(
    usdtAddress,
    ["function approve(address,uint256) returns(bool)"],
    signer
  );
  await (await usdtWrite.approve(await controller.getAddress(), poolUsdt + workingUsdt)).wait(confirmations);
  const deadline = Math.floor(Date.now() / 1000) + 1800;
  await (
    await controller.initialize(totalSupply, poolToken, poolUsdt, workingUsdt, deadline)
  ).wait(confirmations);

  const pairAddress = await controller.pair();
  await requireCode(ethers.provider, "SYNA/USDT pair", pairAddress);
  const report = {
    ...preflight,
    executionMode: "execute",
    token: await token.getAddress(),
    controller: await controller.getAddress(),
    pair: pairAddress,
    initialized: true,
    txSigned: true,
    txBroadcast: true,
    timestamp: new Date().toISOString(),
  };
  const outDir = path.join(process.cwd(), "deployments");
  fs.mkdirSync(outDir, { recursive: true });
  const out = path.join(outDir, "bullish_qs_v3_polygon.json");
  fs.writeFileSync(out, JSON.stringify(report, null, 2));
  console.log(JSON.stringify(report, null, 2));
}

main().catch((error) => {
  console.error(error.stack || error.message || String(error));
  process.exitCode = 1;
});
