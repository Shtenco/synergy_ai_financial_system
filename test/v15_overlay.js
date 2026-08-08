const assert = require("node:assert/strict");
const { ethers } = require("hardhat");

const E = (x) => ethers.parseEther(String(x));

async function deploy(name, ...args) {
  const F = await ethers.getContractFactory(name);
  const c = await F.deploy(...args);
  await c.waitForDeployment();
  return c;
}

async function mustRevert(promise, label) {
  let reverted = false;
  try { await promise; } catch (_) { reverted = true; }
  assert.equal(reverted, true, label);
}

async function setup() {
  const [owner, outsider] = await ethers.getSigners();
  const usdc = await deploy("MockERC20V6", "USDC", "USDC", 18);
  const synthetic = await deploy("MockERC20V6", "SYNA", "SYNA", 18);
  const oracle = await deploy("PriceOracleHub", owner.address);
  const liabilities = await deploy("V15LiabilityRegistry", owner.address);
  const ledger = await deploy("V15EconomicLedger", owner.address, await oracle.getAddress(), await liabilities.getAddress());
  const risk = await deploy("V15RiskOracle", owner.address, await oracle.getAddress());

  await (await usdc.mint(owner.address, E(200))).wait();
  await (await synthetic.mint(owner.address, E(1000000))).wait();
  await (await oracle.updatePrice(await usdc.getAddress(), E(1))).wait();

  await (await ledger.permanentlyExcludeAsset(await synthetic.getAddress())).wait();
  await mustRevert(ledger.addHardAsset(await synthetic.getAddress()), "own synthetic must never become HardAsset");
  await (await ledger.addHardAsset(await usdc.getAddress())).wait();
  await (await ledger.setHardAccount(await usdc.getAddress(), owner.address, true)).wait();

  const liabilityId = ethers.keccak256(ethers.toUtf8Bytes("USDX_REDEMPTION"));
  await (await liabilities.addLiability(liabilityId, 18, E(1), 10000, ethers.ZeroAddress, E(100))).wait();

  await (await risk.setHaircut(await usdc.getAddress(), 10000)).wait();
  await (await risk.setRiskData(await usdc.getAddress(), E(1), E(1))).wait();
  await (await risk.addScenario(ethers.encodeBytes32String("BASE"), 10000, 0)).wait();
  await (await risk.setScenarioAsset(0, await usdc.getAddress(), 10000, 10000)).wait();

  const controller = await deploy(
    "V15SolvencyController",
    owner.address,
    await ledger.getAddress(),
    await liabilities.getAddress(),
    await risk.getAddress()
  );

  await (await controller.pokeMode()).wait();
  await (await controller.pokeMode()).wait();
  await (await controller.pokeMode()).wait();
  assert.equal(await controller.mode(), 0n, "healthy system must reach GREEN");

  const gate = await deploy("V15PostRouteGate", await controller.getAddress());
  const adapter = await deploy(
    "V15AccountingAdapter",
    owner.address,
    owner.address,
    await ledger.getAddress(),
    await gate.getAddress(),
    await controller.getAddress()
  );

  return { owner, outsider, usdc, synthetic, oracle, liabilities, liabilityId, ledger, risk, controller, gate, adapter };
}

async function revenueRouter(c) {
  const router = await deploy(
    "V15RevenueRouter",
    c.owner.address,
    c.owner.address,
    await c.ledger.getAddress(),
    await c.controller.getAddress()
  );
  await (await c.ledger.setHardAccount(await c.usdc.getAddress(), await router.getAddress(), true)).wait();
  return router;
}

