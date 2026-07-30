const assert = require("node:assert/strict");
const { deployConsolidatedFixture, source, E } = require("./helpers/consolidatedFixture");

describe("Consolidated internal-cycle accounting", function () {
  this.timeout(600000);

  it("runs 1000 internal cycles without false revenue, NAV or dividends", async function () {
    const f = await deployConsolidatedFixture();
    const mmAddress = await f.mm.getAddress();

    for (let i = 0; i < 1000; i++) {
      const from = i % 2 === 0 ? mmAddress : f.keeper.address;
      const to = i % 2 === 0 ? f.keeper.address : mmAddress;
      await (
        await f.ledger.recordInternalTransfer(
          source("internal-cycle", i),
          await f.reserve.getAddress(),
          E("1"),
          from,
          to
        )
      ).wait();
    }

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
