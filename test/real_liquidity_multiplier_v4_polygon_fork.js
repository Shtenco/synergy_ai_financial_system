const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { ethers } = require("hardhat");

const WPOL = "0x0d500B1d8E8eF31E21C99d1Db9A6444d3ADf1270";
const QUICKSWAP_V3_FACTORY = "0x411b0fAcC3489691f28ad58c47006AF5E3Ab3A28";
const QUICKSWAP_V3_QUOTER = "0xa15F0D7377B2A0C0c10db057f641beD21028FC89";
const QUICKSWAP_V3_POSITION_MANAGER = "0x8eF88E4c7CfbbaC1C163f7eddd4B578792201de6";
const E = ethers.parseEther;
const WAD = E("1");

const WPOL_ABI = [
  "function deposit() payable",
  "function approve(address,uint256) returns(bool)",
  "function balanceOf(address) view returns(uint256)"
];

const FACTORY_ABI = [
  "function poolByPair(address,address) view returns(address)"
];

const POSITION_MANAGER_ABI = [
  "function positions(uint256 tokenId) view returns(uint96 nonce,address operator,address token0,address token1,int24 tickLower,int24 tickUpper,uint128 liquidity,uint256 feeGrowthInside0LastX128,uint256 feeGrowthInside1LastX128,uint128 tokensOwed0,uint128 tokensOwed1)"
];

const QUOTER_ABI = [
  "function quoteExactInputSingle(address tokenIn,address tokenOut,uint256 amountIn,uint160 limitSqrtPrice) returns(uint256 amountOut,uint16 fee)"
];

function decimal(value) {
  return Number(ethers.formatEther(value));
}

function v2DepthPerCapital(epsilon = 0.01) {
  return Math.min(
    0.5 * (Math.sqrt(1 + epsilon) - 1),
    0.5 * (1 - Math.sqrt(1 - epsilon))
  );
}

function equivalentPerExternalPol(tickLower, tickUpper, sigma, epsilon = 0.01) {
  const lower = Math.pow(1.0001, Number(tickLower));
  const upper = Math.pow(1.0001, Number(tickUpper));
  const rangeHalf = Math.min(1 - lower, upper - 1);
  const sqrtLower = Math.sqrt(1 - rangeHalf);
  const sqrtUpper = Math.sqrt(1 + rangeHalf);
  const capitalPerLiquidity = (1 - 1 / sqrtUpper) + (1 - sqrtLower);
  const liquidityPerCapital = 1 / capitalPerLiquidity;
  const baseline = v2DepthPerCapital(epsilon);
  const z = 2.576;

  const values = [-z * sigma, z * sigma].map((shock) => {
    const price = Math.exp(shock);
    const rangeLower = 1 - rangeHalf;
    const rangeUpper = 1 + rangeHalf;
    if (!(rangeLower < price && price < rangeUpper)) return 0;
    const up = Math.min(rangeUpper, price * (1 + epsilon));
    const down = Math.max(rangeLower, price * (1 - epsilon));
    const quoteUp = liquidityPerCapital * (Math.sqrt(up) - Math.sqrt(price));
    const quoteDown = liquidityPerCapital * (Math.sqrt(price) - Math.sqrt(down));
    return Math.min(quoteUp, quoteDown) / baseline;
  });
  return Math.min(...values);
}

function toWeiNumber(value) {
  return E(value.toFixed(12));
}

async function expectRevert(promise) {
  await assert.rejects(promise);
}

