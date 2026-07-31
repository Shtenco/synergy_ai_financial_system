const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { ethers } = require("hardhat");

const WPOL = "0x0d500B1d8E8eF31E21C99d1Db9A6444d3ADf1270";
const GAS_PRICE = 274_000_000_000n;
const E = ethers.parseEther;
const CYCLES = 1000;
const WPOL_ABI = [
  "function deposit() payable",
  "function approve(address,uint256) returns(bool)",
  "function balanceOf(address) view returns(uint256)"
];

function decimal(value) {
  return Number(ethers.formatEther(value));
}

async function expectRevert(promise) {
  await assert.rejects(promise.then((tx) => tx.wait()));
}

describe("QE/QT V2 renewable tender/refill Polygon fork", function () {
  this.timeout(1_800_000);

  it("burns all initial SYN and completes 1000 fully-backed QE/QT cycles", async function () {
    const [deployer, externalHolder, buyer, keeperA, keeperB, dividendRecipient, feeRecipient] =
      await ethers.getSigners();

    assert.notEqual(await ethers.provider.getCode(WPOL), "0x", "real Polygon WPOL is missing");

    const wpol = new ethers.Contract(WPOL, WPOL_ABI, deployer);
    const wpolBuyer = wpol.connect(buyer);

    await (await wpol.deposit({ value: E("43") })).wait();
    await (await wpolBuyer.deposit({ value: E(String(CYCLES)) })).wait();

    const Controller = await ethers.getContractFactory("BackedQETenderQTControllerV2", deployer);
    const controller = await Controller.deploy(WPOL, dividendRecipient.address, feeRecipient.address);
    await controller.waitForDeployment();
    const controllerAddress = await controller.getAddress();

    await (await wpol.approve(controllerAddress, E("43"))).wait();
    await (await controller.bootstrap(externalHolder.address)).wait();

    const syn = await ethers.getContractAt("ForkSynQTToken", await controller.syn());

    assert.equal(await controller.bootstrapper(), ethers.ZeroAddress);
    assert.equal(await controller.reserveWPOL(), E("43"));
    assert.equal(await syn.totalSupply(), E("100"));
    assert.equal(await syn.balanceOf(controllerAddress), E("72"));
    assert.equal(await syn.balanceOf(externalHolder.address), E("28"));

    // No external wallet can mint directly; the token owner is the controller.
    await expectRevert(syn.connect(buyer).mint(buyer.address, E("1")));

    const keeperAStart = await wpol.balanceOf(keeperA.address);
    const keeperBStart = await wpol.balanceOf(keeperB.address);
    const holderStart = await wpol.balanceOf(externalHolder.address);
    const dividendStart = await wpol.balanceOf(dividendRecipient.address);
    const feeStart = await wpol.balanceOf(feeRecipient.address);

    let keeperGasUsed = 0n;

    // Burn all 72 protocol-owned SYN in one permissionless on-chain operation.
    const protocolBurnTx = await controller.connect(keeperA).burnProtocolInventory(E("72"));
    keeperGasUsed += (await protocolBurnTx.wait()).gasUsed;
    assert.equal(await syn.totalSupply(), E("28"));
    assert.equal(await syn.balanceOf(controllerAddress), 0n);

    // The remaining 28 SYN are not seized: the holder explicitly approves the tender.
    await (await syn.connect(externalHolder).approve(controllerAddress, ethers.MaxUint256)).wait();
    const holderTenderTx = await controller
      .connect(keeperB)
      .tenderExternalAndBurn(externalHolder.address, E("28"));
    keeperGasUsed += (await holderTenderTx.wait()).gasUsed;

    assert.equal(await syn.totalSupply(), 0n);
    assert.equal(await syn.balanceOf(externalHolder.address), 0n);
    assert.equal(await controller.initialRecoveryComplete(), true);
    assert.equal(await controller.totalProtocolInventoryBurned(), E("72"));
    assert.equal(await controller.totalExternalTenderBurned(), E("28"));
    assert.equal((await wpol.balanceOf(externalHolder.address)) - holderStart, E("21"));
    assert.equal(await controller.reserveWPOL(), E("2.9625"));

    // Zero-liability surplus is a real WPOL dividend; one WPOL stays operational.
    await (await controller.connect(keeperA).payExcessDividend()).wait();
    assert.equal(await controller.reserveWPOL(), E("1"));
    assert.equal((await wpol.balanceOf(dividendRecipient.address)) - dividendStart, E("1.9625"));

    await (await wpolBuyer.approve(controllerAddress, ethers.MaxUint256)).wait();
    await (await syn.connect(buyer).approve(controllerAddress, ethers.MaxUint256)).wait();

    const rows = [];
    for (let cycle = 1; cycle <= CYCLES; cycle++) {
      await (await controller.connect(buyer).buyBackedSYN(E("1"))).wait();

      assert.equal(await syn.totalSupply(), E("1"), `cycle ${cycle}: backed mint failed`);
      assert.equal(await controller.liabilitiesAtPar(), E("1"));

      // A dividend cannot be paid while the just-issued liability exists.
      if (cycle === 1) {
        await expectRevert(controller.connect(keeperA).payExcessDividend());
      }

      const keeper = cycle % 2 === 1 ? keeperA : keeperB;
      const tenderTx = await controller.connect(keeper).tenderRefillAndBurn(buyer.address, E("1"));
      keeperGasUsed += (await tenderTx.wait()).gasUsed;

      assert.equal(await syn.totalSupply(), 0n, `cycle ${cycle}: QT burn failed`);
      assert.equal(await controller.liabilitiesAtPar(), 0n);
      assert.ok((await controller.reserveWPOL()) >= E("1"), `cycle ${cycle}: reserve floor broken`);

      if (cycle === 1 || cycle % 10 === 0 || cycle === CYCLES) {
        rows.push({
          cycle,
          reserveWPOL: decimal(await controller.reserveWPOL()),
          synSupply: decimal(await syn.totalSupply()),
          liabilitiesWPOLAtPar: decimal(await controller.liabilitiesAtPar()),
          equityWPOLAtPar: decimal(await controller.equityAtPar()),
          cumulativeQEMintedSYN: decimal(await controller.totalQEMinted()),
          cumulativeQTburnedSYN: decimal(await controller.totalRefillQTburned()),
          cumulativeKeeperRewardsWPOL: decimal(await controller.totalKeeperRewards()),
          cumulativeSettlementFeesWPOL: decimal(await controller.totalSettlementFees())
        });
      }
    }

    const reserveBeforeFinalDividend = await controller.reserveWPOL();
    assert.equal(reserveBeforeFinalDividend, E("60.625"));
    assert.equal(await controller.totalQEMinted(), E(String(CYCLES)));
    assert.equal(await controller.totalRefillQTburned(), E(String(CYCLES)));
    assert.equal(await syn.totalSupply(), 0n);
    assert.equal(await controller.liabilitiesAtPar(), 0n);
    assert.equal(await controller.equityAtPar(), E("60.625"));

    await (await controller.connect(keeperB).payExcessDividend()).wait();

    const finalReserve = await controller.reserveWPOL();
    const totalDividends = await controller.totalDividends();
    const totalKeeperRewards = await controller.totalKeeperRewards();
    const totalSettlementFees = await controller.totalSettlementFees();
    const keeperRewardsReceived =
      (await wpol.balanceOf(keeperA.address)) - keeperAStart
      + (await wpol.balanceOf(keeperB.address)) - keeperBStart;
    const keeperGasCost = keeperGasUsed * GAS_PRICE;
    const keeperNet = keeperRewardsReceived - keeperGasCost;

    assert.equal(finalReserve, E("1"));
    assert.equal(totalDividends, E("61.5875"));
    assert.equal(
      (await wpol.balanceOf(dividendRecipient.address)) - dividendStart,
      E("61.5875")
    );
    assert.equal(totalKeeperRewards, E("209"));
    assert.equal(keeperRewardsReceived, E("209"));
    assert.equal(totalSettlementFees, E("0.4125"));
    assert.equal((await wpol.balanceOf(feeRecipient.address)) - feeStart, E("0.4125"));
    assert.ok(keeperNet > 0n, "keepers are not profitable at 274 gwei");
    assert.equal(await controller.totalQEMinted(), await controller.totalRefillQTburned());
    assert.equal(await syn.totalSupply(), 0n);

    const result = {
      scenario: "qe_qt_v2_polygon_fork_renewable_cycle",
      realPolygonWPOL: true,
      forkBlock: await ethers.provider.getBlockNumber(),
      initialSupplySYN: 100,
      protocolInventoryBurnedSYN: 72,
      externalTenderBurnedSYN: 28,
      externalHolderConsentRequired: true,
      initialSupplyAfterRecoverySYN: 0,
      reserveAfterInitialFullBurnWPOL: 2.9625,
      initialDividendWPOL: 1.9625,
      renewableCycles: CYCLES,
      cumulativeBackedQEMintedSYN: decimal(await controller.totalQEMinted()),
      cumulativeRefillQTburnedSYN: decimal(await controller.totalRefillQTburned()),
      inventoryTurnoverVsInitialSupply: decimal(await controller.totalQEMinted()) / 100,
      finalSupplySYN: decimal(await syn.totalSupply()),
      reserveBeforeFinalDividendWPOL: decimal(reserveBeforeFinalDividend),
      finalReserveWPOL: decimal(finalReserve),
      totalDividendsWPOL: decimal(totalDividends),
      totalKeeperRewardsWPOL: decimal(totalKeeperRewards),
      totalSettlementFeesWPOL: decimal(totalSettlementFees),
      keeperGasUsed: Number(keeperGasUsed),
      keeperGasCostPOLAt274Gwei: decimal(keeperGasCost),
      keeperNetWPOLAt274Gwei: decimal(keeperNet),
      keeperProfitable: keeperNet > 0n,
      liabilityControlledEveryCompletedCycle: true,
      reserveFloorPreserved: finalReserve === E("1"),
      dividendPossible: totalDividends > 0n,
      noUnbackedPublicMint: true,
      fullV2Pass: true,
      rows
    };

    fs.mkdirSync(path.join(process.cwd(), "reports"), { recursive: true });
    fs.writeFileSync(
      path.join(process.cwd(), "reports", "qe_qt_v2_polygon_fork_renewable_cycle.json"),
      JSON.stringify(result, null, 2)
    );
    fs.writeFileSync(
      path.join(process.cwd(), "reports", "qe_qt_v2_polygon_fork_renewable_cycle.csv"),
      [
        "cycle,reserveWPOL,synSupply,liabilitiesWPOLAtPar,equityWPOLAtPar,cumulativeQEMintedSYN,cumulativeQTburnedSYN,cumulativeKeeperRewardsWPOL,cumulativeSettlementFeesWPOL",
        ...rows.map((r) => [
          r.cycle,
          r.reserveWPOL,
          r.synSupply,
          r.liabilitiesWPOLAtPar,
          r.equityWPOLAtPar,
          r.cumulativeQEMintedSYN,
          r.cumulativeQTburnedSYN,
          r.cumulativeKeeperRewardsWPOL,
          r.cumulativeSettlementFeesWPOL
        ].join(","))
      ].join("\n")
    );

    console.log(`QE_QT_V2_RESULT ${JSON.stringify(result)}`);
  });
});
