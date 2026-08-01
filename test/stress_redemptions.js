const assert = require("node:assert/strict");
const { deployConsolidatedFixture, E } = require("./helpers/consolidatedFixture");

describe("Mass redemption stress", function () {
  it("moves NORMAL to DEFENSIVE and PAUSED before reserves become negative", async function () {
    const f = await deployConsolidatedFixture({ externalSynrClaims: "1100" });

    async function applyShock(redemptionShock, stressedOutflows) {
      await (
        await f.solvency.updateOtherLiabilities({
          externalSynrClaims: E("1100"),
          vestedMevClaims: 0,
          bridgeObligations: 0,
          keeperReimbursementsAccrued: 0,
          externalDebt: 0,
          expectedThirtyDayOperatingCosts: E("10"),
          modeledRedemptionShock: E(redemptionShock)
        })
      ).wait();
      await (
        await f.solvency.updateCoverageInputs(
          E("1000"),
          E(stressedOutflows),
          E("700"),
          E("1000"),
          E("100"),
          0,
          1
        )
      ).wait();
      await (await f.solvency.updateEnvironment(true, true, true)).wait();
    }

    // 10% modeled redemption shock.
    await applyShock("110", "500");
    assert.equal(await f.solvency.mode(), 2n); // NORMAL
    assert.ok((await f.solvency.economicSolvencyBps()) >= 12000n);
    assert.ok((await f.solvency.liquidityCoverageBps()) >= 12000n);

    // 30% modeled shock: solvency remains above 105%, but normal buffers fail.
    await applyShock("330", "900");
    assert.equal(await f.solvency.mode(), 3n); // DEFENSIVE
    assert.ok((await f.solvency.economicSolvencyBps()) >= 10500n);
    assert.ok((await f.solvency.economicSolvencyBps()) < 12000n);

    // 50% modeled shock: fail closed before haircut assets go negative.
    await applyShock("550", "1200");
    assert.equal(await f.solvency.mode(), 4n); // PAUSED
    assert.ok((await f.solvency.economicSolvencyBps()) < 10500n);
    assert.ok((await f.solvency.consolidatedNav()) < 0n || (await f.solvency.liquidityCoverageBps()) < 10500n);
    assert.equal(await f.ledger.totalDividends(), 0n);
  });
});
