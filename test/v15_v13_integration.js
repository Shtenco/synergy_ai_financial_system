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

async function fixture(bHaircutBps = 10000) {
  const [owner, solver] = await ethers.getSigners();
  const tokenA = await deploy("MockERC20V6", "Quote A", "A", 18);
  const tokenB = await deploy("MockERC20V6", "Quote B", "B", 18);
  const usdx = await deploy("USDx", owner.address);
  const capture = await deploy("MEVCaptureReinvestor", owner.address);
  const oracle = await deploy("PriceOracleHub", owner.address);
  const validationOracle = await deploy("PriceOracleHub", owner.address);
  const liabilities = await deploy("V15LiabilityRegistry", owner.address);
  const ledger = await deploy("V15EconomicLedger", owner.address, await oracle.getAddress(), await liabilities.getAddress());
  const risk = await deploy("V15RiskOracle", owner.address, await oracle.getAddress());
  const controller = await deploy(
    "V15SolvencyController",
    owner.address,
    await ledger.getAddress(),
    await liabilities.getAddress(),
    await risk.getAddress()
  );
  const gate = await deploy("V15PostRouteGate", await controller.getAddress());
  const adapter = await deploy(
    "V15AccountingAdapter",
    owner.address,
    owner.address,
    await ledger.getAddress(),
    await gate.getAddress(),
    await controller.getAddress()
  );
  const coordinator = await deploy("V15Coordinator", owner.address, owner.address, await controller.getAddress());

  const source = await deploy("GraphPool", await usdx.getAddress(), await tokenA.getAddress(), await capture.getAddress(), owner.address);
  const destination = await deploy("GraphPool", await usdx.getAddress(), await tokenB.getAddress(), await capture.getAddress(), owner.address);
  const external = await deploy("GraphPool", await tokenA.getAddress(), await tokenB.getAddress(), await capture.getAddress(), owner.address);

  await (await usdx.bootstrapMint(owner.address, E(200))).wait();
  await (await tokenA.mint(owner.address, E(10200))).wait();
  await (await tokenB.mint(owner.address, E(10300))).wait();
  await (await tokenB.mint(solver.address, E(100))).wait();

  for (const [token, spender] of [
    [usdx, source], [usdx, destination],
    [tokenA, source], [tokenB, destination],
    [tokenA, external], [tokenB, external]
  ]) {
    await (await token.approve(await spender.getAddress(), ethers.MaxUint256)).wait();
  }
  await (await source.addLiquidity(E(100), E(100), 0)).wait();
  await (await destination.addLiquidity(E(100), E(100), 0)).wait();
  await (await external.addLiquidity(E(10000), E(10100), 0)).wait();

  const engine = await deploy(
    "ReserveGradientEngine",
    await usdx.getAddress(),
    await capture.getAddress(),
    await adapter.getAddress(),
    owner.address,
    owner.address,
    await coordinator.getAddress()
  );
  const executor = await deploy("GraphArbExecutor", owner.address, await capture.getAddress());

  await (await usdx.setEngine(await engine.getAddress(), true)).wait();
  await (await capture.setController(await engine.getAddress())).wait();
  await (await capture.setCollector(await executor.getAddress(), true)).wait();
  await (await coordinator.setEngine(await engine.getAddress(), true)).wait();

  await (await executor.setGradientEngine(await engine.getAddress(), true)).wait();
  await (await executor.setProtocolNAVGuard(await adapter.getAddress(), true, E("0.05"))).wait();
  await (await executor.setMaxOracleErrorBps(0)).wait();
  await (await executor.setProfitTaxBps(9900)).wait();
  await (await executor.setMinSearcherReward(await tokenB.getAddress(), E("0.001"))).wait();

  for (const pool of [source, destination]) {
    await (await pool.setLiquidityManager(owner.address, true)).wait();
    await (await pool.setGradientController(await engine.getAddress())).wait();
    await (await pool.setArbExecutor(await executor.getAddress(), true)).wait();
    await (await pool.setExecutorOnlyAllSwaps(true)).wait();
    await (await executor.setVenue(await pool.getAddress(), await pool.getAddress(), true)).wait();
    await (await executor.setProtocolTarget(await pool.getAddress(), true)).wait();
    await (await executor.setBaseTokenGate(await pool.getAddress(), true)).wait();
    await (await executor.setAllowedBaseToken(await pool.getAddress(), await tokenB.getAddress(), true)).wait();
    await (await adapter.setSyntheticPoolAccount(await pool.getAddress(), true)).wait();
  }
  await (await adapter.setSyntheticProtocolAccount(await capture.getAddress(), true)).wait();
  await (await executor.setVenue(await external.getAddress(), await external.getAddress(), true)).wait();

  const hardTokens = [await tokenA.getAddress(), await tokenB.getAddress()];
  await (await oracle.updatePrices(hardTokens, [E(1), E(1)])).wait();
  await (await validationOracle.updatePrices(hardTokens, [E(1), E(1)])).wait();
  await (await ledger.permanentlyExcludeAsset(await usdx.getAddress())).wait();

  await mustRevert(
    adapter.setGradientEngine(await engine.getAddress(), true),
    "gradient engine must require frozen independent Economic validation oracle"
  );
  await (await ledger.setValidationOracle(await validationOracle.getAddress(), true)).wait();
  await (await risk.setValidatedCanonicalAnchor(await ledger.getAddress(), true)).wait();
  assert.equal(await ledger.oracleValidationReady(), true);
  assert.equal(await risk.validatedAnchorReady(), true);
  await mustRevert(
    adapter.setGradientEngine(await engine.getAddress(), true),
    "validator-ready but empty hard-asset ledger must still be non-activatable"
  );
  await mustRevert(
    ledger.setValidationOracle(await oracle.getAddress(), false),
    "validation oracle freeze must be irreversible"
  );

  // Full Economic balance sheet comes BEFORE monetary-engine registration.
  await (await ledger.addHardAsset(await tokenA.getAddress())).wait();
  await (await ledger.addHardAsset(await tokenB.getAddress())).wait();
  await (await ledger.setHardAccount(await tokenA.getAddress(), await source.getAddress(), true)).wait();
  await (await ledger.setHardAccount(await tokenB.getAddress(), await destination.getAddress(), true)).wait();
  await (await ledger.setHardAccount(await tokenB.getAddress(), await capture.getAddress(), true)).wait();

  const liabilityId = ethers.keccak256(ethers.toUtf8Bytes("EXTERNAL_USDX"));
  await (await liabilities.addLiability(liabilityId, 18, E(1), 10000, ethers.ZeroAddress, E(100))).wait();
  assert.equal(await ledger.oracleValidationCoversAllAssets(), true);
  await (await adapter.setGradientEngine(await engine.getAddress(), true)).wait();

  await (await risk.setHaircut(await tokenA.getAddress(), 10000)).wait();
  await (await risk.setHaircut(await tokenB.getAddress(), bHaircutBps)).wait();
  await (await risk.setRiskData(await tokenA.getAddress(), E(1), E(1))).wait();
  await (await risk.setRiskData(await tokenB.getAddress(), E(1), E(1))).wait();
  await (await risk.addScenario(ethers.encodeBytes32String("BASE"), 10000, 0)).wait();
  await (await risk.setScenarioAsset(0, await tokenA.getAddress(), 10000, 10000)).wait();
  await (await risk.setScenarioAsset(0, await tokenB.getAddress(), 10000, 10000)).wait();

  await (await controller.pokeMode()).wait();
  await (await controller.pokeMode()).wait();
  await (await controller.pokeMode()).wait();
  assert.equal(await controller.mode(), 0n, "pre-state must be GREEN");
  assert.equal(await controller.searcherRouteAllowed(), true, "validated Economic+Risk anchors must unlock execution");

  await (await engine.setGradientPool(await source.getAddress(), true)).wait();
  await (await engine.setGradientPool(await destination.getAddress(), true)).wait();
  await (await coordinator.initializeGradient(
    await engine.getAddress(), await source.getAddress(), await destination.getAddress(), E(40)
  )).wait();

  return {
    owner, solver, tokenA, tokenB, usdx, capture, oracle, validationOracle, ledger, risk,
    liabilities, liabilityId, controller, adapter, coordinator, source, destination,
    external, engine, executor
  };
}

