"use strict";

const assert = require("node:assert/strict");
const crypto = require("node:crypto");
const fs = require("node:fs");
const path = require("node:path");
const { ethers } = require("hardhat");

const E = ethers.parseEther;
const PRINCIPAL = E("1000");
const FIXED_FEE = E("5");
const EXACT_MIN_GROSS = E("5.2685148");
const STRICT_NET_EDGE_BPS = 2.685148;

const evidence = {
  scenario: "synergy_v15_4_atomic_fixed_5_wpol_fee_10x",
  evidenceClass: "STRUCTURAL_ONLY_NOT_MARKET_EDGE",
  atomicRollbackOnTenthFailure: false,
  profitableTenCycleBatch: false,
  exactBoundaryPass: false,
  boundaryMinusOneWeiRevert: false,
  receiverSubsidyRejected: false
};

async function expectRevert(promise, message) {
  let reverted = false;
  try {
    const value = await promise;
    if (value && typeof value.wait === "function") await value.wait();
  } catch (_) {
    reverted = true;
  }
  assert.ok(reverted, message);
}

function sha256(file) {
  return crypto.createHash("sha256").update(fs.readFileSync(file)).digest("hex");
}

function writeReport() {
  const reports = path.join(process.cwd(), "reports");
  fs.mkdirSync(reports, { recursive: true });
  const contractPath = path.join(
    process.cwd(),
    "contracts/v15_4/AtomicFixedFeeFlashV154.sol"
  );
  const testPath = path.join(
    process.cwd(),
    "test/atomic_flashloan_5pol_10x_v15_4.js"
  );
  const requiredFlags = [
    "atomicRollbackOnTenthFailure",
    "profitableTenCycleBatch",
    "exactBoundaryPass",
    "boundaryMinusOneWeiRevert",
    "receiverSubsidyRejected"
  ];
  evidence.allAssertionsPassed = requiredFlags.every((name) => evidence[name] === true);
  evidence.contractSha256 = sha256(contractPath);
  evidence.testSha256 = sha256(testPath);
  fs.writeFileSync(
    path.join(reports, "v15_4_atomic_flashloan_5pol_10x.json"),
    JSON.stringify(evidence, null, 2)
  );
}

async function deploySystem() {
  const [operator, reinvestmentVault, retainedTreasury] = await ethers.getSigners();

  const Token = await ethers.getContractFactory("MockWPOLV154", operator);
  const wpol = await Token.deploy();
  await wpol.waitForDeployment();

  const Lender = await ethers.getContractFactory(
    "AtomicFixedFeeFlashLenderV154",
    operator
  );
  const lender = await Lender.deploy(await wpol.getAddress(), FIXED_FEE);
  await lender.waitForDeployment();

  const Route = await ethers.getContractFactory(
    "MockSequencedFlashRouteV154",
    operator
  );
  const route = await Route.deploy(await wpol.getAddress(), operator.address);
  await route.waitForDeployment();

  const Compound = await ethers.getContractFactory("AtomicFlashCompoundV154", operator);
  const compound = await Compound.deploy(
    await lender.getAddress(),
    reinvestmentVault.address,
    retainedTreasury.address,
    operator.address
  );
  await compound.waitForDeployment();

  await (await wpol.issueForTest(await lender.getAddress(), E("100000"))).wait();
  await (await wpol.issueForTest(await route.getAddress(), E("1000"))).wait();

  return {
    operator,
    reinvestmentVault,
    retainedTreasury,
    wpol,
    lender,
    route,
    compound
  };
}

