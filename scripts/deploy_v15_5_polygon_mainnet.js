"use strict";

const fs = require("node:fs");
const path = require("node:path");
const { ethers } = require("hardhat");

const ADDRESSES = Object.freeze({
  aavePool: "0x794a61358D6845594F94dc1DB02A252b5b4814aD",
  wpol: "0x0d500B1d8E8eF31E21C99d1Db9A6444d3ADf1270",
  quickSwapRouter: "0xa5E0829CaCEd8fFDD4De3c43696c57F7D7A678ff",
  quickSwapFactory: "0x5757371414417b8C6CAad45bAeF941aBc7d3Ab32"
});

const MAX_TOTAL_EXPERIMENT_RISK = ethers.parseEther("10");
const RESERVED_CYCLE_GAS_RISK = ethers.parseEther(
  process.env.V155_RESERVED_CYCLE_GAS_POL || "5"
);
const CONFIRMATION = "DEPLOY_V15_5_POLYGON_MAINNET";

function required(name) {
  const value = String(process.env[name] || "").trim();
  if (!value) throw new Error(`${name} is required`);
  return value;
}

function bigintJson(value) {
  return JSON.parse(JSON.stringify(value, (_, item) =>
    typeof item === "bigint" ? item.toString() : item
  ));
}

function addMargin(value, bps = 12000n) {
  return value * bps / 10000n + 25_000n;
}

function transactionCost(receipt) {
  const price = receipt.gasPrice ?? receipt.effectiveGasPrice ?? 0n;
  return receipt.gasUsed * price;
}