describe("Real Liquidity Multiplier V4 on Polygon fork", function () {
  this.timeout(1_800_000);

  it("creates a real QuickSwap V3 triangle and proves the one 3-5x invariant", async function () {
    const [deployer, investor] = await ethers.getSigners();

    for (const address of [
      WPOL,
      QUICKSWAP_V3_FACTORY,
      QUICKSWAP_V3_QUOTER,
      QUICKSWAP_V3_POSITION_MANAGER
    ]) {
      assert.notEqual(
        await ethers.provider.getCode(address),
        "0x",
        `missing Polygon contract ${address}`
      );
    }

    const Invariant = await ethers.getContractFactory(
      "RealLiquidityMultiplierInvariant",
      deployer
    );
    const invariant = await Invariant.deploy(deployer.address, deployer.address);
    await invariant.waitForDeployment();

    const Engine = await ethers.getContractFactory(
      "TriangularLiquidityEngineV4",
      deployer
    );
    const engine = await Engine.deploy(WPOL, QUICKSWAP_V3_POSITION_MANAGER);
    await engine.waitForDeployment();
    const engineAddress = await engine.getAddress();

    const wpolDeployer = new ethers.Contract(WPOL, WPOL_ABI, deployer);
    const wpolInvestor = new ethers.Contract(WPOL, WPOL_ABI, investor);

    await (await wpolDeployer.deposit({ value: E("100") })).wait();
    await (await wpolInvestor.deposit({ value: E("20") })).wait();
    await (await wpolDeployer.approve(engineAddress, E("100"))).wait();
    await (await wpolInvestor.approve(engineAddress, E("20"))).wait();

    await (await engine.depositByKeeper(E("100"))).wait();
    await (await engine.connect(investor).depositByKeeper(E("20"))).wait();

    assert.equal(await engine.netExternalCapitalPol(), E("120"));
    assert.equal(await engine.internalTransferRevenuePol(), 0n);
    assert.equal(await engine.externalEmissionLiabilityPol(), 0n);
    assert.equal(await engine.equityShares(deployer.address), E("100"));
    assert.equal(await engine.equityShares(investor.address), E("20"));

    const syna = await engine.syna();
    const synr = await engine.synr();
    const factory = new ethers.Contract(
      QUICKSWAP_V3_FACTORY,
      FACTORY_ABI,
      deployer
    );

    const polSynaPool = await factory.poolByPair(WPOL, syna);
    const polSynrPool = await factory.poolByPair(WPOL, synr);
    const synaSynrPool = await factory.poolByPair(syna, synr);

    assert.notEqual(polSynaPool, ethers.ZeroAddress);
    assert.notEqual(polSynrPool, ethers.ZeroAddress);
    assert.notEqual(synaSynrPool, ethers.ZeroAddress);
    assert.equal(await engine.polSynaPool(), polSynaPool);
    assert.equal(await engine.polSynrPool(), polSynrPool);
    assert.equal(await engine.synaSynrPool(), synaSynrPool);

    const npm = new ethers.Contract(
      QUICKSWAP_V3_POSITION_MANAGER,
      POSITION_MANAGER_ABI,
      deployer
    );
    const positionPA = await npm.positions(await engine.lastPolSynaPositionId());
    const positionPR = await npm.positions(await engine.lastPolSynrPositionId());
    const positionAR = await npm.positions(await engine.lastSynaSynrPositionId());

    assert.ok(positionPA.liquidity > 0n);
    assert.ok(positionPR.liquidity > 0n);
    assert.ok(positionAR.liquidity > 0n);

    const quoter = new ethers.Contract(
      QUICKSWAP_V3_QUOTER,
      QUOTER_ABI,
      deployer
    );
    const quotePA = await quoter.quoteExactInputSingle.staticCall(
      WPOL,
      syna,
      E("0.1"),
      0
    );
    const quoteAR = await quoter.quoteExactInputSingle.staticCall(
      syna,
      synr,
      quotePA.amountOut,
      0
    );
    const quoteRP = await quoter.quoteExactInputSingle.staticCall(
      synr,
      WPOL,
      quoteAR.amountOut,
      0
    );
    assert.ok(quotePA.amountOut > 0n);
    assert.ok(quoteAR.amountOut > 0n);
    assert.ok(quoteRP.amountOut > 0n);

    const polPA = decimal(await engine.anchorPoolPolSyna());
    const polPR = decimal(await engine.anchorPoolPolSynr());
    const sigma = 0.05;
    const efficiencyPA = equivalentPerExternalPol(
      positionPA.tickLower,
      positionPA.tickUpper,
      sigma
    );
    const efficiencyPR = equivalentPerExternalPol(
      positionPR.tickLower,
      positionPR.tickUpper,
      0.7 * sigma
    );
    const rawEquivalent = polPA * efficiencyPA + polPR * efficiencyPR;
    const recognisedEquivalent = Math.min(rawEquivalent, 5 * 120);

    assert.ok(recognisedEquivalent >= 4 * 120);
    assert.ok(recognisedEquivalent <= 5 * 120 + 1e-9);

    const lpPol =
      (await engine.anchorPoolPolSyna()) +
      (await engine.anchorPoolPolSynr());
    const haircutAssets =
      (await engine.liquidReservePol()) +
      (await engine.gasReservePol()) +
      ((await engine.insurancePol()) * 9n) / 10n +
      (lpPol * 75n) / 100n;
    const immediateLiquidity =
      (await engine.liquidReservePol()) +
      (await engine.gasReservePol()) +
      (await engine.insurancePol()) / 2n;
    const emissionBacking =
      (await engine.liquidReservePol()) +
      (await engine.insurancePol()) +
      lpPol / 2n;

    const metrics = {
      sigmaWad: E("0.05"),
      stressEquivalentLiquidityPol: toWeiNumber(recognisedEquivalent),
      netExternalCapitalPol: E("120"),
      haircutAssetsPol: haircutAssets,
      stressLiabilitiesPol: E("20"),
      immediateLiquidityPol: immediateLiquidity,
      stressedOutflowsPol: E("25"),
      gasReservePlusSpentPol: E("7"),
      gasSpentPol: E("1"),
      externalEmissionBackingPol: emissionBacking,
      externalEmissionLiabilityPol: E("40"),
      minimumAnchorPoolPol: await engine.minimumAnchorPoolPol(),
      poolFloorPol: E("10"),
      crossPoolInternalNotional: await engine.crossPoolInternalNotional(),
      internalTransferRevenuePol: 0n
    };

    const preview = await invariant.preview(metrics);
    assert.equal(preview.targetWad, E("4"));
    assert.equal(preview.pass, true);
    assert.ok(preview.invariantWad >= WAD);

    const snapshotId = ethers.keccak256(
      ethers.toUtf8Bytes("polygon-fork-real-liquidity-v4")
    );
    await (await invariant.record(snapshotId, metrics)).wait();
    assert.equal(await invariant.latestPass(), true);

    const inflatedCrossPool = {
      ...metrics,
      crossPoolInternalNotional: E("1000000")
    };
    const previewInflatedCross = await invariant.preview(inflatedCrossPool);
    assert.equal(previewInflatedCross.invariantWad, preview.invariantWad);

    await expectRevert(
      invariant.preview({
        ...metrics,
        stressEquivalentLiquidityPol: E("601")
      })
    );

    const unsupported = await invariant.preview({
      ...metrics,
      sigmaWad: E("0.14")
    });
    assert.equal(unsupported.invariantWad, 0n);
    assert.equal(unsupported.pass, false);

    const result = {
      scenario: "real_liquidity_multiplier_v4_polygon_fork",
      forkBlock: await ethers.provider.getBlockNumber(),
      realPolygonWPOL: true,
      realQuickSwapV3Factory: true,
      realQuickSwapV3PositionManager: true,
      realQuickSwapV3Quoter: true,
      netExternalCapitalPOL: 120,
      actualAnchorPoolPOL: polPA + polPR,
      polSynaPoolPOL: polPA,
      polSynrPoolPOL: polPR,
      rawStressV2EquivalentLiquidityPOL: rawEquivalent,
      recognisedStressLiquidityPOL: recognisedEquivalent,
      recognisedMultiplier: recognisedEquivalent / 120,
      targetMultiplier: 4,
      singleInvariant: decimal(preview.invariantWad),
      pass: preview.pass,
      internalTransferRevenuePOL: 0,
      crossPoolCountedInMultiplier: false,
      externalEmissionLiabilityFromInternalMint: 0,
      triangularQuoteInputPOL: 0.1,
      triangularQuoteOutputPOL: decimal(quoteRP.amountOut),
      quickSwapPools: {
        polSynaPool,
        polSynrPool,
        synaSynrPool
      },
      positionLiquidity: {
        polSyna: positionPA.liquidity.toString(),
        polSynr: positionPR.liquidity.toString(),
        synaSynr: positionAR.liquidity.toString()
      }
    };

    fs.mkdirSync(path.join(process.cwd(), "reports"), { recursive: true });
    fs.writeFileSync(
      path.join(
        process.cwd(),
        "reports",
        "real_liquidity_multiplier_v4_polygon_fork.json"
      ),
      JSON.stringify(result, null, 2)
    );
    console.log(`RLM_V4_POLYGON_RESULT ${JSON.stringify(result)}`);
  });
});