async function route(ctx, principal = E("39.8")) {
  const syn = (await ctx.destination.quoteExactIn(false, principal))[0];
  const aOut = (await ctx.source.quoteExactIn(true, syn))[0];
  const bOut = (await ctx.external.quoteExactIn(true, aOut))[0];
  const ex = await ctx.executor.getAddress();
  return {
    bOut,
    legs: [
      {
        target: await ctx.destination.getAddress(), spender: await ctx.destination.getAddress(),
        tokenIn: await ctx.tokenB.getAddress(), tokenOut: await ctx.usdx.getAddress(),
        amountIn: principal, minAmountOut: syn,
        data: ctx.destination.interface.encodeFunctionData("swapExactIn", [false, principal, syn, ex])
      },
      {
        target: await ctx.source.getAddress(), spender: await ctx.source.getAddress(),
        tokenIn: await ctx.usdx.getAddress(), tokenOut: await ctx.tokenA.getAddress(),
        amountIn: syn, minAmountOut: aOut,
        data: ctx.source.interface.encodeFunctionData("swapExactIn", [true, syn, aOut, ex])
      },
      {
        target: await ctx.external.getAddress(), spender: await ctx.external.getAddress(),
        tokenIn: await ctx.tokenA.getAddress(), tokenOut: await ctx.tokenB.getAddress(),
        amountIn: aOut, minAmountOut: bOut,
        data: ctx.external.interface.encodeFunctionData("swapExactIn", [true, aOut, bOut, ex])
      }
    ]
  };
}

