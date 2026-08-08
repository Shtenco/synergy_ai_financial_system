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

async function fixture(externalA, externalB, minProtocolGain = "0") {
  const [owner, solver] = await ethers.getSigners();

  const tokenA = await deploy("MockERC20V6", "Quote A", "A", 18);
  const tokenB = await deploy("MockERC20V6", "Quote B", "B", 18);
  const usdx = await deploy("USDx", owner.address);
  const capture = await deploy("MEVCaptureReinvestor", owner.address);
  const oracle = await deploy("PriceOracleHub", owner.address);
  const accounting = await deploy(
    "SystemAccounting",
    await oracle.getAddress(),
    await usdx.getAddress(),
    owner.address
  );

  await (await usdx.bootstrapMint(owner.address, E(200))).wait();
  await (await tokenA.mint(owner.address, E(Number(externalA) + 200))).wait();
  await (await tokenB.mint(owner.address, E(Number(externalB) + 200))).wait();
  await (await tokenB.mint(solver.address, E(100))).wait();

  const source = await deploy(
    "GraphPool",
    await usdx.getAddress(),
    await tokenA.getAddress(),
    await capture.getAddress(),
    owner.address
  );
  const destination = await deploy(
    "GraphPool",
    await usdx.getAddress(),
    await tokenB.getAddress(),
    await capture.getAddress(),
    owner.address
  );
  const external = await deploy(
    "GraphPool",
    await tokenA.getAddress(),
    await tokenB.getAddress(),
    await capture.getAddress(),
    owner.address
  );

  for (const [token, spender] of [
    [usdx, source], [usdx, destination],
    [tokenA, source], [tokenB, destination],
    [tokenA, external], [tokenB, external],
  ]) {
    await (await token.approve(await spender.getAddress(), ethers.MaxUint256)).wait();
  }

  await (await source.addLiquidity(E(100), E(100), 0)).wait();
  await (await destination.addLiquidity(E(100), E(100), 0)).wait();
  await (await external.addLiquidity(E(externalA), E(externalB), 0)).wait();

  const engine = await deploy(
    "ReserveGradientEngine",
    await usdx.getAddress(),
    await capture.getAddress(),
    await accounting.getAddress(),
    owner.address,
    owner.address,
    owner.address
  );
  const executor = await deploy("GraphArbExecutor", owner.address, await capture.getAddress());

  await (await usdx.setEngine(await engine.getAddress(), true)).wait();
  await (await capture.setController(await engine.getAddress())).wait();
  await (await capture.setCollector(await executor.getAddress(), true)).wait();

  for (const pool of [source, destination]) {
    await (await pool.setLiquidityManager(owner.address, true)).wait();
    await (await pool.setGradientController(await engine.getAddress())).wait();
    await (await pool.setArbExecutor(await executor.getAddress(), true)).wait();
    await (await pool.setExecutorOnlyAllSwaps(true)).wait();
    await (await accounting.addProtocolUSDxPoolAccount(await pool.getAddress())).wait();
  }
  await (await accounting.addProtocolUSDxAccount(await capture.getAddress())).wait();

  // True HardNAV marks are A=$1, B=$1. The external pool may quote a small basis.
  await (await oracle.updatePrices(
    [await tokenA.getAddress(), await tokenB.getAddress()],
    [E(1), E(1)]
  )).wait();
  await (await accounting.addHardAsset(await tokenA.getAddress(), 10000)).wait();
  await (await accounting.addHardAsset(await tokenB.getAddress(), 10000)).wait();
  await (await accounting.addHardAccount(await tokenA.getAddress(), await source.getAddress())).wait();
  await (await accounting.addHardAccount(await tokenB.getAddress(), await destination.getAddress())).wait();
  await (await accounting.addHardAccount(await tokenB.getAddress(), await capture.getAddress())).wait();

  await (await engine.setGradientPool(await source.getAddress(), true)).wait();
  await (await engine.setGradientPool(await destination.getAddress(), true)).wait();
  await (await engine.initializeGradient(await source.getAddress(), await destination.getAddress(), E(40))).wait();

  for (const pool of [source, destination, external]) {
    await (await executor.setVenue(await pool.getAddress(), await pool.getAddress(), true)).wait();
  }
  for (const pool of [source, destination]) {
    await (await executor.setBaseTokenGate(await pool.getAddress(), true)).wait();
    await (await executor.setAllowedBaseToken(await pool.getAddress(), await tokenB.getAddress(), true)).wait();
  }
  await (await executor.setProfitTaxBps(9900)).wait();
  await (await executor.setMinSearcherReward(await tokenB.getAddress(), E("0.001"))).wait();
  await (await executor.setProtocolNAVGuard(
    await accounting.getAddress(), true, E(minProtocolGain)
  )).wait();

  return { owner, solver, tokenA, tokenB, usdx, capture, oracle, accounting, source, destination, external, engine, executor };
}

