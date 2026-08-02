"use strict";

const fs = require("node:fs");
const path = require("node:path");
const { ethers } = require("hardhat");

const WPOL = "0x0d500B1d8E8eF31E21C99d1Db9A6444d3ADf1270";
const AAVE_POOL = "0x794a61358D6845594F94dc1DB02A252b5b4814aD";
const QUICKSWAP_ROUTER = "0xa5E0829CaCEd8fFDD4De3c43696c57F7D7A678ff";
const CONFIRM_REVERT = "I_ACCEPT_ONE_REVERTING_MAINNET_TRANSACTION";
const MAX_TOTAL_RISK = ethers.parseEther("10");

const pairAbi = [
  "function token0() view returns(address)",
  "function token1() view returns(address)",
  "function getReserves() view returns(uint112 reserve0,uint112 reserve1,uint32 blockTimestampLast)",
  "function balanceOf(address) view returns(uint256)"
];
const routerAbi = [
  "function getAmountsOut(uint256 amountIn,address[] path) view returns(uint256[] amounts)"
];
const aaveAbi = [
  "function FLASHLOAN_PREMIUM_TOTAL() view returns(uint128)"
];
const erc20Abi = ["function balanceOf(address) view returns(uint256)"];

function required(name) {
  const value = String(process.env[name] || "").trim();
  if (!value) throw new Error(`${name} is required`);
  return value;
}

function jsonSafe(value) {
  return JSON.parse(JSON.stringify(value, (_, item) =>
    typeof item === "bigint" ? item.toString() : item
  ));
}

function mulDiv(value, numerator, denominator) {
  return value * numerator / denominator;
}

async function normalizedReserves(pair, experimentToken) {
  const [token0, token1, raw] = await Promise.all([
    pair.token0(),
    pair.token1(),
    pair.getReserves()
  ]);
  const reserve0 = BigInt(raw.reserve0 ?? raw[0]);
  const reserve1 = BigInt(raw.reserve1 ?? raw[1]);
  if (token0.toLowerCase() === WPOL.toLowerCase() && token1.toLowerCase() === experimentToken.toLowerCase()) {
    return { wpol: reserve0, token: reserve1 };
  }
  if (token1.toLowerCase() === WPOL.toLowerCase() && token0.toLowerCase() === experimentToken.toLowerCase()) {
    return { wpol: reserve1, token: reserve0 };
  }
  throw new Error("unexpected pair composition");
}

function receiptCost(receipt) {
  const price = receipt.gasPrice ?? receipt.effectiveGasPrice ?? 0n;
  return receipt.gasUsed * price;
}

