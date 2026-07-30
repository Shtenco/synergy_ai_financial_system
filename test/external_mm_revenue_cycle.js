const assert = require("node:assert/strict");
const { ethers } = require("hardhat");
const { deployConsolidatedFixture, source, E } = require("./helpers/consolidatedFixture");

describe("External market flow and liability QT", function () {
  this.timeout(1800000);

  it("completes 1000 external issue/redeem cycles and bounds dividends by external PnL", async function () {
    const f = await deployConsolidatedFixture();
    const mmAddress = await f.mm.getAddress();
    const qtAddress = await f.qt.getAddress();
    const dividendAddress = await f.dividend.getAddress();

    await (await f.syn.mint(mmAddress, E("1000"))).wait();
    await (
      await f.ledger.recordInventoryIncrease(
        source("initial-inventory"),
        await f.syn.getAddress(),
        E("1000"),
        mmAddress
      )
    ).wait();

    // Recovery capital is principal, not revenue. It funds the 0.75 tender leg.
    await (await f.reserve.mint(qtAddress, E("750"))).wait();
    await (await f.reserve.mint(f.externalBuyer.address, E("1100"))).wait();
    await (
      await f.reserve.connect(f.externalBuyer).approve(mmAddress, ethers.MaxUint256)
    ).wait();
    await (
      await f.syn.connect(f.externalBuyer).approve(qtAddress, ethers.MaxUint256)
    ).wait();

    for (let i = 0; i < 1000; i++) {
      await (
        await f.mm.sellToExternalBuyer(
          f.externalBuyer.address,
          E("1"),
          E("1.1"),
          E("0.01"),
          f.externalCostRecipient.address,
          source("capital", i),
          source("spread", i),
          source("inventory-out", i),
          source("execution-cost", i)
        )
      ).wait();

      assert.equal(await f.ledger.externalLiabilities(), E("1"));
      assert.equal(await f.syn.balanceOf(f.externalBuyer.address), E("1"));

      await (
        await f.qt.externalTenderAndBurn(
          f.externalBuyer.address,
          E("1"),
          0,
          ethers.ZeroAddress,
          source("qt-redemption", i),
          source("unused-qt-cost", i)
        )
      ).wait();

      assert.equal(await f.ledger.externalLiabilities(), 0n, `cycle ${i}: liability remained`);
      assert.equal(await f.syn.balanceOf(f.externalBuyer.address), 0n, `cycle ${i}: SYN remained`);
    }

    assert.equal(await f.mm.totalExternalVolume(), E("1100"));
    assert.equal(await f.mm.totalRealizedSpread(), E("90"));
    assert.equal(await f.qt.totalExternalSynBurned(), E("1000"));
    assert.equal(await f.syn.totalSupply(), 0n);
    assert.equal(await f.ledger.protocolInventory(), 0n);
    assert.equal(await f.ledger.externalLiabilities(), 0n);
    assert.equal(await f.ledger.cumulativeExternalRevenue(), E("100"));
    assert.equal(await f.ledger.cumulativeExternalExpense(), E("760"));
    assert.equal(await f.ledger.realizedExternalPnL(), E("340"));
    assert.equal(await f.ledger.consolidatedNavDelta(), E("340"));

    // Move only the proven realized profit to the system dividend vault.
    await (
      await f.mm.transferReserveInternal(dividendAddress, E("340"), source("profit-to-dividend"))
    ).wait();

    await (
      await f.solvency.updateAssets({
        liquidReserves: E("1090"),
        stableLpNav: E("100"),
        volatileLpNav: E("100"),
        bridgeCapital: E("100"),
        insuranceAssets: E("100"),
        yieldPositions: E("100"),
        gasReserve: E("20"),
        unrealizedInventoryValue: 0
      })
    ).wait();
    await (await f.solvency.updateEnvironment(true, true, true)).wait();

    assert.equal(await f.dividend.maximumDividend(), E("170"));
    await (
      await f.dividend.payDividend(
        f.dividendRecipient.address,
        E("170"),
        source("external-profit-dividend")
      )
    ).wait();

    assert.equal(await f.reserve.balanceOf(f.dividendRecipient.address), E("170"));
    assert.equal(await f.ledger.totalDividends(), E("170"));
    assert.ok((await f.ledger.totalDividends()) <= BigInt(await f.ledger.realizedExternalPnL()));
    assert.equal(await f.ledger.consolidatedNavDelta(), E("170"));
    assert.equal(await f.reserve.balanceOf(dividendAddress), E("170"));
  });
});
