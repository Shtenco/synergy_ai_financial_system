const assert = require("node:assert/strict");
const { ethers } = require("hardhat");
const { deployConsolidatedFixture, source, E } = require("./helpers/consolidatedFixture");

describe("Zero-revenue safe pause", function () {
  it("pauses for 20000 blocks without reserve drain or meaningless self-cycles", async function () {
    const f = await deployConsolidatedFixture();
    const qeAddress = await f.qe.getAddress();

    await (await f.reserve.mint(qeAddress, E("100"))).wait();
    const balanceBefore = await f.reserve.balanceOf(qeAddress);
    const entriesBefore = await f.ledger.entryCount();
    const pnlBefore = await f.ledger.realizedExternalPnL();

    await (await f.solvency.updateEnvironment(false, true, true)).wait();
    assert.equal(await f.solvency.mode(), 4n); // PAUSED

    await ethers.provider.send("hardhat_mine", ["0x4e20"]); // 20,000 blocks

    assert.equal(await f.solvency.mode(), 4n);
    assert.equal(await f.reserve.balanceOf(qeAddress), balanceBefore);
    assert.equal(await f.ledger.entryCount(), entriesBefore);
    assert.equal(await f.ledger.realizedExternalPnL(), pnlBefore);
    assert.equal(await f.ledger.totalDividends(), 0n);
    assert.equal(await f.ledger.externalLiabilities(), 0n);

    await assert.rejects(
      f.qe.allocate(0, E("1"), source("forbidden-zero-revenue-qe")).then((tx) => tx.wait())
    );
  });
});
