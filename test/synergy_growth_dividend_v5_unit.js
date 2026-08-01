const assert = require("node:assert/strict");
const { ethers } = require("hardhat");

const E = ethers.parseEther;
const source = (label) => ethers.keccak256(ethers.toUtf8Bytes(label));

describe("SYNERGY V5 dividend compounding, permissioned DEX and MEV guards", function () {
  this.timeout(1200000);

  async function eligible(registry, admin, participant, label) {
    const latest = await ethers.provider.getBlock("latest");
    await (
      await registry.connect(admin).setParticipant(
        participant.address,
        true,
        BigInt(latest.timestamp + 86400),
        source(label)
      )
    ).wait();
  }

  it("reinvests owner and keeper dividends only from actual external reserve profit", async function () {
    const [admin, owner, keeper, externalPayer, protocolTreasury, taxEscrow] =
      await ethers.getSigners();

    const Token = await ethers.getContractFactory("MockTokenV5", admin);
    const reserve = await Token.deploy("Mock POL", "mPOL");
    await reserve.waitForDeployment();

    const Registry = await ethers.getContractFactory("ParticipantTaxRegistry", admin);
    const registry = await Registry.deploy(admin.address);
    await registry.waitForDeployment();
    await eligible(registry, admin, owner, "owner-tax");
    await eligible(registry, admin, keeper, "keeper-tax");

    const Boundary = await ethers.getContractFactory("MockBoundaryV5", admin);
    const boundary = await Boundary.deploy();
    await boundary.waitForDeployment();

    const Risk = await ethers.getContractFactory("MockRiskGateV5", admin);
    const risk = await Risk.deploy();
    await risk.waitForDeployment();
    await (await risk.set(true, E("1.15616"))).wait();

    const Engine = await ethers.getContractFactory("MockReinvestmentEngineV5", admin);
    const engine = await Engine.deploy(await reserve.getAddress(), protocolTreasury.address);
    await engine.waitForDeployment();

    const Controller = await ethers.getContractFactory("AutoReinvestDividendControllerV5", admin);
    const controller = await Controller.deploy(
      await reserve.getAddress(),
      await registry.getAddress(),
      await boundary.getAddress(),
      await risk.getAddress(),
      await engine.getAddress(),
      owner.address,
      protocolTreasury.address,
      taxEscrow.address,
      1000,
      E("1")
    );
    await controller.waitForDeployment();

    await (await reserve.mint(externalPayer.address, E("100"))).wait();
    await (
      await reserve.connect(externalPayer).approve(await controller.getAddress(), ethers.MaxUint256)
    ).wait();

    await (
      await controller.settleExternalProfit(
        externalPayer.address,
        E("100"),
        keeper.address,
        source("external-profit-1")
      )
    ).wait();

    assert.equal(await controller.cumulativeGrossExternalProfit(), E("100"));
    assert.equal(await controller.cumulativeGrossDividends(), E("10"));
    assert.equal(await controller.cumulativeTaxWithheld(), E("1"));
    assert.equal(await controller.cumulativeRetainedReinvestment(), E("90"));
    assert.equal(await controller.cumulativeOwnerNetReinvestment(), E("4.5"));
    assert.equal(await controller.cumulativeKeeperNetReinvestment(), E("4.5"));
    assert.equal(await engine.equityShares(owner.address), E("4.5"));
    assert.equal(await engine.equityShares(keeper.address), E("4.5"));
    assert.equal(await engine.equityShares(protocolTreasury.address), E("90"));
    assert.equal(await reserve.balanceOf(taxEscrow.address), E("1"));
    assert.equal(await reserve.balanceOf(await engine.getAddress()), E("99"));
    assert.equal(await reserve.balanceOf(owner.address), 0n);
    assert.equal(await reserve.balanceOf(keeper.address), 0n);
    assert.equal(await reserve.balanceOf(await controller.getAddress()), 0n);

    await (await reserve.mint(externalPayer.address, E("1"))).wait();
    await (await boundary.set(externalPayer.address, true)).wait();
    await assert.rejects(
      controller.settleExternalProfit(
        externalPayer.address,
        E("1"),
        keeper.address,
        source("internal-fake-profit")
      )
    );
  });

  it("allows only registered tax-current participants to use SINERGY DEX", async function () {
    const [admin, alice, bob, outsider] = await ethers.getSigners();
    const Token = await ethers.getContractFactory("MockTokenV5", admin);
    const tokenA = await Token.deploy("Asset A", "A");
    const tokenB = await Token.deploy("Asset B", "B");
    await tokenA.waitForDeployment();
    await tokenB.waitForDeployment();

    const Registry = await ethers.getContractFactory("ParticipantTaxRegistry", admin);
    const registry = await Registry.deploy(admin.address);
    await registry.waitForDeployment();
    await eligible(registry, admin, alice, "alice-tax");
    await eligible(registry, admin, bob, "bob-tax");

    const Factory = await ethers.getContractFactory("SynergyDexFactoryV5", admin);
    const factory = await Factory.deploy(await registry.getAddress());
    await factory.waitForDeployment();
    const Router = await ethers.getContractFactory("SynergyDexRouterV5", admin);
    const router = await Router.deploy(await registry.getAddress(), await factory.getAddress());
    await router.waitForDeployment();
    await (await factory.setRouter(await router.getAddress(), true)).wait();
    await (await factory.createPair(await tokenA.getAddress(), await tokenB.getAddress())).wait();
    const pairAddress = await factory.getPair(await tokenA.getAddress(), await tokenB.getAddress());
    assert.notEqual(pairAddress, ethers.ZeroAddress);

    for (const user of [alice, bob, outsider]) {
      await (await tokenA.mint(user.address, E("200"))).wait();
      await (await tokenB.mint(user.address, E("200"))).wait();
      await (await tokenA.connect(user).approve(await router.getAddress(), ethers.MaxUint256)).wait();
      await (await tokenB.connect(user).approve(await router.getAddress(), ethers.MaxUint256)).wait();
    }

    const deadline = BigInt((await ethers.provider.getBlock("latest")).timestamp + 3600);
    await (
      await router.connect(alice).addLiquidity(
        await tokenA.getAddress(),
        await tokenB.getAddress(),
        E("100"),
        E("100"),
        alice.address,
        deadline
      )
    ).wait();

    const beforeBob = await tokenB.balanceOf(bob.address);
    await (
      await router.connect(bob).swapExactTokensForTokens(
        await tokenA.getAddress(),
        await tokenB.getAddress(),
        E("1"),
        E("0.9"),
        bob.address,
        deadline
      )
    ).wait();
    assert.ok((await tokenB.balanceOf(bob.address)) > beforeBob);

    await assert.rejects(
      router.connect(outsider).swapExactTokensForTokens(
        await tokenA.getAddress(),
        await tokenB.getAddress(),
        E("1"),
        E("0.9"),
        outsider.address,
        deadline
      )
    );
    await assert.rejects(
      router.connect(bob).swapExactTokensForTokens(
        await tokenA.getAddress(),
        await tokenB.getAddress(),
        E("1"),
        0,
        bob.address,
        deadline
      )
    );
  });

  it("binds protected orders to a delayed commit and rejects zero/deviant quotes", async function () {
    const [alice, attacker] = await ethers.getSigners();
    const Guard = await ethers.getContractFactory("SynergyOrderCommitmentGuardV5", alice);
    const guard = await Guard.deploy(2, 120);
    await guard.waitForDeployment();

    const tokenIn = ethers.Wallet.createRandom().address;
    const tokenOut = ethers.Wallet.createRandom().address;
    const deadline = BigInt((await ethers.provider.getBlock("latest")).timestamp + 3600);
    const salt = source("private-salt");
    const hash = await guard.hashOrder(
      alice.address,
      tokenIn,
      tokenOut,
      E("1"),
      E("0.95"),
      deadline,
      1,
      salt
    );
    await (await guard.commitOrder(hash)).wait();

    await assert.rejects(
      guard.revealAndConsume(tokenIn, tokenOut, E("1"), E("0.95"), deadline, 1, salt)
    );
    await assert.rejects(
      guard.connect(attacker).revealAndConsume(
        tokenIn,
        tokenOut,
        E("1"),
        E("0.95"),
        deadline,
        1,
        salt
      )
    );

    await ethers.provider.send("hardhat_mine", ["0x2"]);
    await (
      await guard.revealAndConsume(tokenIn, tokenOut, E("1"), E("0.95"), deadline, 1, salt)
    ).wait();

    assert.equal(await guard.validateQuote(E("1"), E("0.99"), E("0.95"), 200), true);
    await assert.rejects(guard.validateQuote(E("1"), 0, E("0.95"), 200));
    await assert.rejects(guard.validateQuote(E("1"), E("0.9"), 0, 200));
  });
});
