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

describe("SynthL1 V6 configuration guards", function () {
  this.timeout(120000);

  it("locks bootstrap mint permanently after runtime engine installation", async function () {
    const [owner] = await ethers.getSigners();
    const usdx = await deploy("USDx", owner.address);
    await (await usdx.bootstrapMint(owner.address, E(10))).wait();

    // Any non-zero runtime engine address permanently closes bootstrap.
    await (await usdx.setEngine(owner.address, true)).wait();
    await mustRevert(
      usdx.bootstrapMint(owner.address, E(1)),
      "bootstrap mint must revert after engine installation"
    );
  });

  it("rejects dust-LP griefing once a managed pool locks liquidity providers", async function () {
    const [owner, attacker] = await ethers.getSigners();
    const usdx = await deploy("USDx", owner.address);
    const quote = await deploy("MockERC20V6", "Quote", "Q", 18);
    const capture = await deploy("MEVCaptureReinvestor", owner.address);
    const pool = await deploy(
      "GraphPool", await usdx.getAddress(), await quote.getAddress(), await capture.getAddress(), owner.address
    );

    await (await usdx.bootstrapMint(owner.address, E(100))).wait();
    await (await quote.mint(owner.address, E(100))).wait();
    await (await usdx.approve(await pool.getAddress(), ethers.MaxUint256)).wait();
    await (await quote.approve(await pool.getAddress(), ethers.MaxUint256)).wait();
    await (await pool.addLiquidity(E(100), E(100), 0)).wait();

    await (await pool.setLiquidityManager(owner.address, true)).wait();

    // Attacker has valid tokens and approvals, so only the provider gate blocks the grief attempt.
    await (await usdx.bootstrapMint(attacker.address, E(1))).wait();
    await (await quote.mint(attacker.address, E(1))).wait();
    await (await usdx.connect(attacker).approve(await pool.getAddress(), E(1))).wait();
    await (await quote.connect(attacker).approve(await pool.getAddress(), E(1))).wait();

    await mustRevert(
      pool.connect(attacker).addLiquidity(E(1), E(1), 0),
      "third-party LP addition must revert in managed mode"
    );
  });

  it("rejects direct synthetic-to-quote closure when executor-only gate is enabled", async function () {
    const [owner, solver] = await ethers.getSigners();
    const usdx = await deploy("USDx", owner.address);
    const quote = await deploy("MockERC20V6", "Quote", "Q", 18);
    const capture = await deploy("MEVCaptureReinvestor", owner.address);
    const pool = await deploy(
      "GraphPool", await usdx.getAddress(), await quote.getAddress(), await capture.getAddress(), owner.address
    );

    await (await usdx.bootstrapMint(owner.address, E(100))).wait();
    await (await quote.mint(owner.address, E(100))).wait();
    await (await usdx.bootstrapMint(solver.address, E(1))).wait();

    await (await usdx.approve(await pool.getAddress(), ethers.MaxUint256)).wait();
    await (await quote.approve(await pool.getAddress(), ethers.MaxUint256)).wait();
    await (await pool.addLiquidity(E(100), E(100), 0)).wait();

    // owner stands in for configured GraphArbExecutor in this isolated gate test.
    await (await pool.setArbExecutor(owner.address, true)).wait();
    await (await usdx.connect(solver).approve(await pool.getAddress(), E(1))).wait();

    await mustRevert(
      pool.connect(solver).swapExactIn(true, E(1), 0, solver.address),
      "solver must not bypass the executor on managed closing direction"
    );
  });
});