async function execute(ctx, principal = E("39.8")) {
  const r = await route(ctx, principal);
  assert.ok(r.bOut > principal, "raw gradient route must be solver-profitable");
  await (await ctx.tokenB.connect(ctx.solver).approve(await ctx.executor.getAddress(), principal)).wait();
  const block = await ethers.provider.getBlock("latest");
  return ctx.executor.connect(ctx.solver).executeCycle(
    await ctx.tokenB.getAddress(), principal, E("0.001"), r.legs, BigInt(block.timestamp + 600)
  );
}

describe("V15 overlay over frozen V13.1", function () {
  this.timeout(120000);

  it("uses the lower of independent Economic feeds so one feed cannot inflate NAV", async function () {
    const c = await fixture(10000);
    const before = await c.ledger.hardNAV1e18();
    await (await c.oracle.updatePrice(await c.tokenA.getAddress(), E(2))).wait();
    assert.equal(await c.ledger.canonicalPrice1e18(await c.tokenA.getAddress()), E(1));
    assert.equal(await c.ledger.hardNAV1e18(), before, "one high feed must not inflate Economic NAV");
  });

  it("accepts the known latent-basis V13.1 route when Economic HardNAV and K/STS both pass", async function () {
    const c = await fixture(10000);
    const navBefore = await c.ledger.hardNAV1e18();
    await (await execute(c)).wait();
    const navAfter = await c.ledger.hardNAV1e18();
    assert.ok(navAfter >= navBefore + E("0.05"));
    assert.equal(await c.controller.routeSolvent(), true);
    await (await c.coordinator.restoreGradient(await c.engine.getAddress())).wait();
    assert.equal(await c.source.reserve0(), E(60));
    assert.equal(await c.destination.reserve0(), E(140));
  });

  it("reverts the same Economic-HardNAV-positive route when post-route risk K/STS crosses the GREEN floor", async function () {
    const c = await fixture(4000);
    const navBefore = await c.ledger.hardNAV1e18();
    const source0 = await c.source.reserve0();
    const destination0 = await c.destination.reserve0();
    assert.equal(await c.controller.routeSolvent(), true, "pre-state must pass risk gate");

    await mustRevert(execute(c), "post-route K/STS breach must atomically revert V13.1 execution");

    assert.equal(await c.ledger.hardNAV1e18(), navBefore, "reverted route must not change Economic HardNAV");
    assert.equal(await c.source.reserve0(), source0);
    assert.equal(await c.destination.reserve0(), destination0);
  });

  it("blocks new direct searcher exploitation once mode falls to ORANGE", async function () {
    const c = await fixture(10000);
    await (await c.liabilities.setManualAmount(c.liabilityId, E(180))).wait();
    await (await c.controller.pokeMode()).wait();
    await (await c.controller.pokeMode()).wait();
    assert.equal(await c.controller.mode(), 2n);
    assert.equal(await c.controller.routeSolvent(), true, "ORANGE should retain survival/restore ability");
    assert.equal(await c.controller.searcherRouteAllowed(), false);
    await mustRevert(execute(c), "ORANGE must block direct frozen executor exploitation");
  });

  it("can restore and close an already-active gradient after a liability shock drives the system to RED", async function () {
    const c = await fixture(10000);
    await (await execute(c)).wait();
    assert.ok((await c.source.reserve0()) > E(60), "exploitation must displace synthetic into source");
    assert.ok((await c.destination.reserve0()) < E(140), "exploitation must remove synthetic from destination");

    await (await c.liabilities.setManualAmount(c.liabilityId, E(195))).wait();
    await (await c.controller.pokeMode()).wait();
    assert.equal(await c.controller.mode(), 3n, "shock must force RED");
    assert.equal(await c.controller.searcherRouteAllowed(), false);

    await (await c.coordinator.restoreGradient(await c.engine.getAddress())).wait();
    assert.equal(await c.source.reserve0(), E(60));
    assert.equal(await c.destination.reserve0(), E(140));

    await (await c.coordinator.closeGradient(await c.engine.getAddress())).wait();
    assert.equal(await c.source.reserve0(), E(100));
    assert.equal(await c.destination.reserve0(), E(100));
  });
});
