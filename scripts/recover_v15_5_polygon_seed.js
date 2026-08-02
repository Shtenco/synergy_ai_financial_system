"use strict";

const fs = require("node:fs");
const path = require("node:path");
const { ethers } = require("hardhat");

const CONFIRM = "RECOVER_V15_5_SEED_LIQUIDITY";

function required(name) {
  const value = String(process.env[name] || "").trim();
  if (!value) throw new Error(`${name} is required`);
  return value;
}

function safe(value) {
  return JSON.parse(JSON.stringify(value, (_, item) =>
    typeof item === "bigint" ? item.toString() : item
  ));
}

async function main() {
  if (process.env.CONFIRM_V155_RECOVERY !== CONFIRM) {
    throw new Error(`set CONFIRM_V155_RECOVERY=${CONFIRM}`);
  }
  const experimentAddress = required("V155_EXPERIMENT_ADDRESS");
  const [signer] = await ethers.getSigners();
  const network = await ethers.provider.getNetwork();
  if (network.chainId !== 137n) throw new Error("Polygon mainnet required");

  const experiment = await ethers.getContractAt(
    "MainnetAtomicAddLpExperimentV155",
    experimentAddress,
    signer
  );
  if ((await experiment.operator()).toLowerCase() !== signer.address.toLowerCase()) {
    throw new Error("signer is not operator");
  }
  const [stateA, stateB] = await experiment.currentPairStates();
  const min = (value) => BigInt(value) * 9000n / 10000n;
  const deadline = BigInt(Math.floor(Date.now() / 1000) + 600);
  const unwrap = String(process.env.V155_RECOVER_NATIVE || "true").toLowerCase() !== "false";
  const feeData = await ethers.provider.getFeeData();
  const minimumPriority = ethers.parseUnits("25", "gwei");
  const priority = feeData.maxPriorityFeePerGas && feeData.maxPriorityFeePerGas > minimumPriority
    ? feeData.maxPriorityFeePerGas
    : minimumPriority;
  const maxFee = feeData.maxFeePerGas || priority * 2n;

  const request = await experiment.recoverSeedLiquidity.populateTransaction(
    min(stateA.wpolReserve),
    min(stateA.experimentTokenReserve),
    min(stateB.wpolReserve),
    min(stateB.experimentTokenReserve),
    deadline,
    unwrap
  );
  const estimated = await signer.estimateGas(request);
  const gasLimit = estimated * 12n / 10n + 25_000n;
  if (gasLimit * maxFee > ethers.parseEther("1")) {
    throw new Error("recovery maximum gas cost exceeds 1 POL");
  }

  const before = await ethers.provider.getBalance(signer.address);
  const tx = await signer.sendTransaction({
    ...request,
    gasLimit,
    maxFeePerGas: maxFee,
    maxPriorityFeePerGas: priority
  });
  const receipt = await tx.wait();
  const after = await ethers.provider.getBalance(signer.address);
  const report = {
    scenario: "synergy_v15_5_recover_seed_liquidity",
    chainId: 137,
    experiment: experimentAddress,
    transactionHash: receipt.hash,
    blockNumber: receipt.blockNumber,
    gasUsed: receipt.gasUsed,
    gasPrice: receipt.gasPrice ?? receipt.effectiveGasPrice ?? 0n,
    unwrapToNative: unwrap,
    walletBalanceBeforeWei: before,
    walletBalanceAfterWei: after,
    seededAfter: await experiment.seeded()
  };
  fs.mkdirSync(path.join(process.cwd(), "reports"), { recursive: true });
  fs.writeFileSync(
    path.join(process.cwd(), "reports/v15_5_polygon_seed_recovery.json"),
    JSON.stringify(safe(report), null, 2)
  );
  console.log(JSON.stringify(safe(report), null, 2));
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