async function buildRoute(ctx, principal) {
  const { tokenA, tokenB, usdx, source, destination, external, executor } = ctx;
  const syntheticOut = (await destination.quoteExactIn(false, principal))[0];
  const quoteAOut = (await source.quoteExactIn(true, syntheticOut))[0];
  const returnedB = (await external.quoteExactIn(true, quoteAOut))[0];
  const executorAddress = await executor.getAddress();

  const legs = [
    {
      target: await destination.getAddress(),
      spender: await destination.getAddress(),
      tokenIn: await tokenB.getAddress(),
      tokenOut: await usdx.getAddress(),
      amountIn: principal,
      minAmountOut: syntheticOut,
      data: destination.interface.encodeFunctionData(
        "swapExactIn", [false, principal, syntheticOut, executorAddress]
      )
    },
    {
      target: await source.getAddress(),
      spender: await source.getAddress(),
      tokenIn: await usdx.getAddress(),
      tokenOut: await tokenA.getAddress(),
      amountIn: syntheticOut,
      minAmountOut: quoteAOut,
      data: source.interface.encodeFunctionData(
        "swapExactIn", [true, syntheticOut, quoteAOut, executorAddress]
      )
    },
    {
      target: await external.getAddress(),
      spender: await external.getAddress(),
      tokenIn: await tokenA.getAddress(),
      tokenOut: await tokenB.getAddress(),
      amountIn: quoteAOut,
      minAmountOut: returnedB,
      data: external.interface.encodeFunctionData(
        "swapExactIn", [true, quoteAOut, returnedB, executorAddress]
      )
    }
  ];
  return { legs, returnedB };
}

describe("SynthL1 V13 post-trade HardNAV guard", function () {
  this.timeout(120000);

  it("reverts a searcher-profitable self-gradient route when protocol HardNAV would fall", async function () {
    const ctx = await fixture("10000", "10000", "0");
    const principal = E("15.5");
    const { legs, returnedB } = await buildRoute(ctx, principal);
    assert.ok(returnedB > principal, "gradient must create a raw solver edge");

    await (await ctx.tokenB.connect(ctx.solver).approve(await ctx.executor.getAddress(), principal)).wait();
    const navBefore = await ctx.accounting.consolidatedHardNAV1e18();
    const block = await ethers.provider.getBlock("latest");

    await mustRevert(
      ctx.executor.connect(ctx.solver).executeCycle(
        await ctx.tokenB.getAddress(),
        principal,
        E("0.001"),
        legs,
        BigInt(block.timestamp + 600)
      ),
      "fair-market self-funded edge must fail the HardNAV guard"
    );

    const navAfter = await ctx.accounting.consolidatedHardNAV1e18();
    assert.equal(navAfter, navBefore, "reverted route must leave protocol NAV unchanged");
    assert.equal(await ctx.source.reserve0(), E(60));
    assert.equal(await ctx.destination.reserve0(), E(140));
  });

  it("accepts an initiated route that converts a latent external basis into positive HardNAV", async function () {
    const ctx = await fixture("10000", "10100", "0.05");
    const principal = E("39.8");
    const { legs, returnedB } = await buildRoute(ctx, principal);
    assert.ok(returnedB > principal, "latent-basis gradient route must reward the solver");

    await (await ctx.tokenB.connect(ctx.solver).approve(await ctx.executor.getAddress(), principal)).wait();
    const navBefore = await ctx.accounting.consolidatedHardNAV1e18();
    const solverBefore = await ctx.tokenB.balanceOf(ctx.solver.address);
    const block = await ethers.provider.getBlock("latest");

    await (await ctx.executor.connect(ctx.solver).executeCycle(
      await ctx.tokenB.getAddress(),
      principal,
      E("0.001"),
      legs,
      BigInt(block.timestamp + 600)
    )).wait();

    const navAfter = await ctx.accounting.consolidatedHardNAV1e18();
    const solverAfter = await ctx.tokenB.balanceOf(ctx.solver.address);
    assert.ok(navAfter >= navBefore + E("0.05"), "protocol HardNAV must increase atomically");
    assert.ok(solverAfter > solverBefore, "solver must retain a positive reward");
    assert.ok(await ctx.tokenB.balanceOf(await ctx.capture.getAddress()) > 0n, "profit tax must be physically captured");

    const supply = await ctx.usdx.totalSupply();
    await (await ctx.engine.restoreGradient()).wait();
    assert.equal(await ctx.usdx.totalSupply(), supply, "restore must remain supply-neutral");
    assert.equal(await ctx.source.reserve0(), E(60));
    assert.equal(await ctx.destination.reserve0(), E(140));
  });
});
