const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { ethers, network } = require("hardhat");

const WPOL = "0x0d500B1d8E8eF31E21C99d1Db9A6444d3ADf1270";
const GAS_PRICE = 274_000_000_000n;
const FLASH_PREMIUM_BPS = 5;
const GAS_LIMIT = 8_000_000;
const E = ethers.parseEther;
const RESULTS = [];

const WPOL_ABI = [
  "function deposit() payable",
  "function transfer(address,uint256) returns(bool)",
  "function balanceOf(address) view returns(uint256)"
];

function record(row) {
  RESULTS.push(row);
  console.log(`QT_RESULT ${JSON.stringify(row)}`);
}

async function mine(count) {
  for (let i = 0; i < count; i++) {
    await network.provider.send("evm_mine");
  }
}

async function protocolWpol(f) {
  return (
    (await f.wpol.balanceOf(f.treasury.address))
    + (await f.wpol.balanceOf(f.bridge.address))
    + (await f.wpol.balanceOf(await f.demand.getAddress()))
    + (await f.wpol.balanceOf(await f.auction.getAddress()))
  );
}

async function deployQtFixture({ seedInventory = true } = {}) {
  const [gov, treasury, bridge] = await ethers.getSigners();
  assert.notEqual(await ethers.provider.getCode(WPOL), "0x", "WPOL missing: not a Polygon fork");

  const wpol = new ethers.Contract(WPOL, WPOL_ABI, gov);
  await (await wpol.deposit({ value: E("12") })).wait();
  await (await wpol.transfer(treasury.address, E("1"))).wait();
  await (await wpol.transfer(bridge.address, E("2"))).wait();

  const Token = await ethers.getContractFactory("ForkSynQTToken");
  const syn = await Token.deploy();
  await syn.waitForDeployment();
  await (await syn.mint(gov.address, E("10"))).wait();

  const Demand = await ethers.getContractFactory("L1BuybackBurnEscrowQT");
  const demand = await Demand.deploy(await syn.getAddress(), WPOL, E("1"), E("4"));
  await demand.waitForDeployment();
  await (await wpol.transfer(await demand.getAddress(), E("4"))).wait();

  const Auction = await ethers.getContractFactory("SynergyQTInventoryAuction");
  const auction = await Auction.deploy(
    await syn.getAddress(),
    WPOL,
    await demand.getAddress(),
    gov.address,
    treasury.address,
    bridge.address
  );
  await auction.waitForDeployment();

  if (seedInventory) {
    await (await syn.transfer(await auction.getAddress(), E("2"))).wait();
  }

  const Lender = await ethers.getContractFactory("ForkFlashLender");
  const lender = await Lender.deploy(WPOL, FLASH_PREMIUM_BPS);
  await lender.waitForDeployment();
  await (await wpol.transfer(await lender.getAddress(), E("3"))).wait();

  const Solver = await ethers.getContractFactory("AaveFlashQESolverV2");
  const solver = await Solver.deploy(
    await lender.getAddress(),
    WPOL,
    await syn.getAddress(),
    await demand.getAddress(),
    await auction.getAddress()
  );
  await solver.waitForDeployment();

  return { gov, treasury, bridge, wpol, syn, demand, auction, lender, solver };
}

