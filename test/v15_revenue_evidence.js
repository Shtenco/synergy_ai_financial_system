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

async function fixture() {
  const [owner, investor, recipient] = await ethers.getSigners();
  const usdc = await deploy("MockERC20V6", "USDC", "USDC", 18);
  const primary = await deploy("PriceOracleHub", owner.address);
  const validator = await deploy("PriceOracleHub", owner.address);
  const liabilities = await deploy("V15LiabilityRegistry", owner.address);
  const ledger = await deploy(
    "V15EconomicLedger", owner.address, await primary.getAddress(), await liabilities.getAddress()
  );

  await (await primary.updatePrice(await usdc.getAddress(), E(1))).wait();
  await (await validator.updatePrice(await usdc.getAddress(), E(1))).wait();
  await (await ledger.addHardAsset(await usdc.getAddress())).wait();
  await (await ledger.setValidationOracle(await validator.getAddress(), true)).wait();

  const risk = await deploy("V15RiskOracle", owner.address, await primary.getAddress());
  await (await risk.setValidatedCanonicalAnchor(await ledger.getAddress(), true)).wait();
  await (await risk.setHaircut(await usdc.getAddress(), 10000)).wait();
  await (await risk.setRiskData(await usdc.getAddress(), E(1), E(1))).wait();
  await (await risk.addScenario(ethers.encodeBytes32String("BASE"), 10000, 0)).wait();
  await (await risk.setScenarioAsset(0, await usdc.getAddress(), 10000, 10000)).wait();

  const liabilityId = ethers.keccak256(ethers.toUtf8Bytes("REDEMPTION"));
  await (await liabilities.addLiability(liabilityId, 18, E(1), 10000, ethers.ZeroAddress, E(100))).wait();

  const controller = await deploy(
    "V15SolvencyController", owner.address, await ledger.getAddress(), await liabilities.getAddress(), await risk.getAddress()
  );
  const router = await deploy(
    "V15RevenueRouter", owner.address, owner.address, await ledger.getAddress(), await controller.getAddress()
  );
  const source = await deploy("MockV15RevenueSource", owner.address);

  await (await usdc.mint(owner.address, E(200))).wait();
  await (await ledger.setHardAccount(await usdc.getAddress(), owner.address, true)).wait();
  await (await ledger.setHardAccount(await usdc.getAddress(), await router.getAddress(), true)).wait();
  await (await ledger.setHardAccount(await usdc.getAddress(), await source.getAddress(), true)).wait();

  const selector = ethers.id("cumulativeEligibleRevenue(address)").slice(0, 10);
  await (await router.setRevenueSource(await source.getAddress(), selector, true)).wait();

  await (await controller.pokeMode()).wait();
  await (await controller.pokeMode()).wait();
  await (await controller.pokeMode()).wait();
  assert.equal(await controller.mode(), 0n);
  assert.equal(await controller.searcherRouteAllowed(), true);

  async function generateEligible(amount) {
    await (await usdc.mint(owner.address, amount)).wait();
    await (await usdc.approve(await source.getAddress(), amount)).wait();
    await (await source.recognizeAndFund(await usdc.getAddress(), amount)).wait();
    await (await source.approveRouter(await usdc.getAddress(), await router.getAddress(), amount)).wait();
    await (await router.recordEligibleRevenueToken(await usdc.getAddress(), await source.getAddress(), amount)).wait();
  }

  return { owner, investor, recipient, usdc, ledger, liabilities, controller, router, source, generateEligible };
}

describe("V15 current revenue evidence / HWM accounting", function () {
  this.timeout(120000);

  it("distributes only physically evidenced hard revenue within solvency headroom", async function () {
    const c = await fixture();
    await (await c.router.startPeriod()).wait();
    await c.generateEligible(E(20));
    assert.equal(await c.router.eligibleRevenue1e18(), E(20));
    await (await c.router.settlePeriod()).wait();
    assert.equal(await c.router.distributableBudget1e18(), E(20));
    await (await c.router.distribute(await c.usdc.getAddress(), c.recipient.address, E(10))).wait();
    await mustRevert(
      c.router.distribute(await c.usdc.getAddress(), c.recipient.address, E(11)),
      "distribution cannot exceed evidenced hard-profit budget"
    );
  });

  it("rejects raw source balance that lacks monotonic revenue evidence", async function () {
    const c = await fixture();
    await (await c.router.startPeriod()).wait();
    await (await c.usdc.mint(c.owner.address, E(10))).wait();
    await (await c.usdc.transfer(await c.source.getAddress(), E(10))).wait();
    await (await c.source.approveRouter(await c.usdc.getAddress(), await c.router.getAddress(), E(10))).wait();
    await mustRevert(
      c.router.recordEligibleRevenueToken(await c.usdc.getAddress(), await c.source.getAddress(), E(10)),
      "raw donation must not masquerade as revenue"
    );
  });

  it("external capital contribution raises NAV but not operating revenue", async function () {
    const c = await fixture();
    await (await c.router.startPeriod()).wait();
    await (await c.usdc.mint(c.investor.address, E(20))).wait();
    await (await c.usdc.connect(c.investor).approve(await c.router.getAddress(), E(20))).wait();
    await (await c.router.connect(c.owner).recordContributionToken(await c.usdc.getAddress(), c.investor.address, E(20))).wait();
    assert.equal(await c.router.contributions1e18(), E(20));
    await (await c.router.settlePeriod()).wait();
    assert.equal(await c.router.distributableBudget1e18(), 0n);
  });

  it("recovers prior hard loss before exposing new profit to distribution", async function () {
    const c = await fixture();
    await (await c.router.startPeriod()).wait();
    await (await c.usdc.transfer(c.recipient.address, E(20))).wait();
    await (await c.router.settlePeriod()).wait();
    assert.equal(await c.router.lossCarryforward1e18(), E(20));
    await (await c.router.closePeriod()).wait();

    await (await c.router.startPeriod()).wait();
    await c.generateEligible(E(25));
    await (await c.router.settlePeriod()).wait();
    assert.equal(await c.router.lossCarryforward1e18(), 0n);
    assert.equal(await c.router.distributableBudget1e18(), E(5));
  });
});
