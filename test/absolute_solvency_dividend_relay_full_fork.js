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

async function expectRevert(promise) {
  await assert.rejects(promise.then((tx) => tx.wait()));
}

describe("Full QE/QT solvency, WPOL dividend and Ethereum relay integration", function () {
  this.timeout(900000);

  it("runs the complete system in one Polygon-fork test", async function () {
    const signers = await ethers.getSigners();
    const externalHolder = signers[5];
    const ethereumOwner = signers[6];
    const funder = signers[7];
    const keeperA = signers[8];
    const keeperB = signers[9];

    assert.notEqual(await ethers.provider.getCode(WPOL), "0x", "WPOL missing: not a Polygon fork");
    const wpol = new ethers.Contract(WPOL, WPOL_ABI, funder);
    await (await wpol.deposit({ value: E("46") })).wait();

    const MockAcross = await ethers.getContractFactory("MockAcrossSpokePoolV3", funder);
    const mockAcross = await MockAcross.deploy(ethereumOwner.address);
    await mockAcross.waitForDeployment();

    const Relay = await ethers.getContractFactory("AcrossMainnetDividendRelay", funder);
    const relay = await Relay.deploy(
      WPOL,
      await mockAcross.getAddress(),
      ethereumOwner.address,
      WPOL,
      100
    );
    await relay.waitForDeployment();

    const Controller = await ethers.getContractFactory("AbsoluteSolvencyDividendQTController", funder);
    const controller = await Controller.deploy(
      WPOL,
      await relay.getAddress(),
      5,
      { gasLimit: 29_000_000 }
    );
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
    assert.equal(await controller.dividendRecipient(), await relay.getAddress());
    assert.equal(await relay.ethereumRecipient(), ethereumOwner.address);
    assert.equal(await relay.ETHEREUM_MAINNET_CHAIN_ID(), 1n);
    assert.equal(await relay.maxRelayFeeBps(), 100n);
    assert.equal(await controller.protocolAssets(), E("43"));
    assert.equal(await controller.liabilitiesAtPar(), E("100"));
    assert.equal(await controller.reserveCoverageBps(), 4300n);
    assert.equal(await controller.equityAtPar(), -E("57"));

    const supplyInitial = await syn.totalSupply();
    const assetsInitial = await controller.protocolAssets();
    const lenderInitial = await wpol.balanceOf(await lender.getAddress());
    const keeperAInitial = await wpol.balanceOf(keeperA.address);
    const keeperBInitial = await wpol.balanceOf(keeperB.address);
    const ownerInitial = await wpol.balanceOf(ethereumOwner.address);

    const rows = [];
    let prepareGas = 0n;
    let executeGas = 0n;

    for (let cycle = 1; cycle <= MAX_CYCLES && !(await controller.halted()); cycle++) {
      const preparer = cycle % 2 === 1 ? keeperA : keeperB;
      const executor = cycle % 2 === 1 ? keeperB : keeperA;
      const supplyBefore = await syn.totalSupply();

      const prepareTx = await controller.connect(preparer).step({ gasLimit: TX_GAS_LIMIT });
      const prepareReceipt = await prepareTx.wait();
      assert.equal(await controller.phase(), 2n, `cycle ${cycle}: prepare phase failed`);
      await mine(2);

      const executeTx = await controller.connect(executor).step({ gasLimit: TX_GAS_LIMIT });
      const executeReceipt = await executeTx.wait();
      const supplyAfter = await syn.totalSupply();

      assert.equal(supplyBefore - supplyAfter, E("2"), `cycle ${cycle}: burn failed`);
      prepareGas += prepareReceipt.gasUsed;
      executeGas += executeReceipt.gasUsed;

      rows.push({
        cycle,
        synSupply: n(supplyAfter),
        totalBurned: n(supplyInitial - supplyAfter),
        protocolAssetsWPOL: n(await controller.protocolAssets()),
        liabilitiesWPOLAtPar: n(await controller.liabilitiesAtPar()),
        equityWPOLAtPar: n(await controller.equityAtPar()),
        coveragePercent: Number(await controller.reserveCoverageBps()) / 100,
        relayEscrowWPOL: n(await relay.pendingDividendWPOL()),
        prepareGasUsed: Number(prepareReceipt.gasUsed),
        executeGasUsed: Number(executeReceipt.gasUsed),
        halted: await controller.halted()
      });
    }

    const cyclesCompleted = Number(await controller.completedCycles());
    const supplyFinal = await syn.totalSupply();
    const assetsFinal = await controller.protocolAssets();
    const liabilitiesFinal = await controller.liabilitiesAtPar();
    const equityFinal = await controller.equityAtPar();
    const coverageFinal = await controller.reserveCoverageBps();
    const dividendEscrow = await relay.pendingDividendWPOL();
    const keeperRewards =
      (await wpol.balanceOf(keeperA.address)) - keeperAInitial
      + (await wpol.balanceOf(keeperB.address)) - keeperBInitial;
    const totalGasCost = (prepareGas + executeGas) * GAS_PRICE;
    const keeperProfitAfterGas = keeperRewards - totalGasCost;

    assert.equal(cyclesCompleted, 36);
    assert.equal(await controller.halted(), true);
    assert.equal(await controller.solventHalt(), true);
    assert.equal(await controller.phase(), 3n);
    assert.equal(await controller.totalBurned(), E("72"));
    assert.equal(await demand.totalBurned(), E("72"));
    assert.equal(supplyFinal, E("28"));
    assert.equal(assetsFinal, E("28.28"));
    assert.equal(liabilitiesFinal, E("28"));
    assert.equal(equityFinal, E("0.28"));
    assert.equal(coverageFinal, 10100n);
    assert.equal(dividendEscrow, E("1.013"));
    assert.equal(await controller.totalDividends(), E("1.013"));
    assert.equal(await syn.balanceOf(await auction.getAddress()), 0n);
    assert.equal(await syn.balanceOf(externalHolder.address), E("28"));
    assert.equal((await wpol.balanceOf(await lender.getAddress())) - lenderInitial, E("0.027"));
    assert.equal(keeperRewards, E("13.68"));
    assert.ok(keeperProfitAfterGas > 0n, "keepers are unprofitable after gas");

    const forkBlock = await ethers.provider.getBlock("latest");
    const quoteTimestamp = Number(forkBlock.timestamp);
    const fillDeadline = quoteTimestamp + 3600;

    // Fee-limit protection: 1.01% loss must fail when maximum fee is 1.00%.
    await expectRevert(
      relay.connect(keeperA).relayPending(
        E("1.0027687"),
        ethers.ZeroAddress,
        quoteTimestamp,
        fillDeadline,
        0,
        { gasLimit: TX_GAS_LIMIT }
      )
    );
    assert.equal(await relay.pendingDividendWPOL(), E("1.013"));
    assert.equal(await mockAcross.deposits(), 0n);

    // Stale quote and invalid deadline protections.
    await expectRevert(
      relay.connect(keeperA).relayPending(
        E("1.00287"),
        ethers.ZeroAddress,
        quoteTimestamp - 601,
        fillDeadline,
        0,
        { gasLimit: TX_GAS_LIMIT }
      )
    );
    await expectRevert(
      relay.connect(keeperA).relayPending(
        E("1.00287"),
        ethers.ZeroAddress,
        quoteTimestamp,
        quoteTimestamp + 60,
        0,
        { gasLimit: TX_GAS_LIMIT }
      )
    );

    const relayTx = await relay.connect(keeperB).relayPending(
      E("1.00287"),
      ethers.ZeroAddress,
      quoteTimestamp,
      fillDeadline,
      0,
      { gasLimit: TX_GAS_LIMIT }
    );
    const relayReceipt = await relayTx.wait();

    const ownerFinal = await wpol.balanceOf(ethereumOwner.address);
    const record = await mockAcross.lastDeposit();

    assert.equal(await relay.pendingDividendWPOL(), 0n);
    assert.equal(await relay.relayNonce(), 1n);
    assert.notEqual(await relay.lastRelayId(), ethers.ZeroHash);
    assert.equal(await relay.totalRelayedWPOL(), E("1.013"));
    assert.equal(await mockAcross.deposits(), 1n);
    assert.equal(await mockAcross.totalInput(), E("1.013"));
    assert.equal(await mockAcross.totalOutput(), E("1.00287"));
    assert.equal(ownerFinal - ownerInitial, E("1.00287"));
    assert.equal(await wpol.balanceOf(await mockAcross.getAddress()), E("0.01013"));
    assert.equal(record.recipient, ethereumOwner.address);
    assert.equal(record.inputToken, WPOL);
    assert.equal(record.outputToken, WPOL);
    assert.equal(record.destinationChainId, 1n);
    assert.equal(record.inputAmount, E("1.013"));
    assert.equal(record.outputAmount, E("1.00287"));

    // Full-balance relay prevents double spending; a second call has no funds.
    await expectRevert(
      relay.connect(keeperA).relayPending(
        E("1"),
        ethers.ZeroAddress,
        quoteTimestamp,
        fillDeadline,
        0,
        { gasLimit: TX_GAS_LIMIT }
      )
    );
    assert.equal(await mockAcross.deposits(), 1n);

    const result = {
      scenario: "full_qe_qt_solvency_dividend_across_relay",
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
      dividendGeneratedWPOL: n(dividendEscrow),
      dividendEscrowedInRelay: dividendEscrow === E("1.013"),
      ethereumDestinationChainId: Number(record.destinationChainId),
      ethereumRecipient: record.recipient,
      relayInputWPOL: n(record.inputAmount),
      relayOutputWPOL: n(record.outputAmount),
      relayFeeWPOL: n(record.inputAmount - record.outputAmount),
      relayFeePercent: Number((record.inputAmount - record.outputAmount) * 10000n / record.inputAmount) / 100,
      relayNonce: Number(await relay.relayNonce()),
      relayGasUsed: Number(relayReceipt.gasUsed),
      ethereumOwnerReceivedWPOL: n(ownerFinal - ownerInitial),
      feeLimitProtectionPass: true,
      staleQuoteProtectionPass: true,
      invalidDeadlineProtectionPass: true,
      doubleSpendProtectionPass: (await mockAcross.deposits()) === 1n,
      totalKeeperRewardsWPOL: n(keeperRewards),
      totalRecoveryGasCostPOLAt274Gwei: n(totalGasCost),
      keeperProfitAfterRecoveryGasWPOL: n(keeperProfitAfterGas),
      keeperCriterionPass: keeperProfitAfterGas > 0n,
      fullIntegrationPass:
        (await controller.solventHalt())
        && coverageFinal === 10100n
        && (ownerFinal - ownerInitial) === E("1.00287")
        && (await mockAcross.deposits()) === 1n,
      rows
    };

    fs.mkdirSync(path.join(process.cwd(), "reports"), { recursive: true });
    fs.writeFileSync(
      path.join(process.cwd(), "reports", "full_qe_qt_solvency_dividend_relay.json"),
      JSON.stringify(result, null, 2)
    );
    console.log(`FULL_SYSTEM_RESULT ${JSON.stringify(result)}`);
  });
});
