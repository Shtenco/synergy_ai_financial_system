const { ethers } = require("hardhat");

const E = ethers.parseEther;

async function deployConsolidatedFixture(options = {}) {
  const signers = await ethers.getSigners();
  const [
    admin,
    keeper,
    feeVault,
    bridgeVault,
    insuranceVault,
    yieldVault,
    externalBuyer,
    externalCostRecipient,
    dividendRecipient,
    externalStrategy
  ] = signers;

  const Reserve = await ethers.getContractFactory("MockReserveAsset", admin);
  const reserve = await Reserve.deploy();
  await reserve.waitForDeployment();

  const Syn = await ethers.getContractFactory("ForkSynQTToken", admin);
  const syn = await Syn.deploy();
  await syn.waitForDeployment();

  const Registry = await ethers.getContractFactory("SystemBoundaryRegistry", admin);
  const registry = await Registry.deploy(admin.address);
  await registry.waitForDeployment();

  const Ledger = await ethers.getContractFactory("ConsolidatedLedger", admin);
  const ledger = await Ledger.deploy(admin.address, await registry.getAddress());
  await ledger.waitForDeployment();

  const Solvency = await ethers.getContractFactory("SolvencyController", admin);
  const solvency = await Solvency.deploy(admin.address, await ledger.getAddress());
  await solvency.waitForDeployment();

  const MM = await ethers.getContractFactory("ExternalRevenueMarketMaker", admin);
  const mm = await MM.deploy(
    admin.address,
    await reserve.getAddress(),
    await syn.getAddress(),
    await registry.getAddress(),
    await solvency.getAddress(),
    await ledger.getAddress(),
    E(options.stressPrice || "1"),
    E(options.maximumInventory || "1000000"),
    E(options.minimumPoolDepth || "0")
  );
  await mm.waitForDeployment();

  const QT = await ethers.getContractFactory("ExternalLiabilityQT", admin);
  const qt = await QT.deploy(
    admin.address,
    await reserve.getAddress(),
    await syn.getAddress(),
    await registry.getAddress(),
    await solvency.getAddress(),
    await ledger.getAddress(),
    E(options.stressPrice || "1"),
    E(options.qtPrice || "0.75")
  );
  await qt.waitForDeployment();

  const Dividend = await ethers.getContractFactory("ExternalProfitDividendVault", admin);
  const dividend = await Dividend.deploy(
    admin.address,
    await reserve.getAddress(),
    await registry.getAddress(),
    await solvency.getAddress(),
    await ledger.getAddress(),
    E(options.minimumDividendReserve || "1"),
    options.payoutRateBps || 5000
  );
  await dividend.waitForDeployment();

  const QE = await ethers.getContractFactory("BackedReserveQE", admin);
  const qe = await QE.deploy(
    admin.address,
    await reserve.getAddress(),
    await solvency.getAddress(),
    await ledger.getAddress(),
    await registry.getAddress(),
    options.qeFractionBps || 1000,
    E(options.monthlyQECap || "100")
  );
  await qe.waitForDeployment();

  const systemAddresses = [
    await ledger.getAddress(),
    await solvency.getAddress(),
    await mm.getAddress(),
    await qt.getAddress(),
    await dividend.getAddress(),
    await qe.getAddress(),
    keeper.address,
    feeVault.address,
    bridgeVault.address,
    insuranceVault.address,
    yieldVault.address
  ];
  await (await registry.setSystemAddresses(systemAddresses, true)).wait();

  for (const module of [mm, qt, dividend, qe]) {
    await (await ledger.setRecorder(await module.getAddress(), true)).wait();
  }

  await (await qe.setDestination(0, await mm.getAddress())).wait();
  await (await qe.setDestination(1, bridgeVault.address)).wait();
  await (await qe.setDestination(2, insuranceVault.address)).wait();
  await (await qe.setDestination(3, yieldVault.address)).wait();

  const assets = {
    liquidReserves: E(options.liquidReserves || "1200"),
    stableLpNav: E(options.stableLpNav || "100"),
    volatileLpNav: E(options.volatileLpNav || "100"),
    bridgeCapital: E(options.bridgeCapital || "100"),
    insuranceAssets: E(options.insuranceAssets || "100"),
    yieldPositions: E(options.yieldPositions || "100"),
    gasReserve: E(options.gasReserve || "20"),
    unrealizedInventoryValue: E(options.inventoryValue || "0")
  };
  const liabilities = {
    externalSynrClaims: E(options.externalSynrClaims || "0"),
    vestedMevClaims: E(options.vestedMevClaims || "0"),
    bridgeObligations: E(options.bridgeObligations || "0"),
    keeperReimbursementsAccrued: E(options.keeperAccrued || "0"),
    externalDebt: E(options.externalDebt || "0"),
    expectedThirtyDayOperatingCosts: E(options.operatingCosts || "10"),
    modeledRedemptionShock: E(options.redemptionShock || "0")
  };
  await (await solvency.updateAssets(assets)).wait();
  await (await solvency.updateOtherLiabilities(liabilities)).wait();
  await (
    await solvency.updateCoverageInputs(
      E(options.immediateLiquidity || "1000"),
      E(options.stressedOutflows || "100"),
      E(options.reservePolicyCapital || "700"),
      E(options.conservativeObligations || "1000"),
      E(options.totalReimbursedGas || "100"),
      options.gasSkippedActions || 0,
      options.usefulActionsExecuted || 1
    )
  ).wait();
  await (await solvency.setBuffers(E("10"), E("10"), E("10"), E("0.0001"))).wait();
  await (await solvency.updateEnvironment(true, true, true)).wait();

  return {
    E,
    signers,
    admin,
    keeper,
    feeVault,
    bridgeVault,
    insuranceVault,
    yieldVault,
    externalBuyer,
    externalCostRecipient,
    dividendRecipient,
    externalStrategy,
    reserve,
    syn,
    registry,
    ledger,
    solvency,
    mm,
    qt,
    dividend,
    qe,
    assets,
    liabilities
  };
}

function source(label, index = 0) {
  return ethers.keccak256(ethers.toUtf8Bytes(`${label}:${index}`));
}

module.exports = { deployConsolidatedFixture, source, E };
