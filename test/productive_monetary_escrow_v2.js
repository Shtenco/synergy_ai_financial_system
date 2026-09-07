const assert = require("node:assert/strict");
const { ethers } = require("hardhat");

async function expectRevert(promise, fragment) {
  try {
    await promise;
    assert.fail("expected transaction to revert");
  } catch (err) {
    assert.match(String(err), new RegExp(fragment));
  }
}

describe("ProductiveMonetaryEscrowV2", function () {
  async function fixture() {
    const [governance, ai, risk, financialOs, productive, beneficiary, outsider] =
      await ethers.getSigners();

    const Token = await ethers.getContractFactory("MockControlledEmissionTokenV1");
    const token = await Token.deploy(governance.address);
    await token.waitForDeployment();

    const Escrow = await ethers.getContractFactory("ProductiveMonetaryEscrowV2");
    const escrow = await Escrow.deploy(
      await token.getAddress(),
      ethers.parseEther("1"),
      ethers.parseEther("1000000"),
      governance.address,
      ai.address,
      risk.address,
      financialOs.address,
      productive.address,
      10000
    );
    await escrow.waitForDeployment();
    await (await token.connect(governance).setController(await escrow.getAddress())).wait();

    return {
      governance,
      ai,
      risk,
      financialOs,
      productive,
      beneficiary,
      outsider,
      token,
      escrow,
    };
  }

  async function proposeAndLock(ctx, coverageBps = 10000, amount = "100") {
    const now = (await ethers.provider.getBlock("latest")).timestamp;
    await (
      await ctx.escrow.connect(ctx.ai).proposeEmission(
        ctx.beneficiary.address,
        ethers.parseEther(amount),
        now + 3600,
        ethers.id("policy:aicb-v5"),
        ethers.id("model:aicb-v5")
      )
    ).wait();
    const id = await ctx.escrow.proposalNonce();
    await (
      await ctx.escrow.connect(ctx.risk).approveAndLockEmission(
        id,
        ethers.parseEther(amount),
        ethers.parseEther("1"),
        coverageBps,
        ethers.id("risk:approved")
      )
    ).wait();
    return id;
  }

  async function initializeFinancial(ctx) {
    await (
      await ctx.escrow.connect(ctx.financialOs).initializeFinancialBaseline(
        ethers.id("fin:1"),
        1,
        ethers.parseEther("1000"),
        ethers.parseEther("100"),
        ethers.id("fin-evidence:1")
      )
    ).wait();
  }

  async function addFinancialCredit(ctx, close, sequence, amount) {
    const prior = 1000 + (sequence - 2) * amount;
    await (
      await ctx.escrow.connect(ctx.financialOs).recordFinancialGrowth(
        ethers.id(close),
        sequence,
        ethers.parseEther(String(prior + amount)),
        ethers.parseEther("100"),
        ethers.parseEther(String(amount)),
        0,
        0,
        ethers.id(`evidence:${close}`)
      )
    ).wait();
  }

  async function addProductiveCredit(ctx, close, sequence, goods, capacity = 0, haircut = 0) {
    await (
      await ctx.escrow.connect(ctx.productive).recordProductiveGrowth(
        ethers.id(close),
        sequence,
        ethers.parseEther(String(goods)),
        ethers.parseEther(String(capacity)),
        ethers.parseEther(String(haircut)),
        0,
        ethers.id("valuation:productive-v1"),
        ethers.id(`evidence:${close}`)
      )
    ).wait();
  }

  it("keeps AICB proposal non-minting and risk approval escrow-only", async function () {
    const ctx = await fixture();
    const now = (await ethers.provider.getBlock("latest")).timestamp;
    await (
      await ctx.escrow.connect(ctx.ai).proposeEmission(
        ctx.beneficiary.address,
        ethers.parseEther("100"),
        now + 3600,
        ethers.id("policy"),
        ethers.id("model")
      )
    ).wait();
    assert.equal(await ctx.token.totalSupply(), 0n);

    await expectRevert(
      ctx.escrow.connect(ctx.ai).approveAndLockEmission(
        1,
        ethers.parseEther("100"),
        ethers.parseEther("1"),
        10000,
        ethers.id("risk")
      ),
      "RISK_AUTHORITY_ONLY"
    );

    await (
      await ctx.escrow.connect(ctx.risk).approveAndLockEmission(
        1,
        ethers.parseEther("100"),
        ethers.parseEther("1"),
        10000,
        ethers.id("risk")
      )
    ).wait();
    assert.equal(await ctx.token.balanceOf(await ctx.escrow.getAddress()), ethers.parseEther("100"));
    assert.equal(await ctx.token.balanceOf(ctx.beneficiary.address), 0n);
  });

  it("refuses release when only Financial OS growth exists", async function () {
    const ctx = await fixture();
    const id = await proposeAndLock(ctx);
    await initializeFinancial(ctx);
    await addFinancialCredit(ctx, "fin:2", 2, 100);

    assert.equal(
      await ctx.escrow.availableFinancialGrowthCreditUsdE18(),
      ethers.parseEther("100")
    );
    assert.equal(await ctx.escrow.availableProductiveGrowthCreditUsdE18(), 0n);

    await expectRevert(
      ctx.escrow.connect(ctx.risk).releaseAgainstDualVerifiedGrowth(id, ethers.parseEther("100")),
      "NO_DUAL_VERIFIED_GROWTH"
    );
  });

  it("refuses release when only productive growth exists", async function () {
    const ctx = await fixture();
    const id = await proposeAndLock(ctx);
    await addProductiveCredit(ctx, "prod:1", 1, 100);

    assert.equal(
      await ctx.escrow.availableProductiveGrowthCreditUsdE18(),
      ethers.parseEther("100")
    );
    assert.equal(await ctx.escrow.availableFinancialGrowthCreditUsdE18(), 0n);

    await expectRevert(
      ctx.escrow.connect(ctx.risk).releaseAgainstDualVerifiedGrowth(id, ethers.parseEther("100")),
      "NO_DUAL_VERIFIED_GROWTH"
    );
  });

  it("releases only the weaker of productive and financial credits", async function () {
    const ctx = await fixture();
    const id = await proposeAndLock(ctx);
    await initializeFinancial(ctx);
    await addFinancialCredit(ctx, "fin:2", 2, 100);
    await addProductiveCredit(ctx, "prod:1", 1, 40);

    assert.equal(await ctx.escrow.availableDualGrowthCreditUsdE18(), ethers.parseEther("40"));
    await (
      await ctx.escrow.connect(ctx.risk).releaseAgainstDualVerifiedGrowth(
        id,
        ethers.parseEther("100")
      )
    ).wait();

    assert.equal(await ctx.token.balanceOf(ctx.beneficiary.address), ethers.parseEther("40"));
    assert.equal(
      await ctx.escrow.availableFinancialGrowthCreditUsdE18(),
      ethers.parseEther("60")
    );
    assert.equal(await ctx.escrow.availableProductiveGrowthCreditUsdE18(), 0n);
  });

  it("applies fraud/quality haircut before productive credit reaches escrow", async function () {
    const ctx = await fixture();
    await addProductiveCredit(ctx, "prod:1", 1, 80, 40, 30);
    assert.equal(
      await ctx.escrow.availableProductiveGrowthCreditUsdE18(),
      ethers.parseEther("90")
    );
  });

  it("fails closed on a non-zero physical consistency gap", async function () {
    const ctx = await fixture();
    await expectRevert(
      ctx.escrow.connect(ctx.productive).recordProductiveGrowth(
        ethers.id("prod:1"),
        1,
        ethers.parseEther("100"),
        0,
        0,
        1,
        ethers.id("valuation"),
        ethers.id("evidence")
      ),
      "PHYSICAL_CONSISTENCY_GAP"
    );
  });

  it("does not let internal marks, flash principal or debt-funded assets create financial credit", async function () {
    const ctx = await fixture();
    await initializeFinancial(ctx);

    await (
      await ctx.escrow.connect(ctx.financialOs).recordFinancialGrowth(
        ethers.id("fin:2"),
        2,
        ethers.parseEther("1100"),
        ethers.parseEther("100"),
        0,
        ethers.parseEther("100"),
        0,
        ethers.id("evidence:internal-mark")
      )
    ).wait();
    assert.equal(await ctx.escrow.availableFinancialGrowthCreditUsdE18(), 0n);

    await (
      await ctx.escrow.connect(ctx.financialOs).recordFinancialGrowth(
        ethers.id("fin:3"),
        3,
        ethers.parseEther("1100"),
        ethers.parseEther("200"),
        ethers.parseEther("100"),
        0,
        ethers.parseEther("100"),
        ethers.id("evidence:flash")
      )
    ).wait();
    assert.equal(await ctx.escrow.availableFinancialGrowthCreditUsdE18(), 0n);
  });

  it("supports 200% coverage with dual-gate proportional release", async function () {
    const ctx = await fixture();
    const id = await proposeAndLock(ctx, 20000, "100");
    await initializeFinancial(ctx);

    await addFinancialCredit(ctx, "fin:2", 2, 100);
    await addProductiveCredit(ctx, "prod:1", 1, 100);
    await (
      await ctx.escrow.connect(ctx.risk).releaseAgainstDualVerifiedGrowth(id, ethers.parseEther("100"))
    ).wait();
    assert.equal(await ctx.token.balanceOf(ctx.beneficiary.address), ethers.parseEther("50"));

    await addFinancialCredit(ctx, "fin:3", 3, 100);
    await addProductiveCredit(ctx, "prod:2", 2, 100);
    await (
      await ctx.escrow.connect(ctx.risk).releaseAgainstDualVerifiedGrowth(id, ethers.parseEther("100"))
    ).wait();
    assert.equal(await ctx.token.balanceOf(ctx.beneficiary.address), ethers.parseEther("100"));
    assert.equal(await ctx.escrow.totalLockedEmission(), 0n);
  });

  it("replay-protects both independent evidence streams", async function () {
    const ctx = await fixture();
    await initializeFinancial(ctx);
    await addFinancialCredit(ctx, "fin:2", 2, 10);
    await addProductiveCredit(ctx, "prod:1", 1, 10);

    await expectRevert(
      ctx.escrow.connect(ctx.financialOs).recordFinancialGrowth(
        ethers.id("fin:2"),
        3,
        ethers.parseEther("1020"),
        ethers.parseEther("100"),
        ethers.parseEther("10"),
        0,
        0,
        ethers.id("evidence:again")
      ),
      "FINANCIAL_CLOSE_REPLAY"
    );

    await expectRevert(
      ctx.escrow.connect(ctx.productive).recordProductiveGrowth(
        ethers.id("prod:1"),
        2,
        ethers.parseEther("10"),
        0,
        0,
        0,
        ethers.id("valuation"),
        ethers.id("evidence:again")
      ),
      "PRODUCTIVE_CLOSE_REPLAY"
    );
  });
});
