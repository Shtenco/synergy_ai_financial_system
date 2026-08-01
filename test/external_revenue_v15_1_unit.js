"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { ethers, network } = require("hardhat");

const E = ethers.parseEther;

async function mineUntil(blockNumber) {
  while ((await ethers.provider.getBlockNumber()) <= blockNumber) {
    await network.provider.send("evm_mine", []);
  }
}

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

function writeReport(report) {
  const reports = path.join(process.cwd(), "reports");
  fs.mkdirSync(reports, { recursive: true });
  fs.writeFileSync(
    path.join(reports, "v15_1_structural_test.json"),
    JSON.stringify(report, null, 2)
  );
}

describe("SYNERGY V15.1 structural accounting", function () {
  it("settles without refund-loop DoS and splits only realized route profit", async function () {
    const [coordinator, treasury, solver1, solver2] = await ethers.getSigners();

    const Token = await ethers.getContractFactory("MockERC20V151", coordinator);
    const settlement = await Token.deploy("Settlement", "SET");
    await settlement.waitForDeployment();
    const intermediate = await Token.deploy("Intermediate", "MID");
    await intermediate.waitForDeployment();

    const Auction = await ethers.getContractFactory("SolverAuctionV151", coordinator);
    const auction = await Auction.deploy(
      treasury.address,
      coordinator.address,
      E("0.05")
    );
    await auction.waitForDeployment();

    const Engine = await ethers.getContractFactory("ExternalRevenueEngineV151", coordinator);
    const engine = await Engine.deploy(
      await auction.getAddress(),
      treasury.address,
      coordinator.address
    );
    await engine.waitForDeployment();

    const Adapter = await ethers.getContractFactory("MockRateAdapterV151", coordinator);
    const adapter1 = await Adapter.deploy(
      await settlement.getAddress(),
      await intermediate.getAddress(),
      2,
      1
    );
    await adapter1.waitForDeployment();
    const adapter2 = await Adapter.deploy(
      await intermediate.getAddress(),
      await settlement.getAddress(),
      11,
      20
    );
    await adapter2.waitForDeployment();

    const RejectingBidder = await ethers.getContractFactory("RejectNativeBidderV151", coordinator);
    const rejectingBidder = await RejectingBidder.deploy();
    await rejectingBidder.waitForDeployment();

    await (await auction.connect(treasury).setConsumer(await engine.getAddress())).wait();
    await (await engine.setAdapter(await adapter1.getAddress(), true)).wait();
    await (await engine.setAdapter(await adapter2.getAddress(), true)).wait();

    const principal = E("1000");
    await (await settlement.issueForTest(solver2.address, principal)).wait();
    await (await intermediate.issueForTest(await adapter1.getAddress(), E("5000"))).wait();
    await (await settlement.issueForTest(await adapter2.getAddress(), E("5000"))).wait();
    await (await settlement.connect(solver2).approve(await engine.getAddress(), principal)).wait();

    const steps = [
      {
        adapter: await adapter1.getAddress(),
        tokenIn: await settlement.getAddress(),
        tokenOut: await intermediate.getAddress(),
        minAmountOut: E("2000"),
        data: "0x"
      },
      {
        adapter: await adapter2.getAddress(),
        tokenIn: await intermediate.getAddress(),
        tokenOut: await settlement.getAddress(),
        minAmountOut: E("1100"),
        data: "0x"
      }
    ];

    const currentBlock = await ethers.provider.getBlockNumber();
    const closeBlock = currentBlock + 12;
    const expiryBlock = closeBlock + 20;
    const venuesHash = ethers.keccak256(ethers.toUtf8Bytes("V15.1 STRUCTURAL FIXTURE"));

    await (
      await auction.publish(
        await settlement.getAddress(),
        principal,
        E("1"),
        269,
        5000,
        closeBlock,
        expiryBlock,
        venuesHash
      )
    ).wait();
    const epoch = await auction.currentEpoch();
    const solutionHash = await engine.hashRoute(
      epoch,
      await settlement.getAddress(),
      principal,
      steps
    );

    await (
      await auction.connect(solver1).bid(epoch, solutionHash, 6000, { value: E("0.05") })
    ).wait();
    await (
      await rejectingBidder.placeBid(
        await auction.getAddress(),
        epoch,
        solutionHash,
        7000,
        { value: E("0.05") }
      )
    ).wait();
    await (
      await auction.connect(solver2).bid(epoch, solutionHash, 8000, { value: E("0.05") })
    ).wait();

    assert.equal(await auction.refunds(await rejectingBidder.getAddress()), E("0.05"));
    await mineUntil(closeBlock);
    await (await auction.settle(epoch)).wait();

    const winner = await auction.best(epoch);
    assert.equal(winner[0].toLowerCase(), solver2.address.toLowerCase());
    assert.equal(Number(winner[2]), 8000);
    assert.equal(winner[3], solutionHash);
    assert.equal(winner[4], true);

    const treasuryBefore = await settlement.balanceOf(treasury.address);
    const solverBefore = await settlement.balanceOf(solver2.address);
    const executionReceipt = await (
      await engine.connect(solver2).execute(
        epoch,
        solutionHash,
        await settlement.getAddress(),
        principal,
        steps
      )
    ).wait();

    const treasuryRevenue = (await settlement.balanceOf(treasury.address)) - treasuryBefore;
    const solverRevenue = (await settlement.balanceOf(solver2.address)) - solverBefore;
    assert.equal(treasuryRevenue, E("80"));
    assert.equal(solverRevenue, E("20"));
    assert.equal(await settlement.balanceOf(await engine.getAddress()), 0n);
    assert.equal(await auction.consumed(epoch), true);
    assert.equal(await engine.cumulativeTreasuryRevenue(await settlement.getAddress()), E("80"));
    assert.equal(await engine.cumulativeSolverRevenue(await settlement.getAddress()), E("20"));

    assert.equal(await auction.refunds(solver2.address), E("0.05"));
    await (await auction.connect(solver2).withdrawRefund()).wait();
    assert.equal(await auction.refunds(solver2.address), 0n);

    await expectRevert(
      rejectingBidder.withdraw(await auction.getAddress()),
      "rejecting loser must fail only its own pull refund"
    );
    assert.equal(await auction.refunds(await rejectingBidder.getAddress()), E("0.05"));

    await expectRevert(
      engine.connect(solver2).execute(
        epoch,
        solutionHash,
        await settlement.getAddress(),
        principal,
        steps
      ),
      "consumed solution must not be replayable"
    );

    writeReport({
      scenario: "synergy_v15_1_structural_accounting",
      evidenceClass: "STRUCTURAL_PASS",
      economicEdgeProven: false,
      auction: {
        pullRefunds: true,
        rejectingLoserDidNotBlockSettlement: true,
        refundableWinnerBondCountedAsRevenue: false,
        treasuryShareBps: 8000,
        solutionConsumedOnce: true
      },
      rawAccounting: {
        principal: principal.toString(),
        grossProfit: E("100").toString(),
        treasuryRevenue: treasuryRevenue.toString(),
        solverRevenue: solverRevenue.toString(),
        engineSettlementResidue: (
          await settlement.balanceOf(await engine.getAddress())
        ).toString()
      },
      execution: {
        transactionHash: executionReceipt.hash,
        blockNumber: executionReceipt.blockNumber
      },
      interpretation: "Fixture rates validate mechanics only and are excluded from historical external-revenue evidence."
    });
  });
});
