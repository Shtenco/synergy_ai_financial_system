const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { ethers } = require("hardhat");

const WPOL = "0x0d500B1d8E8eF31E21C99d1Db9A6444d3ADf1270";
const QUICKSWAP_V3_QUOTER = "0xa15F0D7377B2A0C0c10db057f641beD21028FC89";
const QUICKSWAP_V3_POSITION_MANAGER = "0x8eF88E4c7CfbbaC1C163f7eddd4B578792201de6";
const E = ethers.parseEther;
const WAD = E("1");

const WPOL_ABI = [
  "function deposit() payable",
  "function approve(address,uint256) returns(bool)",
  "function balanceOf(address) view returns(uint256)"
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
    await registry.connect(admin).setParticipant(
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
  const lpPol = (await engine.anchorPoolPolSyna()) + (await engine.anchorPoolPolSynr());
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

async function expectRevert(promise) {
  let reverted = false;
  try {
    await promise;
  } catch (_) {
    reverted = true;
  }
  assert.equal(reverted, true);
}

describe("SYNERGY V6 self-sustainability on Polygon fork", function () {
  this.timeout(1_800_000);

  it("keeps multiplier above 3x and compounds without new investor deposits", async function () {
    const [
      deployer,
      anchorInvestor,
      externalRevenuePayer,
      keeperUser,
      protocolTreasury,
      taxEscrow
    ] = await ethers.getSigners();

    for (const address of [WPOL, QUICKSWAP_V3_QUOTER, QUICKSWAP_V3_POSITION_MANAGER]) {
      assert.notEqual(await ethers.provider.getCode(address), "0x");
    }

    const wpolDeployer = new ethers.Contract(WPOL, WPOL_ABI, deployer);
    const wpolAnchor = new ethers.Contract(WPOL, WPOL_ABI, anchorInvestor);
    const wpolRevenue = new ethers.Contract(WPOL, WPOL_ABI, externalRevenuePayer);
    await (await wpolDeployer.deposit({ value: E("100") })).wait();
    await (await wpolAnchor.deposit({ value: E("20") })).wait();
    await (await wpolRevenue.deposit({ value: E("28") })).wait();

    const Engine = await ethers.getContractFactory("TriangularLiquidityEngineV5", deployer);
    const engine = await Engine.deploy(WPOL, QUICKSWAP_V3_POSITION_MANAGER, protocolTreasury.address);
    await engine.waitForDeployment();
    const engineAddress = await engine.getAddress();

    await (await wpolDeployer.approve(engineAddress, E("100"))).wait();
    await (await wpolAnchor.approve(engineAddress, E("20"))).wait();
    await (await engine.depositByKeeper(E("100"))).wait();
    await (await engine.connect(anchorInvestor).depositByKeeper(E("20"))).wait();
    assert.equal(await engine.originalExternalCapitalPol(), E("120"));
    assert.equal(await engine.totalBackedCapitalPol(), E("120"));

    const Invariant = await ethers.getContractFactory("RealLiquidityMultiplierInvariant", deployer);
    const invariant = await Invariant.deploy(deployer.address, deployer.address);
    await invariant.waitForDeployment();
    const npm = new ethers.Contract(QUICKSWAP_V3_POSITION_MANAGER, POSITION_MANAGER_ABI, deployer);
    const initial = await invariantMetrics(engine, npm, 120);
    const initialPreview = await invariant.preview(initial.metrics);
    assert.equal(initialPreview.pass, true);
    await (await invariant.record(source("v6-bootstrap"), initial.metrics)).wait();

    const Registry = await ethers.getContractFactory("ParticipantTaxRegistry", deployer);
    const registry = await Registry.deploy(deployer.address);
    await registry.waitForDeployment();
    await setEligible(registry, deployer, deployer, "v6-owner");
    await setEligible(registry, deployer, keeperUser, "v6-keeper");

    const Boundary = await ethers.getContractFactory("SystemBoundaryRegistry", deployer);
    const boundary = await Boundary.deploy(deployer.address);
    await boundary.waitForDeployment();

    const Controller = await ethers.getContractFactory("AutoReinvestDividendControllerV6", deployer);
    const controller = await Controller.deploy(
      WPOL,
      await registry.getAddress(),
      await boundary.getAddress(),
      await invariant.getAddress(),
      engineAddress,
      deployer.address,
      protocolTreasury.address,
      taxEscrow.address,
      1000,
      WAD,
      2000
    );
    await controller.waitForDeployment();
    const controllerAddress = await controller.getAddress();

    await (
      await boundary.setSystemAddresses(
        [engineAddress, controllerAddress, protocolTreasury.address, taxEscrow.address],
        true
      )
    ).wait();
    await (await engine.setProfitController(controllerAddress)).wait();
    await (await controller.setOperator(keeperUser.address, true)).wait();
    await (await wpolRevenue.approve(controllerAddress, E("28"))).wait();

    const beforePA = await npm.positions(await engine.lastPolSynaPositionId());
    const beforePR = await npm.positions(await engine.lastPolSynrPositionId());
    const rounds = [
      { revenue: "20", expense: "0.10", id: "v6-operating-1" },
      { revenue: "5", expense: "0.05", id: "v6-operating-2" },
      { revenue: "3", expense: "0.03", id: "v6-operating-3" }
    ];

    for (const round of rounds) {
      const originalBefore = await engine.originalExternalCapitalPol();
      await (
        await controller.connect(keeperUser).settleExternalOperatingRevenue(
          externalRevenuePayer.address,
          E(round.revenue),
          keeperUser.address,
          E(round.expense),
          source(round.id),
          { gasLimit: 12_000_000n }
        )
      ).wait();
      assert.equal(await engine.originalExternalCapitalPol(), originalBefore);
    }

    assert.equal(await engine.originalExternalCapitalPol(), E("120"));
    assert.equal(await controller.cumulativeGrossOperatingRevenue(), E("28"));
    assert.equal(await controller.cumulativeKeeperExpenseReimbursed(), E("0.18"));
    assert.equal(await controller.cumulativeNetExternalProfit(), E("27.82"));
    assert.equal(await controller.cumulativeRetainedReinvestment(), E("25.038"));
    assert.equal(await controller.cumulativeOwnerNetReinvestment(), E("1.2519"));
    assert.equal(await controller.cumulativeKeeperNetReinvestment(), E("1.2519"));
    assert.equal(await controller.cumulativeTaxWithheld(), E("0.2782"));
    assert.equal(await engine.totalBackedCapitalPol(), E("147.5418"));

    const afterPA = await npm.positions(await engine.lastPolSynaPositionId());
    const afterPR = await npm.positions(await engine.lastPolSynrPositionId());
    assert.ok(afterPA.liquidity > beforePA.liquidity);
    assert.ok(afterPR.liquidity > beforePR.liquidity);

    const after = await invariantMetrics(engine, npm, 147.5418);
    const afterPreview = await invariant.preview(after.metrics);
    assert.equal(afterPreview.pass, true);
    const recognisedMultiplier = after.recognisedEquivalent / 147.5418;
    assert.ok(recognisedMultiplier >= 3.0 && recognisedMultiplier <= 5.0);

    const SelfInvariant = await ethers.getContractFactory("DividendSelfSustainInvariantV6", deployer);
    const selfInvariant = await SelfInvariant.deploy();
    await selfInvariant.waitForDeployment();
    const selfPreview = await selfInvariant.preview({
      baseLiquidityRiskInvariantWad: afterPreview.invariantWad,
      bootstrapExternalCapitalPol: E("120"),
      currentOriginalExternalCapitalPol: await engine.originalExternalCapitalPol(),
      totalBackedCapitalPol: await engine.totalBackedCapitalPol(),
      cumulativeGrossOperatingRevenuePol: await controller.cumulativeGrossOperatingRevenue(),
      cumulativeExternalExpensePol: await controller.cumulativeKeeperExpenseReimbursed(),
      internalTransferRevenuePol: await engine.internalTransferRevenuePol()
    });
    assert.equal(selfPreview.pass, true);

    const capitalBeforeZeroRevenue = await engine.totalBackedCapitalPol();
    await expectRevert(
      controller.connect(keeperUser).settleExternalOperatingRevenue(
        externalRevenuePayer.address,
        0,
        keeperUser.address,
        0,
        source("v6-zero-revenue")
      )
    );
    assert.equal(await engine.totalBackedCapitalPol(), capitalBeforeZeroRevenue);

    await expectRevert(
      controller.connect(keeperUser).settleExternalOperatingRevenue(
        protocolTreasury.address,
        E("1"),
        keeperUser.address,
        0,
        source("v6-internal-recycling")
      )
    );
    assert.equal(await engine.totalBackedCapitalPol(), capitalBeforeZeroRevenue);

    const quoter = new ethers.Contract(QUICKSWAP_V3_QUOTER, QUOTER_ABI, deployer);
    const quote = await quoter.quoteExactInputSingle.staticCall(
      WPOL,
      await engine.syna(),
      E("0.1"),
      0
    );
    assert.ok(quote.amountOut > 0n);

    fs.mkdirSync(path.join(process.cwd(), "reports"), { recursive: true });
    const report = {
      pass: true,
      bootstrapExternalCapitalPOL: 120,
      newInvestorCapitalAfterBootstrapPOL: 0,
      endingBackedCapitalPOL: 147.5418,
      capitalGrowthFactor: 147.5418 / 120,
      grossExternalOperatingRevenuePOL: 28,
      keeperExternalExpensePOL: 0.18,
      netExternalProfitPOL: 27.82,
      retainedProfitReinvestedPOL: 25.038,
      ownerDividendReinvestedPOL: 1.2519,
      keeperDividendReinvestedPOL: 1.2519,
      taxEscrowPOL: 0.2782,
      recognisedLiquidityMultiplier: recognisedMultiplier,
      baseSingleInvariant: decimal(afterPreview.invariantWad),
      selfSustainInvariant: decimal(selfPreview.invariantWad),
      zeroExternalRevenueGrowthPOL: 0,
      internalRecyclingGrowthPOL: 0,
      quickSwapPositionGrowth: {
        polSynaBefore: beforePA.liquidity.toString(),
        polSynaAfter: afterPA.liquidity.toString(),
        polSynrBefore: beforePR.liquidity.toString(),
        polSynrAfter: afterPR.liquidity.toString()
      },
      publicQuoteForPointOnePOL: quote.amountOut.toString(),
      interpretation: "No new investor deposit was used after 120 POL bootstrap. Growth came from new external operating revenue net of keeper expense; reinvestment compounded it but did not create it."
    };
    fs.writeFileSync(
      path.join(process.cwd(), "reports", "synergy_self_sustain_v6_polygon_fork.json"),
      JSON.stringify(report, null, 2)
    );
    console.log("SYNERGY_SELF_SUSTAIN_V6_RESULT", JSON.stringify(report));
  });
});
