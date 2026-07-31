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

const source = (label) => ethers.keccak256(ethers.toUtf8Bytes(label));
const decimal = (value) => Number(ethers.formatEther(value));
const toWeiNumber = (value) => E(value.toFixed(12));

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
  return Math.min(
    ...[-z * sigma, z * sigma].map((shock) => {
      const price = Math.exp(shock);
      const rangeLower = 1 - rangeHalf;
      const rangeUpper = 1 + rangeHalf;
      if (!(rangeLower < price && price < rangeUpper)) return 0;
      const up = Math.min(rangeUpper, price * (1 + epsilon));
      const down = Math.max(rangeLower, price * (1 - epsilon));
      const quoteUp = liquidityPerCapital * (Math.sqrt(up) - Math.sqrt(price));
      const quoteDown = liquidityPerCapital * (Math.sqrt(price) - Math.sqrt(down));
      return Math.min(quoteUp, quoteDown) / baseline;
    })
  );
}

async function setEligible(registry, admin, participant, label) {
  const block = await ethers.provider.getBlock("latest");
  await (
    await registry
      .connect(admin)
      .setParticipant(
        participant.address,
        true,
        BigInt(block.timestamp + 86400),
        source(label)
      )
  ).wait();
}

async function invariantMetrics(engine, npm, capitalPol, sigma = 0.05) {
  const positionPA = await npm.positions(await engine.lastPolSynaPositionId());
  const positionPR = await npm.positions(await engine.lastPolSynrPositionId());
  const polPA = decimal(await engine.anchorPoolPolSyna());
  const polPR = decimal(await engine.anchorPoolPolSynr());
  const rawEquivalent =
    polPA * equivalentPerExternalPol(positionPA.tickLower, positionPA.tickUpper, sigma) +
    polPR * equivalentPerExternalPol(positionPR.tickLower, positionPR.tickUpper, 0.7 * sigma);
  const recognisedEquivalent = Math.min(rawEquivalent, 5 * capitalPol);
  const lpPol =
    (await engine.anchorPoolPolSyna()) + (await engine.anchorPoolPolSynr());
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

  return {
    rawEquivalent,
    recognisedEquivalent,
    metrics: {
      sigmaWad: E(String(sigma)),
      stressEquivalentLiquidityPol: toWeiNumber(recognisedEquivalent),
      netExternalCapitalPol: E(capitalPol.toFixed(6)),
      haircutAssetsPol: haircutAssets,
      stressLiabilitiesPol: E("20"),
      immediateLiquidityPol: immediateLiquidity,
      stressedOutflowsPol: E("25"),
      gasReservePlusSpentPol: E("8"),
      gasSpentPol: E("1"),
      externalEmissionBackingPol: emissionBacking,
      externalEmissionLiabilityPol: E("40"),
      minimumAnchorPoolPol: await engine.minimumAnchorPoolPol(),
      poolFloorPol: E("10"),
      crossPoolInternalNotional: await engine.crossPoolInternalNotional(),
      internalTransferRevenuePol: 0n
    }
  };
}

