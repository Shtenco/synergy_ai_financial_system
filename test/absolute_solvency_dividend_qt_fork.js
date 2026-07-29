const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { ethers, network } = require("hardhat");

const WPOL = "0x0d500B1d8E8eF31E21C99d1Db9A6444d3ADf1270";
const GAS_PRICE = 274_000_000_000n;
const E = ethers.parseEther;
const MAX_CYCLES = 40;
const TX_GAS_LIMIT = 8_000_000;

const WPOL_ABI = [
  "function deposit() payable",
  "function approve(address,uint256) returns(bool)",
  "function balanceOf(address) view returns(uint256)"
];

async function mine(count) {
  for (let i = 0; i < count; i++) await network.provider.send("evm_mine");
}

function n(value) {
  return Number(ethers.formatEther(value));
}

describe("Synergy absolute solvency + owner dividend on Polygon fork", function () {
  this.timeout(600000);

  it("restores 101% coverage, remains keeper-profitable, and pays the owner", async function () {
    const signers = await ethers.getSigners();
    const externalHolder = signers[5];
    const owner = signers[6];
    const funder = signers[7];
    const keeperA = signers[8];
    const keeperB = signers[9];

    assert.notEqual(await ethers.provider.getCode(WPOL), "0x", "WPOL missing: not a Polygon fork");
    const wpol = new ethers.Contract(WPOL, WPOL_ABI, funder);
    await (await wpol.deposit({ value: E("46") })).wait();

    const Controller = await ethers.getContractFactory("AbsoluteSolvencyDividendQTController", funder);
    const controller = await Controller.deploy(WPOL, owner.address, 5, { gasLimit: 29_000_000 });
    await controller.waitForDeployment();
    const controllerAddress = await controller.getAddress();

    await (await wpol.approve(controllerAddress, E("46"))).wait();
    await (await controller.bootstrap(externalHolder.address, { gasLimit: TX_GAS_LIMIT })).wait();

    const syn = await ethers.getContractAt("ForkSynQTToken", await controller.syn());
    const demand = await ethers.getContractAt("L1BuybackBurnEscrowQT", await controller.demand());
    const auction = await ethers.getContractAt("SynergyQTInventoryAuction", await controller.auction());
    const lender = await ethers.getContractAt("ForkFlashLender", await controller.lender());
    const solver = await ethers.getContractAt("AaveFlashQESolverV2", await controller.solver());

    assert.equal(await controller.bootstrapper(), ethers.ZeroAddress);
    assert.equal(await solver.operator(), controllerAddress);
    assert.equal(await auction.governor(), controllerAddress);
    assert.equal(await syn.totalSupply(), E("100"));
    assert.equal(await syn.balanceOf(await auction.getAddress()), E("72"));
    assert.equal(await syn.balanceOf(externalHolder.address), E("28"));
    assert.equal(await controller.protocolAssets(), E("43"));
    assert.equal(await controller.liabilitiesAtPar(), E("100"));
    assert.equal(await controller.reserveCoverageBps(), 4300n);
    assert.equal(await controller.equityAtPar(), -E("57"));

    const ownerBefore = await wpol.balanceOf(owner.address);
    const lenderBefore = await wpol.balanceOf(await lender.getAddress());
    const keeperABefore = await wpol.balanceOf(keeperA.address);
    const keeperBBefore = await wpol.balanceOf(keeperB.address);
    const supplyInitial = await syn.totalSupply();
    const assetsInitial = await controller.protocolAssets();

    const rows = [];
    let prepareGas = 0n;
    let executeGas = 0n;

    for (let cycle = 1; cycle <= MAX_CYCLES && !(await controller.halted()); cycle++) {
      const preparer = cycle % 2 === 1 ? keeperA : keeperB;
      const executor = cycle % 2 === 1 ? keeperB : keeperA;
      const supplyBefore = await syn.totalSupply();
      const assetsBefore = await controller.protocolAssets();

      const prepareTx = await controller.connect(preparer).step({ gasLimit: TX_GAS_LIMIT });
      const prepareReceipt = await prepareTx.wait();
      assert.equal(await controller.phase(), 2n);
      await mine(2);

      const executeTx = await controller.connect(executor).step({ gasLimit: TX_GAS_LIMIT });
      const executeReceipt = await executeTx.wait();

      const supplyAfter = await syn.totalSupply();
      const assetsAfter = await controller.protocolAssets();
      const ownerBalance = await wpol.balanceOf(owner.address);
      const cycleGas = (prepareReceipt.gasUsed + executeReceipt.gasUsed) * GAS_PRICE;

      assert.equal(supplyBefore - supplyAfter, E("2"));
      assert.equal(await syn.totalSupply(), supplyInitial - E(String(cycle * 2)));
      prepareGas += prepareReceipt.gasUsed;
      executeGas += executeReceipt.gasUsed;

      rows.push({
        cycle,
        synSupply: n(supplyAfter),
        synBurned: n(supplyBefore - supplyAfter),
        protocolAssetsWPOL: n(assetsAfter),
        protocolAssetDeltaWPOL: n(assetsAfter - assetsBefore),
        liabilitiesWPOLAtPar: n(await controller.liabilitiesAtPar()),
        equityWPOLAtPar: n(await controller.equityAtPar()),
        coveragePercent: Number(await controller.reserveCoverageBps()) / 100,
        ownerDividendsWPOL: n(ownerBalance - ownerBefore),
        cycleGasPOLAt274Gwei: n(cycleGas),
        halted: await controller.halted()
      });
    }

    const cyclesCompleted = Number(await controller.completedCycles());
    const supplyFinal = await syn.totalSupply();
    const assetsFinal = await controller.protocolAssets();
    const liabilitiesFinal = await controller.liabilitiesAtPar();
    const equityFinal = await controller.equityAtPar();
    const coverageFinal = await controller.reserveCoverageBps();
    const ownerAfter = await wpol.balanceOf(owner.address);
    const lenderAfter = await wpol.balanceOf(await lender.getAddress());
    const keeperAAfter = await wpol.balanceOf(keeperA.address);
    const keeperBAfter = await wpol.balanceOf(keeperB.address);
    const totalGasCost = (prepareGas + executeGas) * GAS_PRICE;
    const keeperRewards = (keeperAAfter - keeperABefore) + (keeperBAfter - keeperBBefore);
    const keeperProfitAfterGas = keeperRewards - totalGasCost;
    const dividends = ownerAfter - ownerBefore;

    assert.equal(cyclesCompleted, 36);
    assert.equal(await controller.halted(), true);
    assert.equal(await controller.solventHalt(), true);
    assert.equal(await controller.phase(), 3n);
    assert.equal(await controller.totalBurned(), E("72"));
    assert.equal(await demand.totalBurned(), E("72"));
    assert.equal(supplyFinal, E("28"));
    assert.equal(await syn.balanceOf(await auction.getAddress()), 0n);
    assert.equal(await syn.balanceOf(externalHolder.address), E("28"));
    assert.equal(assetsFinal, E("28.28"));
    assert.equal(liabilitiesFinal, E("28"));
    assert.equal(equityFinal, E("0.28"));
    assert.equal(coverageFinal, 10100n);
    assert.equal(dividends, E("1.013"));
    assert.equal(await controller.totalDividends(), E("1.013"));
    assert.equal(keeperRewards, E("13.68"));
    assert.equal(await controller.totalKeeperRewards(), E("13.68"));
    assert.equal(lenderAfter - lenderBefore, E("0.027"));
    assert.ok(keeperProfitAfterGas > 0n, "keeper network is unprofitable at 274 gwei");
    assert.ok(assetsFinal >= liabilitiesFinal, "system is not absolutely solvent");
    assert.ok(coverageFinal >= 10000n, "reserve coverage below 100%");
    assert.equal(supplyInitial - supplyFinal, E("72"));
    await assert.rejects(
      controller.connect(keeperA).step({ gasLimit: TX_GAS_LIMIT }).then((tx) => tx.wait())
    );

    const result = {
      scenario: "absolute_solvency_dividend_qt",
      forkBlock: await ethers.provider.getBlockNumber(),
      realPolygonWPOL: true,
      cyclesCompleted,
      ownerlessAfterBootstrap: (await controller.bootstrapper()) === ethers.ZeroAddress,
      permissionlessKeepersUsed: 2,
      selfHalted: await controller.halted(),
      solventHalt: await controller.solventHalt(),
      newSynMintedDuringRecovery: 0,
      synSupplyInitial: n(supplyInitial),
      synSupplyFinal: n(supplyFinal),
      totalSynBurned: n(supplyInitial - supplyFinal),
      debtReductionPercent: Number((supplyInitial - supplyFinal) * 10000n / supplyInitial) / 100,
      protocolAssetsInitialWPOL: n(assetsInitial),
      protocolAssetsFinalWPOL: n(assetsFinal),
      liabilitiesInitialWPOLAtPar: n(supplyInitial),
      liabilitiesFinalWPOLAtPar: n(liabilitiesFinal),
      equityInitialWPOLAtPar: n(assetsInitial - supplyInitial),
      equityFinalWPOLAtPar: n(equityFinal),
      coverageInitialPercent: 43,
      coverageFinalPercent: Number(coverageFinal) / 100,
      absoluteSolvencyPass: assetsFinal >= liabilitiesFinal && coverageFinal >= 10000n,
      ownerDividendsWPOL: n(dividends),
      dividendPass: dividends > 0n,
      totalKeeperRewardsWPOL: n(keeperRewards),
      totalPrepareGasUsed: Number(prepareGas),
      totalExecuteGasUsed: Number(executeGas),
      totalGasCostPOLAt274Gwei: n(totalGasCost),
      keeperProfitAfterGasWPOL: n(keeperProfitAfterGas),
      keeperCriterionPass: keeperProfitAfterGas > 0n,
      lenderFlashFeesWPOL: n(lenderAfter - lenderBefore),
      selfSufficientAfterBootstrap: true,
      rows
    };

    fs.mkdirSync(path.join(process.cwd(), "reports"), { recursive: true });
    fs.writeFileSync(
      path.join(process.cwd(), "reports", "absolute_solvency_dividend_qt.json"),
      JSON.stringify(result, null, 2)
    );
    console.log(`ABSOLUTE_SOLVENCY_RESULT ${JSON.stringify(result)}`);
  });
});
