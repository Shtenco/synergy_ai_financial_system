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

describe("V15 guardian emergency stop", function () {
  this.timeout(120000);

  it("guardian can stop risk immediately but only owner can restart", async function () {
    const [owner, guardian] = await ethers.getSigners();
    const usdc = await deploy("MockERC20V6", "USDC", "USDC", 18);
    const oracle = await deploy("PriceOracleHub", owner.address);
    const validationOracle = await deploy("PriceOracleHub", owner.address);
    const liabilities = await deploy("V15LiabilityRegistry", owner.address);
    const ledger = await deploy(
      "V15EconomicLedger", owner.address, await oracle.getAddress(), await liabilities.getAddress()
    );
    const risk = await deploy("V15RiskOracle", owner.address, await oracle.getAddress());

    await (await usdc.mint(owner.address, E(200))).wait();
    await (await oracle.updatePrice(await usdc.getAddress(), E(1))).wait();
    await (await validationOracle.updatePrice(await usdc.getAddress(), E(1))).wait();
    await (await ledger.addHardAsset(await usdc.getAddress())).wait();
    await (await ledger.setHardAccount(await usdc.getAddress(), owner.address, true)).wait();
    await (await ledger.setValidationOracle(await validationOracle.getAddress(), true)).wait();
    await (await risk.setValidatedCanonicalAnchor(await ledger.getAddress(), true)).wait();
    assert.equal(await risk.validatedAnchorReady(), true);

    const id = ethers.keccak256(ethers.toUtf8Bytes("LIABILITY"));
    await (await liabilities.addLiability(id, 18, E(1), 10000, ethers.ZeroAddress, E(100))).wait();
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
    assert.equal(await controller.mode(), 0n);
    assert.equal(await controller.searcherRouteAllowed(), true);
    assert.equal(await controller.routeSolvent(), true);

    await (await controller.setGuardian(guardian.address)).wait();
    await (await controller.connect(guardian).setEmergencyPaused(true)).wait();
    assert.equal(await controller.emergencyPaused(), true);
    assert.equal(await controller.searcherRouteAllowed(), false);
    assert.equal(await controller.distributionAllowed(), false);
    assert.equal(await controller.routeSolvent(), true, "survival/restore solvency must remain observable");

    await mustRevert(
      controller.connect(guardian).setEmergencyPaused(false),
      "guardian must not be able to restart risk"
    );
    await (await controller.setEmergencyPaused(false)).wait();
    assert.equal(await controller.searcherRouteAllowed(), true);
  });
});
