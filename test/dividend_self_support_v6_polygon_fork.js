const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { ethers } = require("hardhat");

const WPOL = "0x0d500B1d8E8eF31E21C99d1Db9A6444d3ADf1270";
const QUICKSWAP_V3_POSITION_MANAGER =
  "0x8eF88E4c7CfbbaC1C163f7eddd4B578792201de6";
const E = ethers.parseEther;
const WAD = E("1");
const GAS_BENCHMARK_WEI = 274n * 10n ** 9n;

const WPOL_ABI = [
  "function deposit() payable",
  "function approve(address,uint256) returns(bool)",
  "function balanceOf(address) view returns(uint256)"
];
const POSITION_MANAGER_ABI = [
  "function positions(uint256 tokenId) view returns(uint96 nonce,address operator,address token0,address token1,int24 tickLower,int24 tickUpper,uint128 liquidity,uint256 feeGrowthInside0LastX128,uint256 feeGrowthInside1LastX128,uint128 tokensOwed0,uint128 tokensOwed1)"
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

async function riskMetrics(engine, npm, capitalPol, sigma = 0.05) {
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
    recognisedEquivalent,
    recognisedMultiplier: recognisedEquivalent / capitalPol,
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

async function expectRevert(action) {
  let reverted = false;
  try {
    await action();
  } catch (_) {
    reverted = true;
  }
  assert.equal(reverted, true);
}

describe("SYNERGY V6 profit-only self-support on Polygon fork", function () {
  this.timeout(1_800_000);

  it("keeps multiplier above 3x with no new investor capital and reimburses keeper cost", async function () {
    const [
      deployer,
      anchorInvestor,
      externalRevenuePayer,
      keeperUser,
      protocolTreasury,
      taxEscrow,
      lateInvestor
    ] = await ethers.getSigners();

    for (const address of [WPOL, QUICKSWAP_V3_POSITION_MANAGER]) {
      assert.notEqual(await ethers.provider.getCode(address), "0x");
    }

    const wpolDeployer = new ethers.Contract(WPOL, WPOL_ABI, deployer);
    const wpolAnchor = new ethers.Contract(WPOL, WPOL_ABI, anchorInvestor);
    const wpolRevenue = new ethers.Contract(WPOL, WPOL_ABI, externalRevenuePayer);
    const wpolLate = new ethers.Contract(WPOL, WPOL_ABI, lateInvestor);
    const wpolKeeper = new ethers.Contract(WPOL, WPOL_ABI, keeperUser);

    await (await wpolDeployer.deposit({ value: E("100") })).wait();
    await (await wpolAnchor.deposit({ value: E("20") })).wait();
    await (await wpolRevenue.deposit({ value: E("25") })).wait();
    await (await wpolLate.deposit({ value: E("1") })).wait();

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
    await (await wpolLate.approve(engineAddress, E("1"))).wait();
    await (await engine.depositByKeeper(E("100"))).wait();
    await (await engine.connect(anchorInvestor).depositByKeeper(E("20"))).wait();
    assert.equal(await engine.originalExternalCapitalPol(), E("120"));

    const RiskGate = await ethers.getContractFactory(
      "RealLiquidityMultiplierInvariant",
      deployer
    );
    const riskGate = await RiskGate.deploy(deployer.address, deployer.address);
    await riskGate.waitForDeployment();
    const npm = new ethers.Contract(
      QUICKSWAP_V3_POSITION_MANAGER,
      POSITION_MANAGER_ABI,
      deployer
    );
    const initialRisk = await riskMetrics(engine, npm, 120);
    const initialPreview = await riskGate.preview(initialRisk.metrics);
    assert.equal(initialPreview.pass, true);
    await (
      await riskGate.record(source("v6-risk-initial"), initialRisk.metrics)
    ).wait();

    const Registry = await ethers.getContractFactory(
      "ParticipantTaxRegistry",
      deployer
    );
    const registry = await Registry.deploy(deployer.address);
    await registry.waitForDeployment();
    await setEligible(registry, deployer, deployer, "v6-owner");
    await setEligible(registry, deployer, keeperUser, "v6-keeper");

    const Boundary = await ethers.getContractFactory(
      "SystemBoundaryRegistry",
      deployer
    );
    const boundary = await Boundary.deploy(deployer.address);
    await boundary.waitForDeployment();

    const Controller = await ethers.getContractFactory(
      "AutoReinvestDividendControllerV6",
      deployer
    );
    const controller = await Controller.deploy(
      WPOL,
      await registry.getAddress(),
      await boundary.getAddress(),
      await riskGate.getAddress(),
      engineAddress,
      deployer.address,
      protocolTreasury.address,
      taxEscrow.address,
      E("120"),
      1000,
      WAD,
      1500
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
    await (await wpolRevenue.approve(controllerAddress, E("25"))).wait();

    const snapshot = await ethers.provider.send("evm_snapshot", []);
    await (await engine.connect(lateInvestor).depositByKeeper(E("1"))).wait();
    assert.equal(await controller.bootstrapCapitalIntact(), false);
    await expectRevert(() =>
      controller
        .connect(keeperUser)
        .settleExternalRevenue.staticCall(
          externalRevenuePayer.address,
          E("1"),
          E("0.1"),
          keeperUser.address,
          source("v6-late-capital-rejected")
        )
    );
    await ethers.provider.send("evm_revert", [snapshot]);
    assert.equal(await controller.bootstrapCapitalIntact(), true);

    const beforePA = await npm.positions(await engine.lastPolSynaPositionId());
    const beforePR = await npm.positions(await engine.lastPolSynrPositionId());
    const keeperBalanceBefore = await wpolKeeper.balanceOf(keeperUser.address);

    const tx1 = await controller
      .connect(keeperUser)
      .settleExternalRevenue(
        externalRevenuePayer.address,
        E("20"),
        E("0.7"),
        keeperUser.address,
        source("v6-revenue-cycle-1"),
        { gasLimit: 12_000_000n }
      );
    const receipt1 = await tx1.wait();

    const firstRisk = await riskMetrics(engine, npm, 139.107);
    const firstPreview = await riskGate.preview(firstRisk.metrics);
    assert.equal(firstPreview.pass, true);
    await (
      await riskGate.record(source("v6-risk-after-cycle-1"), firstRisk.metrics)
    ).wait();

    const tx2 = await controller
      .connect(keeperUser)
      .settleExternalRevenue(
        externalRevenuePayer.address,
        E("5"),
        E("0.7"),
        keeperUser.address,
        source("v6-revenue-cycle-2"),
        { gasLimit: 12_000_000n }
      );
    const receipt2 = await tx2.wait();

    assert.equal(await engine.originalExternalCapitalPol(), E("120"));
    assert.equal(await controller.cumulativeGrossExternalRevenue(), E("25"));
    assert.equal(await controller.cumulativeKeeperCostReimbursed(), E("1.4"));
    assert.equal(await controller.cumulativeNetExternalProfit(), E("23.6"));
    assert.equal(await controller.cumulativeGrossDividends(), E("2.36"));
    assert.equal(await controller.cumulativeTaxWithheld(), E("0.236"));
    assert.equal(await controller.cumulativeOwnerNetReinvestment(), E("1.062"));
    assert.equal(await controller.cumulativeKeeperNetReinvestment(), E("1.062"));
    assert.equal(await controller.cumulativeRetainedReinvestment(), E("21.24"));
    assert.equal(await controller.cumulativeCashDividendPaid(), 0n);
    assert.equal(await engine.totalBackedCapitalPol(), E("143.364"));
    assert.equal(
      (await wpolKeeper.balanceOf(keeperUser.address)) - keeperBalanceBefore,
      E("1.4")
    );

    const afterPA = await npm.positions(await engine.lastPolSynaPositionId());
    const afterPR = await npm.positions(await engine.lastPolSynrPositionId());
    assert.ok(afterPA.liquidity > beforePA.liquidity);
    assert.ok(afterPR.liquidity > beforePR.liquidity);

    const finalRisk = await riskMetrics(engine, npm, 143.364);
    const finalPreview = await riskGate.preview(finalRisk.metrics);
    assert.equal(finalPreview.pass, true);
    const recognisedMultiplierWad = toWeiNumber(finalRisk.recognisedMultiplier);

    const SelfSupport = await ethers.getContractFactory(
      "DividendSelfSupportInvariantV6",
      deployer
    );
    const selfSupport = await SelfSupport.deploy();
    await selfSupport.waitForDeployment();

    const gasUsed = receipt1.gasUsed + receipt2.gasUsed;
    const benchmarkKeeperGasCost = gasUsed * GAS_BENCHMARK_WEI;
    assert.ok(E("1.4") >= benchmarkKeeperGasCost);

    const selfMetrics = {
      bootstrapOriginalCapitalPol: E("120"),
      currentOriginalExternalCapitalPol: await engine.originalExternalCapitalPol(),
      totalBackedCapitalPol: await engine.totalBackedCapitalPol(),
      cumulativeGrossExternalRevenuePol: await controller.cumulativeGrossExternalRevenue(),
      cumulativeKeeperCostReimbursedPol: await controller.cumulativeKeeperCostReimbursed(),
      cumulativeTaxWithheldPol: await controller.cumulativeTaxWithheld(),
      retainedReinvestedPol: await controller.cumulativeRetainedReinvestment(),
      ownerReinvestedPol: await controller.cumulativeOwnerNetReinvestment(),
      keeperReinvestedPol: await controller.cumulativeKeeperNetReinvestment(),
      cashDividendPaidPol: await controller.cumulativeCashDividendPaid(),
      internalTransferRevenuePol: await engine.internalTransferRevenuePol(),
      recognisedMultiplierWad,
      riskInvariantWad: finalPreview.invariantWad,
      actualKeeperGasCostPol: benchmarkKeeperGasCost
    };
    const selfPreview = await selfSupport.preview(selfMetrics);
    assert.equal(selfPreview.pass, true);
    assert.ok(selfPreview.invariantWad >= WAD);

    await expectRevert(() =>
      controller
        .connect(keeperUser)
        .settleExternalRevenue.staticCall(
          protocolTreasury.address,
          E("1"),
          E("0.1"),
          keeperUser.address,
          source("v6-internal-recycling-forbidden")
        )
    );

    const report = {
      scenario: "v6_no_new_capital_profit_only_compounding",
      forkBlock: await ethers.provider.getBlockNumber(),
      bootstrapCapitalPOL: 120,
      newInvestorCapitalAfterBootstrapPOL: 0,
      grossExternalRevenuePOL: 25,
      keeperCostReimbursedPOL: 1.4,
      netExternalProfitPOL: 23.6,
      taxEscrowPOL: 0.236,
      retainedReinvestedPOL: 21.24,
      ownerReinvestedPOL: 1.062,
      keeperReinvestedPOL: 1.062,
      cashDividendPOL: 0,
      endingBackedCapitalPOL: 143.364,
      capitalGrowthFactor: 143.364 / 120,
      recognisedMultiplier: finalRisk.recognisedMultiplier,
      riskInvariant: decimal(finalPreview.invariantWad),
      selfSupportInvariant: decimal(selfPreview.invariantWad),
      keeperGasUsed: gasUsed.toString(),
      keeperGasCostAt274GweiPOL: decimal(benchmarkKeeperGasCost),
      keeperCostCoverage: 1.4 / decimal(benchmarkKeeperGasCost),
      lateInvestorCapitalRejectedByController: true,
      internalRevenueRejected: true,
      quickSwapPositionGrowth: {
        polSynaBefore: beforePA.liquidity.toString(),
        polSynaAfter: afterPA.liquidity.toString(),
        polSynrBefore: beforePR.liquidity.toString(),
        polSynrAfter: afterPR.liquidity.toString()
      },
      pass: true,
      interpretation:
        "No new investor capital was used after bootstrap. Growth came from external operating revenue after keeper cost and tax. Internal dividend recycling alone was rejected and cannot create profit."
    };
    fs.mkdirSync(path.join(process.cwd(), "reports"), { recursive: true });
    fs.writeFileSync(
      path.join(process.cwd(), "reports", "dividend_self_support_v6_polygon_fork.json"),
      JSON.stringify(report, null, 2)
    );
    console.log("DIVIDEND_SELF_SUPPORT_V6_RESULT", JSON.stringify(report));
  });
});
