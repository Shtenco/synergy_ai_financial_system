const assert = require("node:assert/strict");
const { ethers } = require("hardhat");
const { deployConsolidatedFixture, source, E } = require("./helpers/consolidatedFixture");

describe("External-profit-only dividends", function () {
  it("rejects principal and internal funding, then permits bounded external profit", async function () {
    const f = await deployConsolidatedFixture();
    const mmAddress = await f.mm.getAddress();
    const dividendAddress = await f.dividend.getAddress();

    // Principal in the vault is not realized profit.
    await (await f.reserve.mint(dividendAddress, E("100"))).wait();
    assert.equal(await f.dividend.maximumDividend(), 0n);
    await assert.rejects(
      f.dividend
        .payDividend(f.dividendRecipient.address, E("1"), source("principal-dividend"))
        .then((tx) => tx.wait())
    );

    // A real external balance delta is recognized exactly once.
    await (await f.reserve.mint(f.externalStrategy.address, E("20"))).wait();
    await (
      await f.reserve.connect(f.externalStrategy).approve(mmAddress, ethers.MaxUint256)
    ).wait();
    await (
      await f.mm.collectExternalStrategyRevenue(
        f.externalStrategy.address,
        E("20"),
        source("external-strategy-revenue")
      )
    ).wait();
    await (
      await f.mm.transferReserveInternal(
        dividendAddress,
        E("20"),
        source("external-profit-internal-routing")
      )
    ).wait();

    assert.equal(await f.ledger.realizedExternalPnL(), E("20"));
    assert.equal(await f.ledger.internalTransferVolume(), E("20"));
    assert.equal(await f.dividend.maximumDividend(), E("10"));

    await (
      await f.dividend.payDividend(
        f.dividendRecipient.address,
        E("10"),
        source("bounded-external-dividend")
      )
    ).wait();

    assert.equal(await f.ledger.totalDividends(), E("10"));
    assert.equal(await f.reserve.balanceOf(f.dividendRecipient.address), E("10"));
    assert.ok((await f.ledger.totalDividends()) <= BigInt(await f.ledger.realizedExternalPnL()));

    await assert.rejects(
      f.ledger
        .recordExternalRevenue(
          source("external-strategy-revenue"),
          await f.reserve.getAddress(),
          E("1"),
          0,
          f.externalStrategy.address,
          mmAddress,
          await f.reserve.balanceOf(mmAddress)
        )
        .then((tx) => tx.wait())
    );
  });
});