describe("SYNERGY V15.4 atomic fixed-fee flashloan", function () {
  after(function () {
    writeReport();
  });

  it("reverts all ten cycles when the tenth falls below 2.685148 bps", async function () {
    const {
      reinvestmentVault,
      retainedTreasury,
      wpol,
      lender,
      route,
      compound
    } = await deploySystem();

    // First nine calls would yield 6 WPOL gross and 1 WPOL net after the fee.
    // The tenth yields only 5.2 gross, or 0.2 WPOL net = 2 bps on 1,000 WPOL.
    await (await route.configure(E("6"), E("5.2"), 9)).wait();

    const balancesBefore = {
      lender: await wpol.balanceOf(await lender.getAddress()),
      route: await wpol.balanceOf(await route.getAddress()),
      reinvestment: await wpol.balanceOf(reinvestmentVault.address),
      retained: await wpol.balanceOf(retainedTreasury.address)
    };

    await expectRevert(
      compound.runTenCycles(PRINCIPAL, await route.getAddress(), 0, "0x"),
      "the complete 10-cycle transaction must revert when cycle ten misses the strict edge"
    );

    assert.equal(await lender.completedLoans(), 0n);
    assert.equal(await lender.cumulativeFees(), 0n);
    assert.equal(await compound.completedCycles(), 0n);
    assert.equal(await compound.cumulativeNetProtocolProfit(), 0n);
    assert.equal(await compound.cumulativeReinvested(), 0n);
    assert.equal(await route.calls(), 0n, "route state from the first nine calls must also roll back");
    assert.equal(await wpol.balanceOf(await lender.getAddress()), balancesBefore.lender);
    assert.equal(await wpol.balanceOf(await route.getAddress()), balancesBefore.route);
    assert.equal(await wpol.balanceOf(reinvestmentVault.address), balancesBefore.reinvestment);
    assert.equal(await wpol.balanceOf(retainedTreasury.address), balancesBefore.retained);
    assert.equal(await wpol.balanceOf(await compound.getAddress()), 0n);

    evidence.atomicRollbackOnTenthFailure = true;
  });

  it("closes ten loans and compounds 80 percent when every cycle earns 6 WPOL gross", async function () {
    const {
      reinvestmentVault,
      retainedTreasury,
      wpol,
      lender,
      route,
      compound
    } = await deploySystem();

    await (await route.configure(E("6"), E("6"), 10)).wait();

    const lenderBefore = await wpol.balanceOf(await lender.getAddress());
    const routeBefore = await wpol.balanceOf(await route.getAddress());

    await (
      await compound.runTenCycles(PRINCIPAL, await route.getAddress(), E("6"), "0x")
    ).wait();

    const netPerCycle = E("1");
    const tenGross = E("60");
    const tenFees = E("50");
    const tenNet = E("10");
    const reinvested = E("8");
    const retained = E("2");
    const realizedNetEdgeBps =
      (Number(ethers.formatEther(netPerCycle)) /
        Number(ethers.formatEther(PRINCIPAL))) *
      10_000;

    assert.ok(realizedNetEdgeBps >= STRICT_NET_EDGE_BPS);
    assert.equal(await lender.completedLoans(), 10n);
    assert.equal(await lender.cumulativeFees(), tenFees);
    assert.equal(await compound.completedCycles(), 10n);
    assert.equal(await compound.cumulativeGrossRouteProfit(), tenGross);
    assert.equal(await compound.cumulativeFlashFees(), tenFees);
    assert.equal(await compound.cumulativeNetProtocolProfit(), tenNet);
    assert.equal(await compound.cumulativeReinvested(), reinvested);
    assert.equal(await compound.cumulativeRetained(), retained);
    assert.equal(await wpol.balanceOf(await lender.getAddress()), lenderBefore + tenFees);
    assert.equal(await wpol.balanceOf(await route.getAddress()), routeBefore - tenGross);
    assert.equal(await wpol.balanceOf(reinvestmentVault.address), reinvested);
    assert.equal(await wpol.balanceOf(retainedTreasury.address), retained);
    assert.equal(await wpol.balanceOf(await compound.getAddress()), 0n);
    assert.equal(await route.calls(), 10n);

    Object.assign(evidence, {
      profitableTenCycleBatch: true,
      principalWpolPerCycle: 1000,
      cycles: 10,
      fixedFlashFeeWpolPerCycle: 5,
      grossRouteProfitWpolPerCycle: 6,
      netProtocolProfitWpolPerCycle: 1,
      realizedNetEdgeBps,
      strictNetEdgeFloorBps: STRICT_NET_EDGE_BPS,
      cumulativeGrossRouteProfitWpol: 60,
      cumulativeFlashFeesWpol: 50,
      cumulativeNetProtocolProfitWpol: 10,
      reinvestmentShare: 0.8,
      reinvestedWpol: 8,
      retainedWpol: 2,
      lenderPrincipalRestoredEveryCycle: true,
      settlementResidueWpol: 0,
      interpretation:
        "The ten-cycle batch is profitable only because the structural route supplies 6 WPOL of external fixture profit per cycle. The test proves accounting and rollback, not a live Polygon opportunity."
    });
  });

  it("accepts the exact 2.685148 bps boundary and rejects one wei below it", async function () {
    {
      const { reinvestmentVault, retainedTreasury, wpol, lender, route, compound } =
        await deploySystem();
      await (await route.configure(EXACT_MIN_GROSS, EXACT_MIN_GROSS, 1)).wait();
      await (
        await compound.runCycle(
          PRINCIPAL,
          await route.getAddress(),
          EXACT_MIN_GROSS,
          "0x"
        )
      ).wait();

      const exactNet = E("0.2685148");
      assert.equal(await lender.completedLoans(), 1n);
      assert.equal(await compound.completedCycles(), 1n);
      assert.equal(await compound.cumulativeNetProtocolProfit(), exactNet);
      assert.equal(
        await wpol.balanceOf(reinvestmentVault.address),
        E("0.21481184")
      );
      assert.equal(
        await wpol.balanceOf(retainedTreasury.address),
        E("0.05370296")
      );
      assert.equal(await wpol.balanceOf(await compound.getAddress()), 0n);
      evidence.exactBoundaryPass = true;
    }

    {
      const { wpol, lender, route, compound } = await deploySystem();
      const belowBoundary = EXACT_MIN_GROSS - 1n;
      await (await route.configure(belowBoundary, belowBoundary, 1)).wait();
      const lenderBefore = await wpol.balanceOf(await lender.getAddress());
      const routeBefore = await wpol.balanceOf(await route.getAddress());

      await expectRevert(
        compound.runCycle(PRINCIPAL, await route.getAddress(), 0, "0x"),
        "one wei below the exact strict boundary must revert"
      );

      assert.equal(await lender.completedLoans(), 0n);
      assert.equal(await compound.completedCycles(), 0n);
      assert.equal(await route.calls(), 0n);
      assert.equal(await wpol.balanceOf(await lender.getAddress()), lenderBefore);
      assert.equal(await wpol.balanceOf(await route.getAddress()), routeBefore);
      assert.equal(await wpol.balanceOf(await compound.getAddress()), 0n);
      evidence.boundaryMinusOneWeiRevert = true;
    }
  });

  it("rejects any receiver pre-funding instead of counting subsidy as route profit", async function () {
    const { wpol, lender, route, compound } = await deploySystem();
    await (await route.configure(E("6"), E("6"), 1)).wait();
    await (await wpol.issueForTest(await compound.getAddress(), 1n)).wait();

    await expectRevert(
      compound.runCycle(PRINCIPAL, await route.getAddress(), 0, "0x"),
      "a pre-funded receiver must not be allowed to subsidize flash profitability"
    );

    assert.equal(await lender.completedLoans(), 0n);
    assert.equal(await compound.completedCycles(), 0n);
    assert.equal(await route.calls(), 0n);
    assert.equal(await wpol.balanceOf(await compound.getAddress()), 1n);
    evidence.receiverSubsidyRejected = true;
  });
});
