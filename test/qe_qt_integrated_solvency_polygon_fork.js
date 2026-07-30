const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { ethers } = require("hardhat");

const WPOL = "0x0d500B1d8E8eF31E21C99d1Db9A6444d3ADf1270";
const E = ethers.parseEther;
const CYCLES = 100;
const WPOL_ABI = [
  "function deposit() payable",
  "function approve(address,uint256) returns(bool)",
  "function transfer(address,uint256) returns(bool)",
  "function balanceOf(address) view returns(uint256)"
];
const source = (label, i = 0) => ethers.keccak256(ethers.toUtf8Bytes(`${label}:${i}`));

describe("Consolidated QE/QT Polygon fork integration", function () {
  this.timeout(1200000);

  it("uses real WPOL balances for external issuance, QT redemption and bounded dividend", async function () {
    const [admin, keeper, feeVault, bridge, insurance, yieldVault, buyer, costRecipient, dividendRecipient] =
      await ethers.getSigners();
    assert.notEqual(await ethers.provider.getCode(WPOL), "0x");

    const wpolAdmin = new ethers.Contract(WPOL, WPOL_ABI, admin);
    const wpolBuyer = wpolAdmin.connect(buyer);
    await (await wpolAdmin.deposit({ value: E("75") })).wait();
    await (await wpolBuyer.deposit({ value: E("110") })).wait();

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
      WPOL,
      await syn.getAddress(),
      await registry.getAddress(),
      await solvency.getAddress(),
      await ledger.getAddress(),
      E("1"),
      E("100"),
      0
    );
    await mm.waitForDeployment();
    const QT = await ethers.getContractFactory("ExternalLiabilityQT", admin);
    const qt = await QT.deploy(
      admin.address,
      WPOL,
      await syn.getAddress(),
      await registry.getAddress(),
      await solvency.getAddress(),
      await ledger.getAddress(),
      E("1"),
      E("0.75")
    );
    await qt.waitForDeployment();
    const Dividend = await ethers.getContractFactory("ExternalProfitDividendVault", admin);
    const dividend = await Dividend.deploy(
      admin.address,
      WPOL,
      await registry.getAddress(),
      await solvency.getAddress(),
      await ledger.getAddress(),
      E("1"),
      5000
    );
    await dividend.waitForDeployment();

    await (
      await registry.setSystemAddresses(
        [
          await ledger.getAddress(),
          await solvency.getAddress(),
          await mm.getAddress(),
          await qt.getAddress(),
          await dividend.getAddress(),
          keeper.address,
          feeVault.address,
          bridge.address,
          insurance.address,
          yieldVault.address
        ],
        true
      )
    ).wait();
    for (const module of [mm, qt, dividend]) {
      await (await ledger.setRecorder(await module.getAddress(), true)).wait();
    }

    await (
      await solvency.updateAssets({
        liquidReserves: E("75"),
        stableLpNav: E("100"),
        volatileLpNav: 0,
        bridgeCapital: E("100"),
        insuranceAssets: E("100"),
        yieldPositions: E("100"),
        gasReserve: E("20"),
        unrealizedInventoryValue: 0
      })
    ).wait();
    await (
      await solvency.updateOtherLiabilities({
        externalSynrClaims: 0,
        vestedMevClaims: 0,
        bridgeObligations: 0,
        keeperReimbursementsAccrued: 0,
        externalDebt: 0,
        expectedThirtyDayOperatingCosts: E("10"),
        modeledRedemptionShock: 0
      })
    ).wait();
    await (
      await solvency.updateCoverageInputs(E("75"), E("50"), E("700"), E("1000"), E("100"), 0, 1)
    ).wait();
    await (await solvency.setBuffers(E("5"), E("5"), E("5"), E("0.0001"))).wait();
    await (await solvency.updateEnvironment(true, true, true)).wait();
    assert.equal(await solvency.mode(), 2n);

    await (await syn.mint(await mm.getAddress(), E(String(CYCLES)))).wait();
    await (
      await ledger.recordInventoryIncrease(
        source("fork-inventory"),
        await syn.getAddress(),
        E(String(CYCLES)),
        await mm.getAddress()
      )
    ).wait();
    await (await wpolAdmin.transfer(await qt.getAddress(), E("75"))).wait();
    await (await wpolBuyer.approve(await mm.getAddress(), ethers.MaxUint256)).wait();
    await (await syn.connect(buyer).approve(await qt.getAddress(), ethers.MaxUint256)).wait();

    let gasUsed = 0n;
    for (let i = 0; i < CYCLES; i++) {
      const sell = await mm.sellToExternalBuyer(
        buyer.address,
        E("1"),
        E("1.1"),
        E("0.01"),
        costRecipient.address,
        source("fork-capital", i),
        source("fork-spread", i),
        source("fork-inventory-out", i),
        source("fork-cost", i)
      );
      gasUsed += (await sell.wait()).gasUsed;
      const redeem = await qt.externalTenderAndBurn(
        buyer.address,
        E("1"),
        0,
        ethers.ZeroAddress,
        source("fork-redemption", i),
        source("fork-unused", i)
      );
      gasUsed += (await redeem.wait()).gasUsed;
      assert.equal(await ledger.externalLiabilities(), 0n);
    }

    assert.equal(await syn.totalSupply(), 0n);
    assert.equal(await ledger.protocolInventory(), 0n);
    assert.equal(await ledger.realizedExternalPnL(), E("34"));
    assert.equal(await wpolAdmin.balanceOf(await mm.getAddress()), E("109"));
    assert.equal(await wpolAdmin.balanceOf(await qt.getAddress()), 0n);

    await (
      await mm.transferReserveInternal(
        await dividend.getAddress(),
        E("34"),
        source("fork-profit-routing")
      )
    ).wait();
    await (
      await solvency.updateAssets({
        liquidReserves: E("109"),
        stableLpNav: E("100"),
        volatileLpNav: 0,
        bridgeCapital: E("100"),
        insuranceAssets: E("100"),
        yieldPositions: E("100"),
        gasReserve: E("20"),
        unrealizedInventoryValue: 0
      })
    ).wait();
    await (await solvency.updateEnvironment(true, true, true)).wait();
    await (
      await dividend.payDividend(dividendRecipient.address, E("17"), source("fork-dividend"))
    ).wait();

    assert.equal(await wpolAdmin.balanceOf(dividendRecipient.address), E("17"));
    assert.equal(await ledger.totalDividends(), E("17"));
    assert.equal(await ledger.consolidatedNavDelta(), E("17"));

    const result = {
      forkBlock: await ethers.provider.getBlockNumber(),
      realPolygonWPOL: true,
      cycles: CYCLES,
      externalLiabilitiesFinal: 0,
      synSupplyFinal: 0,
      realizedExternalPnLWPOL: 34,
      dividendWPOL: 17,
      gasUsed: Number(gasUsed),
      economicSolvencyBps: Number(await solvency.economicSolvencyBps()),
      liquidityCoverageBps: Number(await solvency.liquidityCoverageBps()),
      gasCoverageBps: Number(await solvency.gasCoverageBps()),
      pass: true,
      limitation: "Real WPOL and token balances; SYN is local and no real QuickSwap/Aave swap is executed in this test."
    };
    fs.mkdirSync(path.join(process.cwd(), "reports"), { recursive: true });
    fs.writeFileSync(
      path.join(process.cwd(), "reports", "qe_qt_integrated_solvency_polygon_fork.json"),
      JSON.stringify(result, null, 2)
    );
    console.log(`CONSOLIDATED_FORK_RESULT ${JSON.stringify(result)}`);
  });
});