async function main() {
  if (process.env.CONFIRM_V155_DEPLOY !== CONFIRMATION) {
    throw new Error(`Refusing mainnet deployment. Set CONFIRM_V155_DEPLOY=${CONFIRMATION}`);
  }

  const [signer] = await ethers.getSigners();
  const provider = ethers.provider;
  const network = await provider.getNetwork();
  if (network.chainId !== 137n) throw new Error(`Polygon mainnet chainId 137 required, got ${network.chainId}`);

  const operator = process.env.V155_OPERATOR || signer.address;
  if (operator.toLowerCase() !== signer.address.toLowerCase()) {
    throw new Error("combined deploy-and-seed requires V155_OPERATOR to equal the disposable signer");
  }
  const reinvestmentVault = required("V155_REINVESTMENT_VAULT");
  const retainedTreasury = required("V155_RETAINED_TREASURY");
  for (const address of [operator, reinvestmentVault, retainedTreasury]) {
    if (!ethers.isAddress(address) || address === ethers.ZeroAddress) {
      throw new Error(`invalid configured address ${address}`);
    }
  }
  for (const [name, address] of Object.entries(ADDRESSES)) {
    if (await provider.getCode(address) === "0x") throw new Error(`missing code for ${name} at ${address}`);
  }

  const fee = await provider.getFeeData();
  const minimumPriority = ethers.parseUnits("25", "gwei");
  const maxPriorityFeePerGas = process.env.V155_PRIORITY_FEE_GWEI
    ? ethers.parseUnits(process.env.V155_PRIORITY_FEE_GWEI, "gwei")
    : (fee.maxPriorityFeePerGas && fee.maxPriorityFeePerGas > minimumPriority
      ? fee.maxPriorityFeePerGas
      : minimumPriority);
  const maxFeePerGas = process.env.V155_MAX_FEE_GWEI
    ? ethers.parseUnits(process.env.V155_MAX_FEE_GWEI, "gwei")
    : (fee.maxFeePerGas || maxPriorityFeePerGas * 2n);
  if (maxFeePerGas < maxPriorityFeePerGas) throw new Error("maxFeePerGas below priority fee");

  const seedWpolEach = ethers.parseEther(process.env.V155_SEED_WPOL_EACH || "0.25");
  const seedTokenEach = ethers.parseUnits(process.env.V155_SEED_TOKEN_EACH || "1000000", 18);
  const seedCapital = seedWpolEach * 2n;
  if (seedCapital > ethers.parseEther("2")) throw new Error("contract caps total seed at 2 POL");

  const Experiment = await ethers.getContractFactory("MainnetAtomicAddLpExperimentV155", signer);
  const deployment = await Experiment.getDeployTransaction(
    ADDRESSES.aavePool,
    ADDRESSES.wpol,
    ADDRESSES.quickSwapRouter,
    ADDRESSES.quickSwapFactory,
    operator,
    reinvestmentVault,
    retainedTreasury
  );
  const deployEstimate = await signer.estimateGas(deployment);
  const deployGasLimit = addMargin(deployEstimate);
  const deployMaxCost = deployGasLimit * maxFeePerGas;
  if (deployMaxCost + seedCapital + RESERVED_CYCLE_GAS_RISK > MAX_TOTAL_EXPERIMENT_RISK) {
    throw new Error("deployment + seed + reserved cycle risk exceeds 10 POL");
  }

  const startingBalance = await provider.getBalance(signer.address);
  const experiment = await Experiment.deploy(
    ADDRESSES.aavePool,
    ADDRESSES.wpol,
    ADDRESSES.quickSwapRouter,
    ADDRESSES.quickSwapFactory,
    operator,
    reinvestmentVault,
    retainedTreasury,
    { gasLimit: deployGasLimit, maxFeePerGas, maxPriorityFeePerGas }
  );
  const deployReceipt = await experiment.deploymentTransaction().wait();
  const deployCost = transactionCost(deployReceipt);
  const experimentAddress = await experiment.getAddress();

  const deadline = BigInt(Math.floor(Date.now() / 1000) + 1800);
  const seedTxRequest = await experiment.seedPools.populateTransaction(
    seedWpolEach,
    seedTokenEach,
    1,
    1,
    deadline,
    { value: seedCapital }
  );
  const seedEstimate = await signer.estimateGas(seedTxRequest);
  const seedGasLimit = addMargin(seedEstimate);
  const seedMaxCost = seedGasLimit * maxFeePerGas;
  if (deployCost + seedCapital + seedMaxCost + RESERVED_CYCLE_GAS_RISK > MAX_TOTAL_EXPERIMENT_RISK) {
    throw new Error("actual deployment + seed + reserved cycle risk exceeds 10 POL");
  }

  const seedTx = await experiment.seedPools(
    seedWpolEach,
    seedTokenEach,
    1,
    1,
    deadline,
    { value: seedCapital, gasLimit: seedGasLimit, maxFeePerGas, maxPriorityFeePerGas }
  );
  const seedReceipt = await seedTx.wait();
  const seedGasCost = transactionCost(seedReceipt);
  const consumedGas = deployCost + seedGasCost;
  const conservativeCommittedRisk = consumedGas + seedCapital + RESERVED_CYCLE_GAS_RISK;
  if (conservativeCommittedRisk > MAX_TOTAL_EXPERIMENT_RISK) {
    throw new Error("post-deployment risk accounting exceeded 10 POL");
  }

  const endingBalance = await provider.getBalance(signer.address);
  const report = {
    scenario: "synergy_v15_5_polygon_mainnet_deploy_and_seed",
    evidenceClass: "LIVE_MAINNET_DEPLOYMENT_NOT_PROFIT_EVIDENCE",
    chainId: Number(network.chainId),
    deployer: signer.address,
    operator,
    reinvestmentVault,
    retainedTreasury,
    officialAddresses: ADDRESSES,
    deployed: {
      experiment: experimentAddress,
      tokenA: await experiment.tokenA(),
      tokenB: await experiment.tokenB(),
      pairA: await experiment.pairA(),
      pairB: await experiment.pairB()
    },
    transactions: {
      deploymentHash: deployReceipt.hash,
      deploymentBlock: deployReceipt.blockNumber,
      deploymentGasUsed: deployReceipt.gasUsed,
      deploymentGasCostPolWei: deployCost,
      seedHash: seedReceipt.hash,
      seedBlock: seedReceipt.blockNumber,
      seedGasUsed: seedReceipt.gasUsed,
      seedGasCostPolWei: seedGasCost
    },
    seed: {
      wpolPerPoolWei: seedWpolEach,
      totalNativePolWrappedWei: seedCapital,
      experimentTokenPerPool: seedTokenEach,
      recoverableProtocolOwnedSeed: true
    },
    riskBudget: {
      maximumTotalWei: MAX_TOTAL_EXPERIMENT_RISK,
      actualGasSpentWei: consumedGas,
      conservativelyCountedSeedCapitalWei: seedCapital,
      reservedCycleGasWei: RESERVED_CYCLE_GAS_RISK,
      conservativeCommittedWei: conservativeCommittedRisk,
      remainingUncommittedWei: MAX_TOTAL_EXPERIMENT_RISK - conservativeCommittedRisk
    },
    wallet: {
      startingBalanceWei: startingBalance,
      endingBalanceWei: endingBalance
    },
    nextStep: "Run scripts/run_v15_5_polygon_mainnet_experiment.js only after a Polygon fork produces the expected atomic-revert report and the operator signs the explicit one-transaction confirmation."
  };

  fs.mkdirSync(path.join(process.cwd(), "reports"), { recursive: true });
  fs.writeFileSync(
    path.join(process.cwd(), "reports/v15_5_polygon_mainnet_deployment.json"),
    JSON.stringify(bigintJson(report), null, 2)
  );
  console.log(JSON.stringify(bigintJson(report), null, 2));
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
