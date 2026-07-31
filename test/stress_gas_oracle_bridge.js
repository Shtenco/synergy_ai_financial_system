const assert = require("node:assert/strict");
const { deployConsolidatedFixture, source, E } = require("./helpers/consolidatedFixture");

describe("Gas, oracle and bridge stress gates", function () {
  it("fails closed below 120% gas coverage and on stale infrastructure", async function () {
    const f = await deployConsolidatedFixture();
    const qeAddress = await f.qe.getAddress();
    await (await f.reserve.mint(qeAddress, E("100"))).wait();

    assert.equal(await f.solvency.gasCoverageBps(), 12000n);
    assert.equal(await f.solvency.mode(), 2n);

    await (
      await f.solvency.updateAssets({
        ...f.assets,
        gasReserve: E("19")
      })
    ).wait();
    await (await f.solvency.updateEnvironment(true, true, true)).wait();
    assert.equal(await f.solvency.gasCoverageBps(), 11900n);
    assert.equal(await f.solvency.mode(), 4n);
    await assert.rejects(
      f.qe.allocate(0, E("1"), source("qe-underfunded-gas")).then((tx) => tx.wait())
    );

    await (
      await f.solvency.updateAssets({
        ...f.assets,
        gasReserve: E("20")
      })
    ).wait();
    await (await f.solvency.updateEnvironment(true, false, true)).wait();
    assert.equal(await f.solvency.mode(), 4n);

    await (await f.solvency.updateEnvironment(true, true, false)).wait();
    assert.equal(await f.solvency.mode(), 4n);

    await (await f.solvency.updateEnvironment(true, true, true)).wait();
    assert.equal(await f.solvency.mode(), 2n);
    assert.equal(await f.solvency.gasCoverageBps(), 12000n);
  });
});