describe("V15 economic/risk overlay", function () {
  this.timeout(120000);

  it("separates Economic HardNAV from risk solvency and fails closed on K/STS breach", async function () {
    const c = await setup();
    assert.equal(await c.ledger.hardNAV1e18(), E(100));
    assert.equal(await c.adapter.consolidatedHardNAV1e18(), E(100));

    const metrics = await c.controller.metrics();
    assert.equal(metrics[3], 20000n, "coverage must be 200%");
    assert.equal(metrics[4], 20000n, "STS must be 200%");

    await (await c.ledger.setHardAccount(await c.usdc.getAddress(), c.owner.address, false)).wait();
    await (await c.ledger.setHardAccount(await c.usdc.getAddress(), c.owner.address, true)).wait();
    assert.equal(await c.ledger.hardAssets1e18(), E(200), "account re-enable must not double count assets");

    await (await c.liabilities.setManualAmount(c.liabilityId, E(195))).wait();
    assert.equal(await c.controller.routeSolvent(), false);
    assert.equal(await c.ledger.hardNAV1e18(), E(5));
    await mustRevert(c.adapter.consolidatedHardNAV1e18(), "unsafe route state must fail closed");
  });

  it("requires HWM profit, eligible revenue, and automatic solvency headroom", async function () {
    const c = await setup();
    const router = await revenueRouter(c);
    await (await router.setRevenueSource(c.owner.address, true)).wait();
    await (await router.startPeriod()).wait();

    await (await c.usdc.mint(c.owner.address, E(20))).wait();
    await (await c.usdc.approve(await router.getAddress(), E(20))).wait();
    await (await router.recordEligibleRevenueToken(await c.usdc.getAddress(), c.owner.address, E(20))).wait();

    assert.equal(await router.eligibleRevenue1e18(), E(20));
    assert.ok((await c.controller.distributionHeadroom1e18()) >= E(20));
    await (await router.settlePeriod()).wait();
    assert.equal(await router.distributableBudget1e18(), E(20));

    await (await router.distribute(await c.usdc.getAddress(), c.outsider.address, E(10))).wait();
    await mustRevert(
      router.distribute(await c.usdc.getAddress(), c.outsider.address, E(11)),
      "cannot exceed automatically derived hard-profit budget"
    );
  });

  it("automatic absolute-capital headroom can bind distribution below eligible profit", async function () {
    const c = await setup();
    const router = await revenueRouter(c);
    await (await router.setRevenueSource(c.owner.address, true)).wait();
    await (await router.startPeriod()).wait();

    await (await c.usdc.mint(c.owner.address, E(50))).wait();
    await (await c.usdc.approve(await router.getAddress(), E(50))).wait();
    await (await router.recordEligibleRevenueToken(await c.usdc.getAddress(), c.owner.address, E(50))).wait();
    // Risk assets are now 250. Requiring 230 leaves at most 20 canonical USD
    // under the conservative 1 hard USD -> up to 1 risk USD assumption.
    await (await c.controller.setPortfolioLimits(E(230), 10000)).wait();
    assert.equal(await c.controller.distributionHeadroom1e18(), E(20));
    await (await router.settlePeriod()).wait();
    assert.equal(await router.distributableBudget1e18(), E(20));

    await (await router.distribute(await c.usdc.getAddress(), c.outsider.address, E(19))).wait();
    await mustRevert(
      router.distribute(await c.usdc.getAddress(), c.outsider.address, E(1)),
      "post-transfer capital floor must reject the final unit at the boundary"
    );
  });

  it("direct donation can raise HardNAV but cannot become distributable revenue without an eligible sweep", async function () {
    const c = await setup();
    const router = await revenueRouter(c);
    await (await router.startPeriod()).wait();

    await (await c.usdc.mint(c.outsider.address, E(20))).wait();
    await (await c.usdc.connect(c.outsider).transfer(c.owner.address, E(20))).wait();
    assert.equal(await c.ledger.hardNAV1e18(), E(120));

    await (await router.settlePeriod()).wait();
    assert.equal(await router.eligibleRevenue1e18(), 0n);
    assert.equal(await router.distributableBudget1e18(), 0n);
  });

  it("physical external capital contribution does not masquerade as operating hard profit", async function () {
    const c = await setup();
    const router = await revenueRouter(c);
    await (await router.startPeriod()).wait();

    await (await c.usdc.mint(c.outsider.address, E(20))).wait();
    await (await c.usdc.connect(c.outsider).approve(await router.getAddress(), E(20))).wait();
    await (await router.recordContributionToken(await c.usdc.getAddress(), c.outsider.address, E(20))).wait();

    assert.equal(await router.contributions1e18(), E(20));
    await (await router.settlePeriod()).wait();
    assert.equal(await router.distributableBudget1e18(), 0n);
  });

  it("settles crisis losses even when no distribution is allowed", async function () {
    const c = await setup();
    const router = await revenueRouter(c);
    await (await router.startPeriod()).wait();

    await (await c.usdc.transfer(c.outsider.address, E(100))).wait();
    await (await c.controller.pokeMode()).wait();
    assert.equal(await c.controller.distributionAllowed(), false);

    await (await router.settlePeriod()).wait();
    assert.equal(await router.lossCarryforward1e18(), E(100));
    assert.equal(await router.distributableBudget1e18(), 0n);
  });

  it("carries losses forward and requires eligible hard revenue after recovery", async function () {
    const c = await setup();
    const router = await revenueRouter(c);
    await (await router.setRevenueSource(c.owner.address, true)).wait();

    await (await router.startPeriod()).wait();
    await (await c.usdc.transfer(c.outsider.address, E(20))).wait();
    await (await router.settlePeriod()).wait();
    assert.equal(await router.lossCarryforward1e18(), E(20));
    assert.equal(await router.distributableBudget1e18(), 0n);
    await (await router.closePeriod()).wait();

    await (await router.startPeriod()).wait();
    await (await c.usdc.connect(c.outsider).transfer(c.owner.address, E(20))).wait();
    await (await c.usdc.mint(c.owner.address, E(5))).wait();
    await (await c.usdc.approve(await router.getAddress(), E(5))).wait();
    await (await router.recordEligibleRevenueToken(await c.usdc.getAddress(), c.owner.address, E(5))).wait();

    await (await router.settlePeriod()).wait();
    assert.equal(await router.lossCarryforward1e18(), 0n);
    assert.equal(await router.distributableBudget1e18(), E(5));
  });
});
