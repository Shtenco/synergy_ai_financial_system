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

describe("V15 Stage-3 accounting/oracle hardening", function () {
  this.timeout(120000);

  async function fixture() {
    const [owner] = await ethers.getSigners();
    const usdc = await deploy("MockERC20V6", "USDC", "USDC", 18);
    const oracle = await deploy("PriceOracleHub", owner.address);
    const liabilities = await deploy("V15LiabilityRegistry", owner.address);
    const ledger = await deploy(
      "V15EconomicLedger", owner.address, await oracle.getAddress(), await liabilities.getAddress()
    );

    await (await usdc.mint(owner.address, E(100))).wait();
    await (await oracle.updatePrice(await usdc.getAddress(), E(1))).wait();
    await (await ledger.addHardAsset(await usdc.getAddress())).wait();
    await (await ledger.setHardAccount(await usdc.getAddress(), owner.address, true)).wait();

    const id = ethers.keccak256(ethers.toUtf8Bytes("MANUAL_REDEMPTION"));
    await (await liabilities.addLiability(id, 18, E(1), 10000, ethers.ZeroAddress, E(20))).wait();
    return { owner, usdc, oracle, liabilities, ledger, id };
  }

  it("uses the lower fresh Economic feed and fails closed when the frozen validator becomes stale", async function () {
    const [owner] = await ethers.getSigners();
    const usdc = await deploy("MockERC20V6", "USDC", "USDC", 18);
    const primary = await deploy("PriceOracleHub", owner.address);
    const validator = await deploy("PriceOracleHub", owner.address);
    const liabilities = await deploy("V15LiabilityRegistry", owner.address);
    const ledger = await deploy(
      "V15EconomicLedger", owner.address, await primary.getAddress(), await liabilities.getAddress()
    );

    await (await usdc.mint(owner.address, E(100))).wait();
    await (await primary.updatePrice(await usdc.getAddress(), E(2))).wait();
    await (await validator.updatePrice(await usdc.getAddress(), E(1))).wait();
    await (await ledger.addHardAsset(await usdc.getAddress())).wait();
    await (await ledger.setHardAccount(await usdc.getAddress(), owner.address, true)).wait();
    await (await ledger.setValidationOracle(await validator.getAddress(), true)).wait();

    assert.equal(await ledger.oracleValidationReady(), true);
    assert.equal(await ledger.canonicalPrice1e18(await usdc.getAddress()), E(1));
    assert.equal(await ledger.hardNAV1e18(), E(100));
    await mustRevert(
      ledger.setValidationOracle(await primary.getAddress(), false),
      "frozen validation oracle must be immutable"
    );

    // Only validator expires; primary remains fresh under its default 60s max age.
    await (await validator.setMaxAge(1)).wait();
    await ethers.provider.send("evm_increaseTime", [2]);
    await ethers.provider.send("evm_mine", []);
    await mustRevert(
      ledger.hardNAV1e18(),
      "stale independent validation feed must fail Economic HardNAV closed"
    );
  });

  it("fails closed when a manual liability report becomes stale", async function () {
    const c = await fixture();
    assert.equal(await c.ledger.hardNAV1e18(), E(80));

    await (await c.liabilities.setManualMaxAge(1)).wait();
    await ethers.provider.send("evm_increaseTime", [2]);
    await ethers.provider.send("evm_mine", []);

    await mustRevert(
      c.ledger.hardNAV1e18(),
      "stale manual liability must make Economic HardNAV unavailable rather than optimistic"
    );

    await (await c.liabilities.setManualAmount(c.id, E(20))).wait();
    assert.equal(await c.ledger.hardNAV1e18(), E(80));
  });

  it("cannot disable a non-zero liability and requires a fresh manual report after source reset", async function () {
    const c = await fixture();

    await mustRevert(
      c.liabilities.setEnabled(c.id, false),
      "outstanding liability must not be removable from balance sheet"
    );

    await (await c.liabilities.setManualAmount(c.id, 0)).wait();
    await (await c.liabilities.setEnabled(c.id, false)).wait();
    assert.equal(await c.ledger.hardNAV1e18(), E(100));

    await (await c.liabilities.setEnabled(c.id, true)).wait();
    await (await c.liabilities.setManualAmount(c.id, E(5))).wait();
    assert.equal(await c.ledger.hardNAV1e18(), E(95));

    await (await c.liabilities.setSource(c.id, ethers.ZeroAddress)).wait();
    await mustRevert(c.ledger.hardNAV1e18(), "source reset must require a fresh manual liability report");
    await (await c.liabilities.setManualAmount(c.id, E(5))).wait();
    assert.equal(await c.ledger.hardNAV1e18(), E(95));
  });
});
