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

  await (await risk.setRiskData(await usdc.getAddress(), E(1), E(1), 10000)).wait();
  await (await risk.addScenario(ethers.encodeBytes32String("BASE"), 10000, 0)).wait();
  await (await risk.setScenarioAsset(0, await usdc.getAddress(), 10000, 10000)).wait();

  const controller = await deploy(
    "V15SolvencyController",
    owner.address,
    await ledger.getAddress(),
    await liabilities.getAddress(),
    await risk.getAddress()
  );

  // RED -> ORANGE -> YELLOW -> GREEN through hysteresis re-entry.
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

describe("V15 economic/risk overlay", function () {
  this.timeout(120000);

  it("separates Economic HardNAV from risk solvency and fails closed on K/STS breach", async function () {
    const c = await setup();
    assert.equal(await c.ledger.hardNAV1e18(), E(100));
    assert.equal(await c.adapter.consolidatedHardNAV1e18(), E(100));

    const metrics = await c.controller.metrics();
    assert.equal(metrics[3], 20000n, "coverage must be 200%");
    assert.equal(metrics[4], 20000n, "STS must be 200%");

    // Re-enabling an account must not duplicate it in the ledger array.
    await (await c.ledger.setHardAccount(await c.usdc.getAddress(), c.owner.address, false)).wait();
    await (await c.ledger.setHardAccount(await c.usdc.getAddress(), c.owner.address, true)).wait();
    assert.equal(await c.ledger.hardAssets1e18(), E(200), "account re-enable must not double count assets");

    // A liability shock pushes coverage below the ORANGE floor. Economic NAV is
    // still defined, but the compatibility adapter must refuse executor NAV reads.
    await (await c.liabilities.setManualAmount(c.liabilityId, E(195))).wait();
    assert.equal(await c.controller.routeSolvent(), false);
    assert.equal(await c.ledger.hardNAV1e18(), E(5));
    await mustRevert(c.adapter.consolidatedHardNAV1e18(), "unsafe route state must fail closed");
  });

  it("distributes only settled hard profit and checks solvency again after transfer", async function () {
    const c = await setup();
    const router = await deploy(
      "V15RevenueRouter",
      c.owner.address,
      c.owner.address,
      await c.ledger.getAddress(),
      await c.controller.getAddress()
    );
    await (await c.ledger.setHardAccount(await c.usdc.getAddress(), await router.getAddress(), true)).wait();

    await (await router.startPeriod()).wait();
    await (await c.usdc.mint(await router.getAddress(), E(20))).wait(); // fixture external hard revenue
    await (await router.settlePeriod(E(5))).wait();
    assert.equal(await router.distributableBudget1e18(), E(15));

    await (await router.distribute(await c.usdc.getAddress(), c.outsider.address, E(10))).wait();
    assert.equal(await c.usdc.balanceOf(c.outsider.address), E(10));
    await mustRevert(
      router.distribute(await c.usdc.getAddress(), c.outsider.address, E(6)),
      "cannot exceed settled hard-profit budget"
    );
    await mustRevert(router.settlePeriod(0), "same period cannot be settled twice");
  });

  it("capital contribution does not masquerade as operating hard profit", async function () {
    const c = await setup();
    const router = await deploy(
      "V15RevenueRouter",
      c.owner.address,
      c.owner.address,
      await c.ledger.getAddress(),
      await c.controller.getAddress()
    );
    await (await c.ledger.setHardAccount(await c.usdc.getAddress(), await router.getAddress(), true)).wait();
    await (await router.startPeriod()).wait();
    await (await c.usdc.mint(await router.getAddress(), E(20))).wait();
    await (await router.recordContribution1e18(E(20))).wait();
    await (await router.settlePeriod(0)).wait();
    assert.equal(await router.distributableBudget1e18(), 0n);
  });
});