async function main() {
  const experimentAddress = required("V155_EXPERIMENT_ADDRESS");
  const [signer] = await ethers.getSigners();
  const provider = ethers.provider;
  const network = await provider.getNetwork();
  if (network.chainId !== 137n) throw new Error(`Polygon mainnet chainId 137 required, got ${network.chainId}`);
  if (await provider.getCode(experimentAddress) === "0x") throw new Error("experiment contract missing");

  const experiment = await ethers.getContractAt(
    "MainnetAtomicAddLpExperimentV155",
    experimentAddress,
    signer
  );
  if ((await experiment.operator()).toLowerCase() !== signer.address.toLowerCase()) {
    throw new Error("connected signer is not the experiment operator");
  }
  if (!(await experiment.seeded())) throw new Error("experiment pools are not seeded");
  if (await experiment.paused()) throw new Error("experiment is paused");

  const tokenA = await experiment.tokenA();
  const tokenB = await experiment.tokenB();
  const pairAAddress = await experiment.pairA();
  const pairBAddress = await experiment.pairB();
  const pairA = new ethers.Contract(pairAAddress, pairAbi, signer);
  const pairB = new ethers.Contract(pairBAddress, pairAbi, signer);
  const router = new ethers.Contract(QUICKSWAP_ROUTER, routerAbi, signer);
  const aave = new ethers.Contract(AAVE_POOL, aaveAbi, signer);
  const wpol = new ethers.Contract(WPOL, erc20Abi, signer);

  const reservesA = await normalizedReserves(pairA, tokenA);
  const reservesB = await normalizedReserves(pairB, tokenB);
  if (reservesA.wpol === 0n || reservesB.wpol === 0n) throw new Error("empty seed pool");

  const flashAmount = ethers.parseEther(process.env.V155_FLASH_WPOL || "100");
  const lpWpolA = mulDiv(flashAmount, 3000n, 10000n);
  const lpWpolB = mulDiv(flashAmount, 3000n, 10000n);
  const gradientWpolA = mulDiv(flashAmount, 100n, 10000n);
  const lpTokenA = mulDiv(lpWpolA, reservesA.token, reservesA.wpol);
  const lpTokenB = mulDiv(lpWpolB, reservesB.token, reservesB.wpol);
  const gradientTokenB = mulDiv(gradientWpolA, reservesB.token, reservesB.wpol);
  const deadline = BigInt(Math.floor(Date.now() / 1000) + 600);

  const quoteAForward = await router.getAmountsOut(gradientWpolA, [WPOL, tokenA]);
  const quoteBForward = await router.getAmountsOut(gradientTokenB, [tokenB, WPOL]);
  const strictNetFloor = mulDiv(flashAmount, 268_514_800n, 1_000_000_000_000n);
  const premiumBps = await aave.FLASHLOAN_PREMIUM_TOTAL();
  const expectedPremium = mulDiv(flashAmount, BigInt(premiumBps), 10000n);

  const plan = {
    flashAmountWpol: flashAmount,
    lpWpolA,
    lpTokenA,
    lpWpolB,
    lpTokenB,
    gradientWpolA,
    gradientTokenB,
    minTokenAOut: mulDiv(BigInt(quoteAForward[1]), 9000n, 10000n),
    minWpolBackFromA: mulDiv(gradientWpolA, 8500n, 10000n),
    minWpolOutFromB: mulDiv(BigInt(quoteBForward[1]), 9000n, 10000n),
    minTokenBBack: mulDiv(gradientTokenB, 8500n, 10000n),
    minAddWpolA: mulDiv(lpWpolA, 9950n, 10000n),
    minAddTokenA: mulDiv(lpTokenA, 9950n, 10000n),
    minAddWpolB: mulDiv(lpWpolB, 9950n, 10000n),
    minAddTokenB: mulDiv(lpTokenB, 9950n, 10000n),
    minRemoveWpolA: mulDiv(lpWpolA, 9000n, 10000n),
    minRemoveTokenA: mulDiv(lpTokenA, 9000n, 10000n),
    minRemoveWpolB: mulDiv(lpWpolB, 9000n, 10000n),
    minRemoveTokenB: mulDiv(lpTokenB, 9000n, 10000n),
    maxPremiumWpol: expectedPremium * 2n + 1n,
    minNetProfitWpol: strictNetFloor,
    deadline
  };

  const gasLimit = BigInt(process.env.V155_CYCLE_GAS_LIMIT || "4500000");
  const feeData = await provider.getFeeData();
  const minimumPriority = ethers.parseUnits("25", "gwei");
  const maxPriorityFeePerGas = process.env.V155_PRIORITY_FEE_GWEI
    ? ethers.parseUnits(process.env.V155_PRIORITY_FEE_GWEI, "gwei")
    : (feeData.maxPriorityFeePerGas && feeData.maxPriorityFeePerGas > minimumPriority
      ? feeData.maxPriorityFeePerGas
      : minimumPriority);
  const maxFeePerGas = process.env.V155_MAX_FEE_GWEI
    ? ethers.parseUnits(process.env.V155_MAX_FEE_GWEI, "gwei")
    : (feeData.maxFeePerGas || maxPriorityFeePerGas * 2n);
  const cycleMaximumGasRisk = gasLimit * maxFeePerGas;

  let priorRisk = 0n;
  const deploymentReportPath = path.join(process.cwd(), "reports/v15_5_polygon_mainnet_deployment.json");
  if (fs.existsSync(deploymentReportPath)) {
    const deployment = JSON.parse(fs.readFileSync(deploymentReportPath, "utf8"));
    priorRisk += BigInt(deployment.riskBudget?.actualGasSpentWei || 0);
    priorRisk += BigInt(deployment.riskBudget?.conservativelyCountedSeedCapitalWei || 0);
  } else {
    const priorRiskPol = required("V155_PRIOR_RISK_POL");
    priorRisk = ethers.parseEther(priorRiskPol);
  }
  if (priorRisk + cycleMaximumGasRisk > MAX_TOTAL_RISK) {
    throw new Error("deployment/seed plus maximum cycle gas risk exceeds 10 POL");
  }

  const stateBefore = {
    pairA: reservesA,
    pairB: reservesB,
    experimentWpol: await wpol.balanceOf(experimentAddress),
    aaveWpol: await wpol.balanceOf(AAVE_POOL),
    completedCycles: await experiment.completedCycles()
  };
  if (stateBefore.experimentWpol !== 0n) throw new Error("receiver subsidy detected before broadcast");

  let staticResult = "UNEXPECTED_STATIC_PASS";
  let staticError = null;
  try {
    await experiment.runAtomicCycle.staticCall(plan, {
      gasLimit,
      maxFeePerGas,
      maxPriorityFeePerGas
    });
  } catch (error) {
    staticResult = "EXPECTED_ATOMIC_REVERT_NO_EXTERNAL_SURPLUS";
    staticError = {
      shortMessage: error.shortMessage || "",
      reason: error.reason || "",
      data: error.data || error.info?.error?.data || "",
      message: error.message || String(error)
    };
  }

  const preflight = {
    scenario: "synergy_v15_5_polygon_mainnet_atomic_addlp_preflight",
    chainId: 137,
    experiment: experimentAddress,
    operator: signer.address,
    plan,
    aavePremiumBps: premiumBps,
    expectedPremiumWpolWei: expectedPremium,
    strictNetFloorWpolWei: strictNetFloor,
    gas: {
      gasLimit,
      maxFeePerGas,
      maxPriorityFeePerGas,
      maximumCycleGasRiskWei: cycleMaximumGasRisk,
      priorConservativeRiskWei: priorRisk,
      maximumCombinedRiskWei: priorRisk + cycleMaximumGasRisk,
      hardBudgetWei: MAX_TOTAL_RISK
    },
    stateBefore,
    staticResult,
    staticError
  };
  fs.mkdirSync(path.join(process.cwd(), "reports"), { recursive: true });
  fs.writeFileSync(
    path.join(process.cwd(), "reports/v15_5_polygon_mainnet_preflight.json"),
    JSON.stringify(jsonSafe(preflight), null, 2)
  );
  console.log(JSON.stringify(jsonSafe(preflight), null, 2));

  if (staticResult === "UNEXPECTED_STATIC_PASS") {
    throw new Error(
      "Unexpected static PASS: mainnet broadcast is blocked until an independent trace and consolidated-NAV audit approves a separate success experiment."
    );
  }
  if (process.env.V155_BROADCAST_REVERT_PROBE !== CONFIRM_REVERT) {
    console.log(`NOT BROADCAST: set V155_BROADCAST_REVERT_PROBE=${CONFIRM_REVERT} to spend gas on the one expected-revert scientific probe.`);
    return;
  }

  const populated = await experiment.runAtomicCycle.populateTransaction(plan);
  const tx = await signer.sendTransaction({
    ...populated,
    gasLimit,
    maxFeePerGas,
    maxPriorityFeePerGas
  });
  console.log(`V15.5 mainnet probe submitted: ${tx.hash}`);

  let receipt;
  try {
    receipt = await tx.wait();
  } catch (error) {
    receipt = error.receipt || await provider.getTransactionReceipt(tx.hash);
  }
  if (!receipt) throw new Error("transaction receipt unavailable");

  const stateAfter = {
    pairA: await normalizedReserves(pairA, tokenA),
    pairB: await normalizedReserves(pairB, tokenB),
    experimentWpol: await wpol.balanceOf(experimentAddress),
    aaveWpol: await wpol.balanceOf(AAVE_POOL),
    completedCycles: await experiment.completedCycles()
  };
  const gasCost = receiptCost(receipt);
  const exactRollback = (
    stateAfter.pairA.wpol === stateBefore.pairA.wpol
      && stateAfter.pairA.token === stateBefore.pairA.token
      && stateAfter.pairB.wpol === stateBefore.pairB.wpol
      && stateAfter.pairB.token === stateBefore.pairB.token
      && stateAfter.experimentWpol === stateBefore.experimentWpol
      && stateAfter.aaveWpol === stateBefore.aaveWpol
      && stateAfter.completedCycles === stateBefore.completedCycles
  );

  const result = {
    ...preflight,
    evidenceClass: "LIVE_POLYGON_MAINNET_ONE_TRANSACTION_PROBE",
    transactionHash: tx.hash,
    blockNumber: receipt.blockNumber,
    receiptStatus: receipt.status,
    gasUsed: receipt.gasUsed,
    effectiveGasPrice: receipt.gasPrice ?? receipt.effectiveGasPrice ?? 0n,
    actualGasCostPolWei: gasCost,
    stateAfter,
    exactAtomicRollback: exactRollback,
    countedRevenueWpolWei: stateAfter.completedCycles > stateBefore.completedCycles
      ? await experiment.cumulativeNetProfitWpol()
      : 0n,
    verdict: receipt.status === 0 && exactRollback
      ? "EXPECTED_REVERT_CONFIRMED_ONLY_GAS_SPENT"
      : (receipt.status === 1 ? "UNEXPECTED_SUCCESS_REQUIRES_STRICT_PROFIT_AUDIT" : "ROLLBACK_MISMATCH_FAIL_CLOSED")
  };
  fs.writeFileSync(
    path.join(process.cwd(), "reports/v15_5_polygon_mainnet_probe_result.json"),
    JSON.stringify(jsonSafe(result), null, 2)
  );
  console.log(JSON.stringify(jsonSafe(result), null, 2));

  if (!exactRollback && receipt.status === 0) throw new Error("failed transaction did not match expected rollback snapshot");
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