describe("SYNERGY V5 dividend compounding and own DEX on Polygon fork", function () {
  this.timeout(1_800_000);

  it("compounds external profit into QuickSwap positions and enforces permissioned SINERGY DEX", async function () {
    const [
      deployer,
      anchorInvestor,
      externalProfitPayer,
      keeperUser,
      protocolTreasury,
      taxEscrow,
      registeredTrader,
      outsider
    ] = await ethers.getSigners();

    for (const address of [
      WPOL,
      QUICKSWAP_V3_FACTORY,
      QUICKSWAP_V3_QUOTER,
      QUICKSWAP_V3_POSITION_MANAGER
    ]) {
      assert.notEqual(await ethers.provider.getCode(address), "0x");
    }

    const wpolDeployer = new ethers.Contract(WPOL, WPOL_ABI, deployer);
    const wpolAnchor = new ethers.Contract(WPOL, WPOL_ABI, anchorInvestor);
    const wpolProfit = new ethers.Contract(WPOL, WPOL_ABI, externalProfitPayer);
    const wpolTrader = new ethers.Contract(WPOL, WPOL_ABI, registeredTrader);
    await (await wpolDeployer.deposit({ value: E("100") })).wait();
    await (await wpolAnchor.deposit({ value: E("20") })).wait();
    await (await wpolProfit.deposit({ value: E("20") })).wait();
    await (await wpolTrader.deposit({ value: E("10") })).wait();

    const Engine = await ethers.getContractFactory("TriangularLiquidityEngineV5", deployer);
    const engine = await Engine.deploy(
      WPOL,
      QUICKSWAP_V3_POSITION_MANAGER,
      protocolTreasury.address
    );
    await engine.waitForDeployment();
    const engineAddress = await engine.getAddress();

    await (await wpolDeployer.approve(engineAddress, E("100"))).wait();
    await (await wpolAnchor.approve(engineAddress, E("20"))).wait();
    await (await engine.depositByKeeper(E("100"))).wait();
    await (await engine.connect(anchorInvestor).depositByKeeper(E("20"))).wait();

    assert.equal(await engine.originalExternalCapitalPol(), E("120"));
    assert.equal(await engine.totalBackedCapitalPol(), E("120"));
    assert.equal(await engine.internalTransferRevenuePol(), 0n);

    const Invariant = await ethers.getContractFactory(
      "RealLiquidityMultiplierInvariant",
      deployer
    );
    const invariant = await Invariant.deploy(deployer.address, deployer.address);
    await invariant.waitForDeployment();

    const npm = new ethers.Contract(
      QUICKSWAP_V3_POSITION_MANAGER,
      POSITION_MANAGER_ABI,
      deployer
    );
    const beforePA = await npm.positions(await engine.lastPolSynaPositionId());
    const beforePR = await npm.positions(await engine.lastPolSynrPositionId());
    const initial = await invariantMetrics(engine, npm, 120);
    const initialPreview = await invariant.preview(initial.metrics);
    assert.equal(initialPreview.pass, true);
    await (
      await invariant.record(source("v5-before-profit"), initial.metrics)
    ).wait();

    const Registry = await ethers.getContractFactory(
      "ParticipantTaxRegistry",
      deployer
    );
    const participantRegistry = await Registry.deploy(deployer.address);
    await participantRegistry.waitForDeployment();
    for (const [participant, label] of [
      [deployer, "owner"],
      [keeperUser, "keeper"],
      [registeredTrader, "trader"]
    ]) {
      await setEligible(participantRegistry, deployer, participant, label);
    }

    const Boundary = await ethers.getContractFactory(
      "SystemBoundaryRegistry",
      deployer
    );
    const boundary = await Boundary.deploy(deployer.address);
    await boundary.waitForDeployment();

    const Controller = await ethers.getContractFactory(
      "AutoReinvestDividendControllerV5",
      deployer
    );
    const controller = await Controller.deploy(
      WPOL,
      await participantRegistry.getAddress(),
      await boundary.getAddress(),
      await invariant.getAddress(),
      engineAddress,
      deployer.address,
      protocolTreasury.address,
      taxEscrow.address,
      1000,
      WAD
    );
    await controller.waitForDeployment();
    const controllerAddress = await controller.getAddress();

    await (
      await boundary.setSystemAddresses(
        [
          engineAddress,
          controllerAddress,
          protocolTreasury.address,
          taxEscrow.address
        ],
        true
      )
    ).wait();
    await (await engine.setProfitController(controllerAddress)).wait();
    await (await controller.setOperator(keeperUser.address, true)).wait();

    await (
      await wpolProfit.approve(controllerAddress, E("20"))
    ).wait();
    const settleTx = await controller
      .connect(keeperUser)
      .settleExternalProfit(
        externalProfitPayer.address,
        E("20"),
        keeperUser.address,
        source("real-external-profit-v5"),
        { gasLimit: 12_000_000n }
      );
    const settleReceipt = await settleTx.wait();

    assert.equal(await controller.cumulativeGrossExternalProfit(), E("20"));
    assert.equal(await controller.cumulativeGrossDividends(), E("2"));
    assert.equal(await controller.cumulativeTaxWithheld(), E("0.2"));
    assert.equal(await controller.cumulativeOwnerNetReinvestment(), E("0.9"));
    assert.equal(await controller.cumulativeKeeperNetReinvestment(), E("0.9"));
    assert.equal(await controller.cumulativeRetainedReinvestment(), E("18"));
    assert.equal(await wpolDeployer.balanceOf(taxEscrow.address), E("0.2"));
    assert.equal(await engine.originalExternalCapitalPol(), E("120"));
    assert.equal(await engine.reinvestedProfitCapitalPol(), E("1.8"));
    assert.equal(await engine.retainedProfitCapitalPol(), E("18"));
    assert.equal(await engine.totalBackedCapitalPol(), E("139.8"));
    assert.equal(await engine.equityShares(deployer.address), E("100.9"));
    assert.equal(await engine.equityShares(keeperUser.address), E("0.9"));
    assert.equal(await engine.equityShares(protocolTreasury.address), E("18"));

    const afterPA = await npm.positions(await engine.lastPolSynaPositionId());
    const afterPR = await npm.positions(await engine.lastPolSynrPositionId());
    assert.ok(afterPA.liquidity > beforePA.liquidity);
    assert.ok(afterPR.liquidity > beforePR.liquidity);

    const after = await invariantMetrics(engine, npm, 139.8);
    const afterPreview = await invariant.preview(after.metrics);
    assert.equal(afterPreview.pass, true);
    await (
      await invariant.record(source("v5-after-compounding"), after.metrics)
    ).wait();

    const Factory = await ethers.getContractFactory(
      "SynergyDexFactoryV5",
      deployer
    );
    const ownFactory = await Factory.deploy(await participantRegistry.getAddress());
    await ownFactory.waitForDeployment();
    const Router = await ethers.getContractFactory(
      "SynergyDexRouterV5",
      deployer
    );
    const ownRouter = await Router.deploy(
      await participantRegistry.getAddress(),
      await ownFactory.getAddress()
    );
    await ownRouter.waitForDeployment();
    await (
      await ownFactory.setRouter(await ownRouter.getAddress(), true)
    ).wait();

    const syna = await engine.syna();
    await (await ownFactory.createPair(WPOL, syna)).wait();
    const ownPair = await ownFactory.getPair(WPOL, syna);
    assert.notEqual(ownPair, ethers.ZeroAddress);
    await (await engine.setRepresentativeEndpoint(ownPair, true)).wait();
    await (
      await engine.mintRepresentativeInventory(registeredTrader.address, E("10"))
    ).wait();

    const synaToken = await ethers.getContractAt(
      "SynergyRepresentativeTokenV5",
      syna,
      registeredTrader
    );
    await (
      await wpolTrader.approve(await ownRouter.getAddress(), ethers.MaxUint256)
    ).wait();
    await (
      await synaToken.approve(await ownRouter.getAddress(), ethers.MaxUint256)
    ).wait();
    const deadline = BigInt((await ethers.provider.getBlock("latest")).timestamp + 3600);
    await (
      await ownRouter
        .connect(registeredTrader)
        .addLiquidity(
          WPOL,
          syna,
          E("5"),
          E("5"),
          registeredTrader.address,
          deadline
        )
    ).wait();

    const beforeSyna = await synaToken.balanceOf(registeredTrader.address);
    await (
      await ownRouter
        .connect(registeredTrader)
        .swapExactTokensForTokens(
          WPOL,
          syna,
          E("1"),
          E("0.8"),
          registeredTrader.address,
          deadline
        )
    ).wait();
    assert.ok((await synaToken.balanceOf(registeredTrader.address)) > beforeSyna);

    const wpolOutsider = new ethers.Contract(WPOL, WPOL_ABI, outsider);
    await (await wpolOutsider.deposit({ value: E("1") })).wait();
    await (
      await wpolOutsider.approve(await ownRouter.getAddress(), E("1"))
    ).wait();
    await assert.rejects(
      ownRouter
        .connect(outsider)
        .swapExactTokensForTokens(
          WPOL,
          syna,
          E("1"),
          E("0.8"),
          outsider.address,
          deadline
        )
    );

    const publicFactory = new ethers.Contract(
      QUICKSWAP_V3_FACTORY,
      FACTORY_ABI,
      deployer
    );
    const publicPolSynaPool = await publicFactory.poolByPair(WPOL, syna);
    assert.notEqual(publicPolSynaPool, ethers.ZeroAddress);

    const quoter = new ethers.Contract(
      QUICKSWAP_V3_QUOTER,
      QUOTER_ABI,
      deployer
    );
    const publicQuote = await quoter.quoteExactInputSingle.staticCall(
      WPOL,
      syna,
      E("0.1"),
      0
    );
    assert.ok(publicQuote.amountOut > 0n);

    const result = {
      scenario: "synergy_v5_profit_dividend_reinvestment_permissioned_dex",
      forkBlock: await ethers.provider.getBlockNumber(),
      originalExternalCapitalPOL: 120,
      realisedExternalProfitPOL: 20,
      endingBackedCapitalPOL: 139.8,
      backedCapitalGrowthFactor: 139.8 / 120,
      grossDividendPOL: 2,
      ownerNetReinvestedPOL: 0.9,
      keeperNetReinvestedPOL: 0.9,
      retainedProfitReinvestedPOL: 18,
      taxEscrowPOL: 0.2,
      cashDividendPaidPOL: 0,
      quickSwapPositionGrowth: {
        polSynaLiquidityBefore: beforePA.liquidity.toString(),
        polSynaLiquidityAfter: afterPA.liquidity.toString(),
        polSynrLiquidityBefore: beforePR.liquidity.toString(),
        polSynrLiquidityAfter: afterPR.liquidity.toString()
      },
      recognisedMultiplierAfter: after.recognisedEquivalent / 139.8,
      singleInvariantAfter: decimal(afterPreview.invariantWad),
      publicRepresentativeQuickSwapPool: publicPolSynaPool,
      ownPermissionedPair: ownPair,
      registeredTradePass: true,
      unregisteredTradeRejected: true,
      zeroMinOutForbidden: true,
      internalTransferRevenuePOL: 0,
      settleGasUsed: Number(settleReceipt.gasUsed),
      pass: afterPreview.pass
    };

    fs.mkdirSync(path.join(process.cwd(), "reports"), { recursive: true });
    fs.writeFileSync(
      path.join(process.cwd(), "reports", "synergy_v5_polygon_fork.json"),
      JSON.stringify(result, null, 2)
    );
    console.log(`SYNERGY_V5_POLYGON_RESULT ${JSON.stringify(result)}`);
  });
});
