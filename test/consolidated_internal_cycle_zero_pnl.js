const assert = require("node:assert/strict");
const { deployConsolidatedFixture, source, E } = require("./helpers/consolidatedFixture");

describe("Consolidated internal-cycle accounting", function () {
  this.timeout(600000);

  it("runs 1000 internal cycles without false revenue, NAV or dividends", async function () {
    const f = await deployConsolidatedFixture();
    const mmAddress = await f.mm.getAddress();

    const Batch = await ethers.getContractFactory("ConsolidatedCycleBatchHarness", f.admin);
    const batch = await Batch.deploy(
      await f.ledger.getAddress(),
      await f.mm.getAddress(),
      await f.qt.getAddress()
    );
    await batch.waitForDeployment();
    await (await f.ledger.setRecorder(await batch.getAddress(), true)).wait();

    for (let start = 0; start < 1000; start += 100) {
      await (
        await batch.batchInternalTransfers(
          start,
          100,
          await f.reserve.getAddress(),
          E("1"),
          mmAddress,
          f.keeper.address
        )
      ).wait();
    }

    assert.equal(await f.ledger.entryCount(), 1000n);
    assert.equal(await f.ledger.internalTransferVolume(), E("1000"));
    assert.equal(await f.ledger.cumulativeExternalRevenue(), 0n);
    assert.equal(await f.ledger.externalLiabilities(), 0n);
    assert.equal(await f.ledger.realizedExternalPnL(), 0n);
    assert.equal(await f.ledger.consolidatedNavDelta(), 0n);
    assert.equal(await f.solvency.dividendableCapital(), 0n);

    await assert.rejects(
      f.dividend
        .payDividend(f.dividendRecipient.address, E("1"), source("false-dividend"))
        .then((tx) => tx.wait())
    );

    // A measured payment to a truly external address is the only loss here.
    await (await f.reserve.mint(f.admin.address, E("1"))).wait();
    await (await f.reserve.transfer(f.externalCostRecipient.address, E("1"))).wait();
    await (
      await f.ledger.recordExternalExpense(
        source("external-gas"),
        await f.reserve.getAddress(),
        E("1"),
        f.admin.address,
        f.externalCostRecipient.address
      )
    ).wait();

    assert.equal(await f.ledger.realizedExternalPnL(), -E("1"));
    assert.equal(await f.ledger.consolidatedNavDelta(), -E("1"));
    assert.equal(await f.solvency.dividendableCapital(), 0n);
    assert.equal(await f.ledger.totalDividends(), 0n);
  });
});
