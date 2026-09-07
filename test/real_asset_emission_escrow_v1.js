const assert = require("node:assert/strict");
const { ethers, network } = require("hardhat");

async function expectRevert(promise, fragment) {
  try {
    await promise;
    assert.fail("expected transaction to revert");
  } catch (err) {
    assert.match(String(err), new RegExp(fragment));
  }
}

describe("RealAssetEmissionEscrowV1", function () {
  async function fixture() {
    const [governance, ai, risk, financialOs, beneficiary, outsider] = await ethers.getSigners();

    const Token = await ethers.getContractFactory("MockControlledEmissionTokenV1");
    const token = await Token.deploy(governance.address);
    await token.waitForDeployment();

    const Escrow = await ethers.getContractFactory("RealAssetEmissionEscrowV1");
    const escrow = await Escrow.deploy(
      await token.getAddress(),
      ethers.parseEther("1"),
      ethers.parseEther("1000000"),
      governance.address,
      ai.address,
      risk.address,
      financialOs.address,
      10000
    );
    await escrow.waitForDeployment();
    await (await token.connect(governance).setController(await escrow.getAddress())).wait();

    return { governance, ai, risk, financialOs, beneficiary, outsider, token, escrow };
  }

  async function propose(ctx, amount = "100", seconds = 3600) {
    const now = (await ethers.provider.getBlock("latest")).timestamp;
    await (
      await ctx.escrow.connect(ctx.ai).proposeEmission(
        ctx.beneficiary.address,
        ethers.parseEther(amount),
        now + seconds,
        ethers.id("policy:v1"),
        ethers.id("ai-model:v1")
      )
    ).wait();
    return await ctx.escrow.proposalNonce();
  }

  it("keeps AI proposal non-minting and requires independent risk approval", async function () {
    const ctx = await fixture();
    const id = await propose(ctx);

    assert.equal(await ctx.token.totalSupply(), 0n);
    assert.equal(await ctx.token.balanceOf(ctx.beneficiary.address), 0n);

    await expectRevert(
      ctx.escrow.connect(ctx.ai).approveAndLockEmission(
        id,
        ethers.parseEther("100"),
        ethers.parseEther("1"),
        20000,
        ethers.id("risk-approval")
      ),
      "RISK_AUTHORITY_ONLY"
    );

    await (
      await ctx.escrow.connect(ctx.risk).approveAndLockEmission(
        id,
        ethers.parseEther("100"),
        ethers.parseEther("1"),
        20000,
        ethers.id("risk-approval")
      )
    ).wait();

    assert.equal(await ctx.token.totalSupply(), ethers.parseEther("100"));
    assert.equal(await ctx.token.balanceOf(await ctx.escrow.getAddress()), ethers.parseEther("100"));
    assert.equal(await ctx.token.balanceOf(ctx.beneficiary.address), 0n);

    const p = await ctx.escrow.proposals(id);
    assert.equal(p.requiredGrowthUsdE18, ethers.parseEther("200"));
  });

  it("does not credit internal marks or liability-funded/flash-like asset growth", async function () {
    const ctx = await fixture();

    await (
      await ctx.escrow.connect(ctx.financialOs).initializeFinancialBaseline(
        ethers.id("close:1"),
        1,
        ethers.parseEther("1000"),
        ethers.parseEther("100"),
        ethers.id("evidence:1")
      )
    ).wait();

    // HardNAV rises, but Financial OS classifies the move as internal mark only.
    await (
      await ctx.escrow.connect(ctx.financialOs).recordFinancialClose(
        ethers.id("close:2"),
        2,
        ethers.parseEther("1100"),
        ethers.parseEther("100"),
        0,
        ethers.parseEther("100"),
        0,
        ethers.id("evidence:2")
      )
    ).wait();
    assert.equal(await ctx.escrow.availableGrowthCreditUsdE18(), 0n);

    // Assets rise by 100, but liabilities also rise by 100 (flash/debt-funded).
    await (
      await ctx.escrow.connect(ctx.financialOs).recordFinancialClose(
        ethers.id("close:3"),
        3,
        ethers.parseEther("1100"),
        ethers.parseEther("200"),
        ethers.parseEther("100"),
        0,
        ethers.parseEther("100"),
        ethers.id("evidence:3")
      )
    ).wait();
    assert.equal(await ctx.escrow.availableGrowthCreditUsdE18(), 0n);
  });

  it("releases target emission proportionally only after verified real asset growth", async function () {
    const ctx = await fixture();
    const id = await propose(ctx);

    await (
      await ctx.escrow.connect(ctx.risk).approveAndLockEmission(
        id,
        ethers.parseEther("100"),
        ethers.parseEther("1"),
        20000,
        ethers.id("risk-approval")
      )
    ).wait();

    await (
      await ctx.escrow.connect(ctx.financialOs).initializeFinancialBaseline(
        ethers.id("close:1"),
        1,
        ethers.parseEther("1000"),
        ethers.parseEther("100"),
        ethers.id("evidence:1")
      )
    ).wait();

    await expectRevert(
      ctx.escrow.connect(ctx.risk).releaseAgainstVerifiedGrowth(id, ethers.parseEther("100")),
      "NO_VERIFIED_GROWTH_CREDIT"
    );

    // +100 eligible assets, +100 HardNAV, no liability growth => +100 credit.
    await (
      await ctx.escrow.connect(ctx.financialOs).recordFinancialClose(
        ethers.id("close:2"),
        2,
        ethers.parseEther("1100"),
        ethers.parseEther("100"),
        ethers.parseEther("100"),
        0,
        0,
        ethers.id("evidence:2")
      )
    ).wait();

    assert.equal(await ctx.escrow.availableGrowthCreditUsdE18(), ethers.parseEther("100"));

    await (
      await ctx.escrow.connect(ctx.risk).releaseAgainstVerifiedGrowth(id, ethers.parseEther("100"))
    ).wait();

    // 200% coverage means 100 USD of growth unlocks 50 of the 100 tokens.
    assert.equal(await ctx.token.balanceOf(ctx.beneficiary.address), ethers.parseEther("50"));
    assert.equal(await ctx.escrow.totalLockedEmission(), ethers.parseEther("50"));

    // Another +100 verified growth completes the target.
    await (
      await ctx.escrow.connect(ctx.financialOs).recordFinancialClose(
        ethers.id("close:3"),
        3,
        ethers.parseEther("1200"),
        ethers.parseEther("100"),
        ethers.parseEther("100"),
        0,
        0,
        ethers.id("evidence:3")
      )
    ).wait();
    await (
      await ctx.escrow.connect(ctx.risk).releaseAgainstVerifiedGrowth(id, ethers.parseEther("100"))
    ).wait();

    assert.equal(await ctx.token.balanceOf(ctx.beneficiary.address), ethers.parseEther("100"));
    assert.equal(await ctx.escrow.totalLockedEmission(), 0n);
    assert.equal(await ctx.escrow.totalReleasedEmission(), ethers.parseEther("100"));
    const p = await ctx.escrow.proposals(id);
    assert.equal(Number(p.status), 3); // RELEASED
  });

  it("rejects Financial OS close replay and non-monotonic sequence", async function () {
    const ctx = await fixture();
    await (
      await ctx.escrow.connect(ctx.financialOs).initializeFinancialBaseline(
        ethers.id("close:1"), 1, ethers.parseEther("1000"), 0, ethers.id("evidence:1")
      )
    ).wait();

    await (
      await ctx.escrow.connect(ctx.financialOs).recordFinancialClose(
        ethers.id("close:2"), 2, ethers.parseEther("1010"), 0, ethers.parseEther("10"), 0, 0,
        ethers.id("evidence:2")
      )
    ).wait();

    await expectRevert(
      ctx.escrow.connect(ctx.financialOs).recordFinancialClose(
        ethers.id("close:2"), 3, ethers.parseEther("1020"), 0, ethers.parseEther("10"), 0, 0,
        ethers.id("evidence:3")
      ),
      "CLOSE_REPLAY"
    );

    await expectRevert(
      ctx.escrow.connect(ctx.financialOs).recordFinancialClose(
        ethers.id("close:3"), 2, ethers.parseEther("1020"), 0, ethers.parseEther("10"), 0, 0,
        ethers.id("evidence:3")
      ),
      "NON_MONOTONIC_CLOSE"
    );
  });

  it("burns unvested target emission on cancellation", async function () {
    const ctx = await fixture();
    const id = await propose(ctx, "80");

    await (
      await ctx.escrow.connect(ctx.risk).approveAndLockEmission(
        id,
        ethers.parseEther("80"),
        ethers.parseEther("1"),
        10000,
        ethers.id("risk-approval")
      )
    ).wait();
    assert.equal(await ctx.token.totalSupply(), ethers.parseEther("80"));

    await (
      await ctx.escrow.connect(ctx.risk).cancelProposal(id, ethers.id("cancel:no-longer-required"))
    ).wait();

    assert.equal(await ctx.token.totalSupply(), 0n);
    assert.equal(await ctx.escrow.totalLockedEmission(), 0n);
    assert.equal(await ctx.escrow.totalBurnedEmission(), ethers.parseEther("80"));
  });

  it("burns unreleased emission after deterministic expiry", async function () {
    const ctx = await fixture();
    const id = await propose(ctx, "25", 20);

    await (
      await ctx.escrow.connect(ctx.risk).approveAndLockEmission(
        id,
        ethers.parseEther("25"),
        ethers.parseEther("1"),
        10000,
        ethers.id("risk-approval")
      )
    ).wait();

    await network.provider.send("evm_increaseTime", [30]);
    await network.provider.send("evm_mine");
    await (await ctx.escrow.connect(ctx.outsider).expireProposal(id)).wait();

    assert.equal(await ctx.token.totalSupply(), 0n);
    assert.equal(await ctx.escrow.totalLockedEmission(), 0n);
    const p = await ctx.escrow.proposals(id);
    assert.equal(Number(p.status), 5); // EXPIRED
  });
});
