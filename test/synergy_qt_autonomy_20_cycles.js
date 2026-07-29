const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { ethers, network } = require("hardhat");

const WPOL = "0x0d500B1d8E8eF31E21C99d1Db9A6444d3ADf1270";
const GAS_PRICE = 274_000_000_000n;
const E = ethers.parseEther;
const CYCLES = 20;
const TX_GAS_LIMIT = 8_000_000;

const WPOL_ABI = [
  "function deposit() payable",
  "function approve(address,uint256) returns(bool)",
  "function balanceOf(address) view returns(uint256)"
];

async function mine(count) {
  for (let i = 0; i < count; i++) {
    await network.provider.send("evm_mine");
  }
}

function f(value) {
  return Number(ethers.formatEther(value));
}

describe("Synergy QT ownerless autonomous controller - 20 real cycles", function () {
  this.timeout(600000);

  it("runs 20 permissionless prepare/reveal/buyback/burn cycles and halts itself", async function () {
    const signers = await ethers.getSigners();
    const funder = signers[7];
    const keeperA = signers[8];
    const keeperB = signers[9];

    assert.notEqual(await ethers.provider.getCode(WPOL), "0x", "WPOL missing: not a Polygon fork");
    const wpol = new ethers.Contract(WPOL, WPOL_ABI, funder);
    await (await wpol.deposit({ value: E("50") })).wait();

    const Controller = await ethers.getContractFactory("AutonomousQTController", funder);
    const controller = await Controller.deploy(
      WPOL,
      E("1"),
      E("2"),
      E("40"),
      5,
      { gasLimit: 28_000_000 }
    );
    await controller.waitForDeployment();
    const controllerAddress = await controller.getAddress();

    await (await wpol.approve(controllerAddress, E("46"))).wait();
    await (await controller.bootstrap(
      E("100"),
      E("40"),
      E("40"),
      E("1"),
      E("2"),
      E("3"),
      { gasLimit: TX_GAS_LIMIT }
    )).wait();

    const syn = await ethers.getContractAt("ForkSynQTToken", await controller.syn());
    const demand = await ethers.getContractAt("L1BuybackBurnEscrowQT", await controller.demand());
    const auction = await ethers.getContractAt("SynergyQTInventoryAuction", await controller.auction());
    const lender = await ethers.getContractAt("ForkFlashLender", await controller.lender());
    const solver = await ethers.getContractAt("AaveFlashQESolverV2", await controller.solver());

    assert.equal(await controller.bootstrapper(), ethers.ZeroAddress, "bootstrap authority was not renounced");
    assert.equal(await solver.operator(), controllerAddress, "solver is not controlled exclusively by state machine");
    assert.equal(await auction.governor(), controllerAddress, "auction is not controlled exclusively by state machine");
    assert.equal(await controller.phase(), 1n, "controller did not enter permissionless prepare phase");

    const supplyInitial = await syn.totalSupply();
    const protocolWpolInitial = await controller.protocolWpol();
    const inventoryInitial = await controller.remainingInventory();
    const keeperAInitial = await wpol.balanceOf(keeperA.address);
    const keeperBInitial = await wpol.balanceOf(keeperB.address);
    const lenderInitial = await wpol.balanceOf(await lender.getAddress());

    assert.equal(supplyInitial, E("100"));
    assert.equal(protocolWpolInitial, E("43"));
    assert.equal(inventoryInitial, E("40"));

    const rows = [];
    let totalPrepareGas = 0n;
    let totalExecuteGas = 0n;
    let totalKeeperRewards = 0n;
    let totalEquityGain = 0n;

    for (let cycle = 1; cycle <= CYCLES; cycle++) {
      const preparer = cycle % 2 === 1 ? keeperA : keeperB;
      const executor = cycle % 2 === 1 ? keeperB : keeperA;
      const preparerBefore = await wpol.balanceOf(preparer.address);
      const executorBefore = await wpol.balanceOf(executor.address);
      const supplyBefore = await syn.totalSupply();
      const protocolBefore = await controller.protocolWpol();

      const prepareTx = await controller.connect(preparer).step({ gasLimit: TX_GAS_LIMIT });
      const prepareReceipt = await prepareTx.wait();
      assert.equal(await controller.phase(), 2n, `cycle ${cycle}: controller did not enter reveal phase`);
      const pending = await controller.pending();
      assert.equal(pending.baseAmount, E("2"), `cycle ${cycle}: incorrect autonomous base amount`);
      assert.equal(pending.payment, E("1.5"), `cycle ${cycle}: incorrect autonomous payment`);

      await mine(2);

      const executeTx = await controller.connect(executor).step({ gasLimit: TX_GAS_LIMIT });
      const executeReceipt = await executeTx.wait();

      const supplyAfter = await syn.totalSupply();
      const protocolAfter = await controller.protocolWpol();
      const preparerAfter = await wpol.balanceOf(preparer.address);
      const executorAfter = await wpol.balanceOf(executor.address);
      const burned = supplyBefore - supplyAfter;
      const reserveSpend = protocolBefore - protocolAfter;
      const equityGain = burned - reserveSpend;
      const keeperReward = (preparerAfter - preparerBefore) + (executorAfter - executorBefore);
      const standardizedGasCost = (prepareReceipt.gasUsed + executeReceipt.gasUsed) * GAS_PRICE;
      const keeperProfitAfterGas = keeperReward - standardizedGasCost;

      assert.equal(burned, E("2"), `cycle ${cycle}: debt burn failed`);
      assert.equal(reserveSpend, E("0.5"), `cycle ${cycle}: reserve accounting failed`);
      assert.equal(equityGain, E("1.5"), `cycle ${cycle}: equity accounting failed`);
      assert.equal(keeperReward, E("0.49925"), `cycle ${cycle}: keeper reward failed`);
      assert.ok(keeperProfitAfterGas > 0n, `cycle ${cycle}: keepers unprofitable at 274 gwei`);
      assert.equal(await controller.completedCycles(), BigInt(cycle));

      totalPrepareGas += prepareReceipt.gasUsed;
      totalExecuteGas += executeReceipt.gasUsed;
      totalKeeperRewards += keeperReward;
      totalEquityGain += equityGain;

      rows.push({
        cycle,
        synSupply: f(supplyAfter),
        synBurned: f(burned),
        remainingInventory: f(await controller.remainingInventory()),
        remainingDemandBase: f(await demand.remainingBase()),
        protocolWpol: f(protocolAfter),
        protocolReserveSpendWPOL: f(reserveSpend),
        protocolEquityGainWPOLAtPar: f(equityGain),
        keeperRewardWPOL: f(keeperReward),
        prepareGasUsed: Number(prepareReceipt.gasUsed),
        executeGasUsed: Number(executeReceipt.gasUsed),
        standardizedGasCostPOLAt274Gwei: f(standardizedGasCost),
        keeperProfitAfterGasWPOL: f(keeperProfitAfterGas)
      });
    }

    const supplyFinal = await syn.totalSupply();
    const protocolWpolFinal = await controller.protocolWpol();
    const keeperAFinal = await wpol.balanceOf(keeperA.address);
    const keeperBFinal = await wpol.balanceOf(keeperB.address);
    const lenderFinal = await wpol.balanceOf(await lender.getAddress());
    const totalGasCost = (totalPrepareGas + totalExecuteGas) * GAS_PRICE;
    const totalKeeperProfitAfterGas = totalKeeperRewards - totalGasCost;
    const equityInitial = protocolWpolInitial - supplyInitial;
    const equityFinal = protocolWpolFinal - supplyFinal;

    assert.equal(await controller.completedCycles(), 20n);
    assert.equal(await controller.totalBurned(), E("40"));
    assert.equal(await demand.totalBurned(), E("40"));
    assert.equal(await controller.remainingInventory(), 0n);
    assert.equal(await demand.remainingBase(), 0n);
    assert.equal(supplyFinal, E("60"));
    assert.equal(protocolWpolFinal, E("33"));
    assert.equal(totalEquityGain, E("30"));
    assert.equal(equityFinal - equityInitial, E("30"));
    assert.equal(totalKeeperRewards, E("9.985"));
    assert.equal((keeperAFinal - keeperAInitial) + (keeperBFinal - keeperBInitial), E("9.985"));
    assert.equal(lenderFinal - lenderInitial, E("0.015"));
    assert.ok(totalKeeperProfitAfterGas > 0n, "20-cycle keeper network was not profitable after gas");
    assert.equal(await controller.halted(), true, "controller did not halt after exhausting inventory");
    assert.equal(await controller.phase(), 3n, "controller did not enter terminal phase");
    await assert.rejects(controller.connect(keeperA).step({ gasLimit: TX_GAS_LIMIT }));

    const result = {
      scenario: "autonomous_qt_20_cycles",
      forkBlock: await ethers.provider.getBlockNumber(),
      cyclesRequested: CYCLES,
      cyclesCompleted: Number(await controller.completedCycles()),
      realPolygonWPOL: true,
      ownerlessAfterBootstrap: (await controller.bootstrapper()) === ethers.ZeroAddress,
      permissionlessKeepersUsed: 2,
      selfHalted: await controller.halted(),
      newSynMintedDuringCycles: 0,
      synSupplyInitial: f(supplyInitial),
      synSupplyFinal: f(supplyFinal),
      totalSynBurned: f(supplyInitial - supplyFinal),
      debtReductionPercent: Number(((supplyInitial - supplyFinal) * 10_000n / supplyInitial)) / 100,
      protocolWpolInitial: f(protocolWpolInitial),
      protocolWpolFinal: f(protocolWpolFinal),
      protocolReserveSpendWPOL: f(protocolWpolInitial - protocolWpolFinal),
      protocolEquityInitialWPOLAtPar: f(equityInitial),
      protocolEquityFinalWPOLAtPar: f(equityFinal),
      protocolEquityGainWPOLAtPar: f(equityFinal - equityInitial),
      protocolCriterionPass: equityFinal > equityInitial,
      totalKeeperRewardsWPOL: f(totalKeeperRewards),
      totalPrepareGasUsed: Number(totalPrepareGas),
      totalExecuteGasUsed: Number(totalExecuteGas),
      totalGasCostPOLAt274Gwei: f(totalGasCost),
      totalKeeperProfitAfterGasWPOL: f(totalKeeperProfitAfterGas),
      keeperCriterionPass: totalKeeperProfitAfterGas > 0n,
      lenderFlashFeesWPOL: f(lenderFinal - lenderInitial),
      terminalInventorySYN: f(await controller.remainingInventory()),
      terminalDemandBaseSYN: f(await demand.remainingBase()),
      autonomyCriterionPass:
        (await controller.bootstrapper()) === ethers.ZeroAddress
        && (await controller.halted())
        && (await controller.completedCycles()) === 20n
        && totalKeeperProfitAfterGas > 0n,
      rows
    };

    fs.mkdirSync(path.join(process.cwd(), "reports"), { recursive: true });
    fs.writeFileSync(
      path.join(process.cwd(), "reports", "qt_autonomy_20_cycles.json"),
      JSON.stringify(result, null, 2)
    );
    console.log(`AUTONOMY_RESULT ${JSON.stringify(result)}`);
  });
});
