const assert = require("node:assert/strict");
const { ethers } = require("hardhat");

const E = (x) => ethers.parseEther(String(x));

async function deploy(name, ...args) {
  const F = await ethers.getContractFactory(name);
  const c = await F.deploy(...args);
  await c.waitForDeployment();
  return c;
}

describe("SynthL1 V6 supply-neutral reserve gradient", function () {
  this.timeout(120000);

  it("initiates, taxes, restores, reinvests and closes one external-searcher cycle", async function () {
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
    await (await tokenA.mint(owner.address, E(10100))).wait();
    await (await tokenB.mint(owner.address, E(10100))).wait();
    await (await tokenB.mint(solver.address, E(100))).wait();

    const source = await deploy(
      "GraphPool", await usdx.getAddress(), await tokenA.getAddress(), await capture.getAddress(), owner.address
    );
    const destination = await deploy(
      "GraphPool", await usdx.getAddress(), await tokenB.getAddress(), await capture.getAddress(), owner.address
    );
    const external = await deploy(
      "GraphPool", await tokenA.getAddress(), await tokenB.getAddress(), await capture.getAddress(), owner.address
    );

    await (await usdx.approve(await source.getAddress(), ethers.MaxUint256)).wait();
    await (await usdx.approve(await destination.getAddress(), ethers.MaxUint256)).wait();
    await (await tokenA.approve(await source.getAddress(), ethers.MaxUint256)).wait();
    await (await tokenB.approve(await destination.getAddress(), ethers.MaxUint256)).wait();
    await (await tokenA.approve(await external.getAddress(), ethers.MaxUint256)).wait();
    await (await tokenB.approve(await external.getAddress(), ethers.MaxUint256)).wait();

    await (await source.addLiquidity(E(100), E(100), 0)).wait();
    await (await destination.addLiquidity(E(100), E(100), 0)).wait();
    await (await external.addLiquidity(E(10000), E(10000), 0)).wait();

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

      // Production invariant: every managed gradient pool must be visible to the
      // executor's HardNAV-turnover uncertainty accounting before activation.
      await (await executor.setVenue(await pool.getAddress(), await pool.getAddress(), true)).wait();
      await (await executor.setProtocolTarget(await pool.getAddress(), true)).wait();
    }
    await (await accounting.addProtocolUSDxAccount(await capture.getAddress())).wait();

    await (await oracle.updatePrices(
      [await tokenA.getAddress(), await tokenB.getAddress()], [E(1), E(1)]
    )).wait();
    await (await accounting.addHardAsset(await tokenA.getAddress(), 10000)).wait();
    await (await accounting.addHardAsset(await tokenB.getAddress(), 10000)).wait();
    await (await accounting.addHardAccount(await tokenA.getAddress(), await source.getAddress())).wait();
    await (await accounting.addHardAccount(await tokenB.getAddress(), await destination.getAddress())).wait();
    await (await accounting.addHardAccount(await tokenB.getAddress(), await capture.getAddress())).wait();
    assert.equal(await accounting.hardAccountCount(await tokenA.getAddress()), 1n);
    assert.equal(await accounting.hardAccountCount(await tokenB.getAddress()), 2n);

    await (await engine.setGradientPool(await source.getAddress(), true)).wait();
    await (await engine.setGradientPool(await destination.getAddress(), true)).wait();

    const supply0 = await usdx.totalSupply();
    await (await engine.initializeGradient(await source.getAddress(), await destination.getAddress(), E(40))).wait();

    assert.equal(await usdx.totalSupply(), supply0);
    assert.equal(await source.reserve0(), E(60));
    assert.equal(await destination.reserve0(), E(140));

    await (await executor.setVenue(await external.getAddress(), await external.getAddress(), true)).wait();
    for (const pool of [source, destination]) {
      await (await executor.setBaseTokenGate(await pool.getAddress(), true)).wait();
      await (await executor.setAllowedBaseToken(await pool.getAddress(), await tokenB.getAddress(), true)).wait();
    }
    await (await executor.setProfitTaxBps(9900)).wait();
    await (await executor.setMinSearcherReward(await tokenB.getAddress(), E("0.001"))).wait();

    const principal = E("15.5");
    const syntheticOut = (await destination.quoteExactIn(false, principal))[0];
    const quoteAOut = (await source.quoteExactIn(true, syntheticOut))[0];
    const grossReturnedB = (await external.quoteExactIn(true, quoteAOut))[0];
    assert.ok(grossReturnedB > principal, "initiated gradient should create searcher edge");

    const executorAddress = await executor.getAddress();
    const legs = [
      {
        target: await destination.getAddress(), spender: await destination.getAddress(),
        tokenIn: await tokenB.getAddress(), tokenOut: await usdx.getAddress(),
        amountIn: principal, minAmountOut: syntheticOut,
        data: destination.interface.encodeFunctionData("swapExactIn", [false, principal, syntheticOut, executorAddress])
      },
      {
        target: await source.getAddress(), spender: await source.getAddress(),
        tokenIn: await usdx.getAddress(), tokenOut: await tokenA.getAddress(),
        amountIn: syntheticOut, minAmountOut: quoteAOut,
        data: source.interface.encodeFunctionData("swapExactIn", [true, syntheticOut, quoteAOut, executorAddress])
      },
      {
        target: await external.getAddress(), spender: await external.getAddress(),
        tokenIn: await tokenA.getAddress(), tokenOut: await tokenB.getAddress(),
        amountIn: quoteAOut, minAmountOut: grossReturnedB,
        data: external.interface.encodeFunctionData("swapExactIn", [true, quoteAOut, grossReturnedB, executorAddress])
      }
    ];

    await (await tokenB.connect(solver).approve(executorAddress, principal)).wait();
    const block = await ethers.provider.getBlock("latest");
    await (await executor.connect(solver).executeCycle(
      await tokenB.getAddress(), principal, E("0.001"), legs, BigInt(block.timestamp + 600)
    )).wait();

    const capturedB = await tokenB.balanceOf(await capture.getAddress());
    assert.ok(capturedB > 0n, "realized-profit tax must be physically captured");
    assert.equal(await usdx.totalSupply(), supply0);

    await (await engine.restoreGradient()).wait();
    assert.equal(await source.reserve0(), E(60));
    assert.equal(await destination.reserve0(), E(140));
    assert.equal(await usdx.totalSupply(), supply0);
    assert.equal(await engine.exploitations(), 1n);

    const destinationQuoteBefore = await destination.reserve1();
    await (await engine.reinvestCapturedQuote(await destination.getAddress(), capturedB)).wait();
    assert.equal(await tokenB.balanceOf(await capture.getAddress()), 0n);
    assert.equal(await destination.reserve1(), destinationQuoteBefore + capturedB);

    await (await engine.closeGradient()).wait();
    assert.equal(await source.reserve0(), E(100));
    assert.equal(await destination.reserve0(), E(100));
    assert.equal(await usdx.totalSupply(), supply0);
    assert.equal(await engine.active(), false);
  });
});