describe("Synergy QT buyback: Polygon fork / burn existing SYN debt", function () {
  this.timeout(240000);

  after(function () {
    fs.mkdirSync(path.join(process.cwd(), "reports"), { recursive: true });
    fs.writeFileSync(
      path.join(process.cwd(), "reports", "synergy_qt_buyback_fork_results.json"),
      JSON.stringify({
        generatedAt: new Date().toISOString(),
        results: RESULTS,
        qt_buyback: RESULTS.find((row) => row.scenario === "qt_buyback") || null
      }, null, 2)
    );
  });

  it("uses funded buyback demand to burn debt and improves protocol equity", async function () {
    const f = await deployQtFixture();

    const supplyBefore = await f.syn.totalSupply();
    const protocolWpolBefore = await protocolWpol(f);
    const treasuryBefore = await f.wpol.balanceOf(f.treasury.address);
    const bridgeBefore = await f.wpol.balanceOf(f.bridge.address);
    const demandBefore = await f.wpol.balanceOf(await f.demand.getAddress());

    assert.equal(supplyBefore, E("10"));
    assert.equal(protocolWpolBefore, E("7"));
    assert.equal(await f.syn.balanceOf(await f.auction.getAddress()), E("2"));

    const latest = await ethers.provider.getBlock("latest");
    const openTx = await f.auction.openProportionalWindow(
      5000,
      2500,
      5000,
      5000,
      E("2"),
      latest.timestamp + 3600
    );
    await openTx.wait();

    const window = await f.auction.windows(0);
    assert.equal(window.baseAvailable, E("2"));
    assert.equal(window.auctionPriceX18, E("0.75"));
    assert.equal(await f.syn.totalSupply(), supplyBefore, "opening QT window minted SYN");

    const baseAmount = E("2");
    const maxPayment = E("1.5");
    const deadline = BigInt(latest.timestamp + 3500);
    const salt = ethers.id("synergy-qt-buyback-burn");
    const solverAddress = await f.solver.getAddress();
    const digest = ethers.keccak256(ethers.AbiCoder.defaultAbiCoder().encode(
      ["address", "uint256", "uint256", "uint256", "bytes32", "uint64"],
      [solverAddress, 0, baseAmount, maxPayment, salt, deadline]
    ));

    await (await f.solver.commitClosed(digest)).wait();
    await mine(2);

    const solverBefore = await f.wpol.balanceOf(solverAddress);
    const tx = await f.solver.runClosed(
      E("1.5"),
      0,
      baseAmount,
      maxPayment,
      salt,
      deadline,
      0,
      { gasLimit: GAS_LIMIT }
    );
    const receipt = await tx.wait();

    const supplyAfter = await f.syn.totalSupply();
    const protocolWpolAfter = await protocolWpol(f);
    const treasuryAfter = await f.wpol.balanceOf(f.treasury.address);
    const bridgeAfter = await f.wpol.balanceOf(f.bridge.address);
    const demandAfter = await f.wpol.balanceOf(await f.demand.getAddress());
    const solverAfter = await f.wpol.balanceOf(solverAddress);

    const debtBurned = supplyBefore - supplyAfter;
    const protocolReserveDelta = protocolWpolAfter - protocolWpolBefore;
    const protocolReserveSpend = protocolWpolBefore - protocolWpolAfter;
    const protocolEquityGain = debtBurned - protocolReserveSpend;
    const solverProfit = solverAfter - solverBefore;
    const flashFee = await f.solver.lastPremium();
    const gasCost = receipt.gasUsed * GAS_PRICE;
    const solverProfitAfterGas = solverProfit - gasCost;

    assert.equal(debtBurned, E("2"), "QT did not burn two SYN");
    assert.equal(await f.demand.totalBurned(), E("2"));
    assert.equal(protocolReserveSpend, E("0.5"));
    assert.equal(treasuryAfter - treasuryBefore, E("0.75"));
    assert.equal(bridgeAfter - bridgeBefore, E("0.75"));
    assert.equal(demandBefore - demandAfter, E("2"));
    assert.equal(solverProfit, E("0.49925"));
    assert.equal(flashFee, E("0.00075"));
    assert.ok(protocolEquityGain > 0n, "QT failed to improve protocol equity");
    assert.ok(solverProfitAfterGas > 0n, "solver was not profitable after standardized gas");
    assert.equal(await f.syn.balanceOf(await f.auction.getAddress()), 0n);
    assert.equal(await f.syn.balanceOf(await f.demand.getAddress()), 0n);

    record({
      scenario: "qt_buyback",
      forkBlock: await ethers.provider.getBlockNumber(),
      realPolygonWPOL: true,
      newSynMintedDuringQt: 0,
      synSupplyBefore: Number(ethers.formatEther(supplyBefore)),
      synSupplyAfter: Number(ethers.formatEther(supplyAfter)),
      synDebtBurned: Number(ethers.formatEther(debtBurned)),
      protocolWpolBefore: Number(ethers.formatEther(protocolWpolBefore)),
      protocolWpolAfter: Number(ethers.formatEther(protocolWpolAfter)),
      protocolReserveDeltaWPOL: Number(ethers.formatEther(protocolReserveDelta)),
      protocolReserveSpendWPOL: Number(ethers.formatEther(protocolReserveSpend)),
      treasuryGainWPOL: Number(ethers.formatEther(treasuryAfter - treasuryBefore)),
      bridgeGainWPOL: Number(ethers.formatEther(bridgeAfter - bridgeBefore)),
      buybackEscrowSpendWPOL: Number(ethers.formatEther(demandBefore - demandAfter)),
      protocolEquityGainWPOLAtPar: Number(ethers.formatEther(protocolEquityGain)),
      protocolCriterionPass: protocolEquityGain > 0n,
      solverProfitWPOL: Number(ethers.formatEther(solverProfit)),
      flashFeeWPOL: Number(ethers.formatEther(flashFee)),
      gasUsed: Number(receipt.gasUsed),
      gasCostPOLAt274Gwei: Number(ethers.formatEther(gasCost)),
      solverProfitAfterGasWPOL: Number(ethers.formatEther(solverProfitAfterGas)),
      solverCriterionPass: solverProfitAfterGas > 0n
    });
  });

  it("cannot open a QT window without existing SYN inventory", async function () {
    const f = await deployQtFixture({ seedInventory: false });
    const latest = await ethers.provider.getBlock("latest");

    await assert.rejects(
      f.auction.openProportionalWindow(
        5000,
        2500,
        5000,
        5000,
        E("2"),
        latest.timestamp + 3600
      )
    );
  });
});
