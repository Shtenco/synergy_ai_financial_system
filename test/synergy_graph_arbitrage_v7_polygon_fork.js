const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { ethers, network } = require("hardhat");

const WPOL = "0x0d500B1d8E8eF31E21C99d1Db9A6444d3ADf1270";
const USDT = "0xc2132D05D31c914a87C6611C10748AEb04B58e8F";
const QS_V3_FACTORY = "0x411b0fAcC3489691f28ad58c47006AF5E3Ab3A28";
const QS_V3_QUOTER = "0xa15F0D7377B2A0C0c10db057f641beD21028FC89";
const QS_V3_POSITION_MANAGER = "0x8eF88E4c7CfbbaC1C163f7eddd4B578792201de6";
const QS_V2_FACTORY = "0x5757371414417b8C6CAad45bAeF941aBc7d3Ab32";

const E = ethers.parseEther;
const U = (value) => ethers.parseUnits(value, 6);

const ERC20_ABI = [
  "function deposit() payable",
  "function approve(address,uint256) returns(bool)",
  "function transfer(address,uint256) returns(bool)",
  "function balanceOf(address) view returns(uint256)"
];
const FACTORY_V3_ABI = ["function poolByPair(address,address) view returns(address)"];
const FACTORY_V2_ABI = ["function getPair(address,address) view returns(address)"];
const POOL_ABI = [
  "function token0() view returns(address)",
  "function token1() view returns(address)",
  "function getReserves() view returns(uint112,uint112,uint32)",
  "function balanceOf(address) view returns(uint256)",
  "function transfer(address,uint256) returns(bool)"
];
const QUOTER_ABI = [
  "function quoteExactInputSingle(address,address,uint256,uint160) returns(uint256,uint16)"
];

const source = (label) => ethers.keccak256(ethers.toUtf8Bytes(label));
const decimal18 = (value) => Number(ethers.formatEther(value));
const decimal6 = (value) => Number(ethers.formatUnits(value, 6));

async function eligible(registry, admin, signer, label) {
  const block = await ethers.provider.getBlock("latest");
  await (
    await registry.connect(admin).setParticipant(
      signer.address,
      true,
      BigInt(block.timestamp + 86400),
      source(label)
    )
  ).wait();
}

async function mine() {
  await network.provider.send("evm_mine");
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

async function fundUsdtFromExternalPool(externalPool, recipient, amount) {
  await network.provider.send("anvil_impersonateAccount", [externalPool]);
  await network.provider.send("anvil_setBalance", [
    externalPool,
    ethers.toBeHex(E("10"))
  ]);
  const directProvider = new ethers.JsonRpcProvider(
    process.env.LOCAL_FORK_URL || "http://127.0.0.1:8545"
  );
  const donor = await directProvider.getSigner(externalPool);
  const usdtFromPool = new ethers.Contract(USDT, ERC20_ABI, donor);
  await (await usdtFromPool.transfer(recipient, amount)).wait();
  await network.provider.send("anvil_stopImpersonatingAccount", [externalPool]);
}

describe("SYNERGY V7 six-pool internal graph and protected public representative pool", function () {
  this.timeout(1_800_000);

  it("uses 6 internal SINERGY pools, 1 protected public pool and 2 external WPOL/USDT exits", async function () {
    const [deployer, keeper, trader, outsider] = await ethers.getSigners();

    for (const address of [
      WPOL,
      USDT,
      QS_V3_FACTORY,
      QS_V3_QUOTER,
      QS_V3_POSITION_MANAGER,
      QS_V2_FACTORY
    ]) {
      assert.notEqual(await ethers.provider.getCode(address), "0x");
    }

    const qsf = new ethers.Contract(QS_V3_FACTORY, FACTORY_V3_ABI, deployer);
    const qsv2 = new ethers.Contract(QS_V2_FACTORY, FACTORY_V2_ABI, deployer);
    const externalV2 = await qsv2.getPair(WPOL, USDT);
    const externalV3 = await qsf.poolByPair(WPOL, USDT);
    assert.notEqual(externalV2, ethers.ZeroAddress);
    assert.notEqual(externalV3, ethers.ZeroAddress);

    const wpol = new ethers.Contract(WPOL, ERC20_ABI, deployer);
    const wpolOutsider = new ethers.Contract(WPOL, ERC20_ABI, outsider);
    const usdt = new ethers.Contract(USDT, ERC20_ABI, deployer);
    const usdtOutsider = new ethers.Contract(USDT, ERC20_ABI, outsider);

    await (await wpol.deposit({ value: E("100") })).wait();
    await (await wpolOutsider.deposit({ value: E("2") })).wait();
    await fundUsdtFromExternalPool(externalV2, deployer.address, U("40"));

    const Registry = await ethers.getContractFactory("ParticipantTaxRegistry", deployer);
    const registry = await Registry.deploy(deployer.address);
    await registry.waitForDeployment();
    await eligible(registry, deployer, deployer, "v7-admin");
    await eligible(registry, deployer, keeper, "v7-keeper");
    await eligible(registry, deployer, trader, "v7-trader");

    const Factory = await ethers.getContractFactory("SynergyDexFactoryV5", deployer);
    const internalFactory = await Factory.deploy(await registry.getAddress());
    await internalFactory.waitForDeployment();

    const Router = await ethers.getContractFactory("SynergyDexRouterV5", deployer);
    const internalRouter = await Router.deploy(
      await registry.getAddress(),
      await internalFactory.getAddress()
    );
    await internalRouter.waitForDeployment();
    await (await internalFactory.setRouter(await internalRouter.getAddress(), true)).wait();

    const Topology = await ethers.getContractFactory("SynergyTopologyV7Harness", deployer);
    const topology = await Topology.deploy(
      WPOL,
      USDT,
      await registry.getAddress(),
      await internalFactory.getAddress(),
      QS_V3_FACTORY,
      QS_V3_POSITION_MANAGER
    );
    await topology.waitForDeployment();

    const syna = await topology.syna();
    const synr = await topology.synr();

    const exactInternalPairs = [
      [WPOL, syna],
      [WPOL, synr],
      [syna, synr],
      [WPOL, USDT],
      [USDT, syna],
      [USDT, synr]
    ];
    for (const [tokenA, tokenB] of exactInternalPairs) {
      await (await internalFactory.createPair(tokenA, tokenB)).wait();
    }
    assert.equal(await internalFactory.allPairsLength(), 6n);
    await (await topology.configureInternalTopology(await internalRouter.getAddress())).wait();

    const internalPools = Array.from(await topology.internalPools());
    assert.equal(internalPools.length, 6);
    assert.equal(new Set(internalPools.map((pool) => pool.toLowerCase())).size, 6);
    for (const pool of internalPools) {
      assert.notEqual(pool, ethers.ZeroAddress);
      assert.notEqual(await ethers.provider.getCode(pool), "0x");
    }

    const synaToken = await ethers.getContractAt(
      "SynergyRepresentativeTokenV7",
      syna,
      deployer
    );
    const synrToken = await ethers.getContractAt(
      "SynergyInternalReserveTokenV7",
      synr,
      deployer
    );

    await (await topology.mintInternalInventory(deployer.address, E("40"), E("40"))).wait();
    await (await wpol.approve(await internalRouter.getAddress(), E("30"))).wait();
    await (await usdt.approve(await internalRouter.getAddress(), U("30"))).wait();
    await (await synaToken.approve(await internalRouter.getAddress(), E("30"))).wait();
    await (await synrToken.approve(await internalRouter.getAddress(), E("30"))).wait();

    const deadline = BigInt((await ethers.provider.getBlock("latest")).timestamp + 3600);
    await (await internalRouter.addLiquidity(WPOL, syna, E("10"), E("10"), deployer.address, deadline)).wait();
    await (await internalRouter.addLiquidity(WPOL, synr, E("10"), E("10"), deployer.address, deadline)).wait();
    await (await internalRouter.addLiquidity(syna, synr, E("10"), E("10"), deployer.address, deadline)).wait();
    await (await internalRouter.addLiquidity(WPOL, USDT, E("10"), U("10"), deployer.address, deadline)).wait();
    await (await internalRouter.addLiquidity(USDT, syna, U("10"), E("10"), deployer.address, deadline)).wait();
    await (await internalRouter.addLiquidity(USDT, synr, U("10"), E("10"), deployer.address, deadline)).wait();

    for (const pool of internalPools) {
      const pair = new ethers.Contract(pool, POOL_ABI, deployer);
      const reserves = await pair.getReserves();
      assert.ok(reserves[0] > 0n);
      assert.ok(reserves[1] > 0n);
    }

    await (await usdt.transfer(outsider.address, U("1"))).wait();
    await (await usdtOutsider.approve(await internalRouter.getAddress(), U("1"))).wait();
    await expectRevert(
      internalRouter.connect(outsider).swapExactTokensForTokens(
        USDT,
        syna,
        U("1"),
        E("0.8"),
        outsider.address,
        deadline
      )
    );

    const internalUsdtSyna = await topology.internalUsdtSyna();
    const lp = new ethers.Contract(internalUsdtSyna, POOL_ABI, deployer);
    assert.ok((await lp.balanceOf(deployer.address)) > 0n);
    await expectRevert(lp.transfer(outsider.address, 1n));

    const Protection = await ethers.getContractFactory(
      "PublicRepresentativeProtectionV7",
      deployer
    );
    const protection = await Protection.deploy(WPOL, syna, 1);
    await protection.waitForDeployment();
    await (await topology.setProtectedGateway(await protection.getAddress())).wait();
    await (await topology.setRepresentativeInfrastructure(QS_V3_QUOTER, true)).wait();

    await (await wpol.approve(await topology.getAddress(), E("20"))).wait();
    await (
      await topology.createPublicRepresentativePool(E("20"), {
        gasLimit: 12_000_000n
      })
    ).wait();

    const publicPool = await topology.publicQuickSwapPolSyna();
    assert.notEqual(publicPool, ethers.ZeroAddress);
    assert.equal(await qsf.poolByPair(WPOL, syna), publicPool);
    assert.equal(await qsf.poolByPair(WPOL, synr), ethers.ZeroAddress);
    assert.equal(await qsf.poolByPair(syna, synr), ethers.ZeroAddress);
    assert.equal(await qsf.poolByPair(USDT, syna), ethers.ZeroAddress);
    assert.equal(await qsf.poolByPair(USDT, synr), ethers.ZeroAddress);

    const quoter = new ethers.Contract(QS_V3_QUOTER, QUOTER_ABI, deployer);
    const quote = await quoter.quoteExactInputSingle.staticCall(
      WPOL,
      syna,
      E("0.1"),
      0
    );
    assert.ok(quote[0] > 0n);

    const ExitRegistry = await ethers.getContractFactory(
      "ExternalExitPoolRegistryV7",
      deployer
    );
    const exits = await ExitRegistry.deploy(WPOL, USDT);
    await exits.waitForDeployment();

    for (const [pool, kind] of [
      [externalV2, 0],
      [externalV3, 1]
    ]) {
      const externalPool = new ethers.Contract(pool, POOL_ABI, deployer);
      const token0 = await externalPool.token0();
      const token1 = await externalPool.token1();
      await (
        await exits.whitelistExitPool(pool, token0, token1, kind, 1, 1)
      ).wait();
      assert.equal(await exits.validate(pool), true);
    }
    assert.equal(await exits.count(), 2n);

    const Gate = await ethers.getContractFactory("SynergyGraphProfitGateV7", deployer);
    const gate = await Gate.deploy(
      await registry.getAddress(),
      await exits.getAddress(),
      WPOL,
      USDT
    );
    await gate.waitForDeployment();
    await (await gate.setKeeper(keeper.address, true)).wait();
    await (await gate.configureInternalPools(internalPools)).wait();
    for (const pool of internalPools) {
      assert.equal(await gate.internalPool(pool), true);
    }
    await (await gate.setPublicRepresentativePool(publicPool, true)).wait();

    const proofDeadline = BigInt(
      (await ethers.provider.getBlock("latest")).timestamp + 600
    );
    const validProof = {
      settlementAsset: USDT,
      amountIn: U("1"),
      amountOut: U("1.12"),
      gasCost: U("0.01"),
      poolFees: U("0.01"),
      slippageCost: U("0.005"),
      flashPremium: U("0.005"),
      internalValueLoss: U("0.02"),
      qeNotional: U("0.1"),
      qtExternalBurn: U("0.03"),
      deadline: proofDeadline,
      pools: [internalUsdtSyna, publicPool, externalV3],
      externalEdge: [false, true, true]
    };

    const salt = source("v7-valid-usdt-salt");
    const routeHash = await gate.connect(keeper).hashProof(validProof, 1, salt);
    await (await gate.connect(keeper).commit(routeHash)).wait();
    await expectRevert(gate.connect(keeper).commit(routeHash));
    await mine();

    const netProfit = await gate
      .connect(keeper)
      .revealAndAccept.staticCall(validProof, 1, salt);
    assert.equal(netProfit, U("0.07"));
    await (await gate.connect(keeper).revealAndAccept(validProof, 1, salt)).wait();

    const fakeQeProof = {
      ...validProof,
      amountOut: U("1.08"),
      internalValueLoss: 0n,
      qtExternalBurn: 0n,
      deadline: BigInt((await ethers.provider.getBlock("latest")).timestamp + 600)
    };
    const fakeSalt = source("v7-fake-qe-usdt-salt");
    const fakeHash = await gate.connect(keeper).hashProof(fakeQeProof, 2, fakeSalt);
    await (await gate.connect(keeper).commit(fakeHash)).wait();
    await mine();
    await expectRevert(
      gate.connect(keeper).revealAndAccept(fakeQeProof, 2, fakeSalt)
    );

    const amountIn = E("0.1");
    const oracleOut = quote[0];
    const minOut = (oracleOut * 99n) / 100n;
    const orderSalt = source("v7-order-salt");
    const orderDeadline = BigInt(
      (await ethers.provider.getBlock("latest")).timestamp + 600
    );
    const orderHash = await protection.hashOrder(
      trader.address,
      WPOL,
      syna,
      amountIn,
      minOut,
      oracleOut,
      100,
      100,
      orderDeadline,
      7,
      orderSalt
    );

    await (await protection.connect(trader).commit(orderHash)).wait();
    await expectRevert(protection.connect(outsider).commit(orderHash));
    await mine();

    await expectRevert(
      protection.connect(trader).revealValidate(
        WPOL,
        syna,
        amountIn,
        minOut,
        oracleOut,
        0,
        oracleOut,
        100,
        100,
        orderDeadline,
        7,
        orderSalt
      )
    );

    const postTradeQuote = (oracleOut * 995n) / 1000n;
    await (
      await protection.connect(trader).revealValidate(
        WPOL,
        syna,
        amountIn,
        minOut,
        oracleOut,
        oracleOut,
        postTradeQuote,
        100,
        100,
        orderDeadline,
        7,
        orderSalt
      )
    ).wait();

    const result = {
      scenario: "synergy_v7_complete_internal_graph_external_representative",
      internalSinergyPools: {
        count: 6,
        polSyna: await topology.internalPolSyna(),
        polSynr: await topology.internalPolSynr(),
        synaSynr: await topology.internalSynaSynr(),
        polUsdt: await topology.internalPolUsdt(),
        usdtSyna: internalUsdtSyna,
        usdtSynr: await topology.internalUsdtSynr(),
        allLiquid: true,
        outsiderRejectedOnUsdtSyna: true,
        lpTransferToOutsiderRejected: true
      },
      publicRepresentativeQuickSwap: {
        count: 1,
        polSyna: publicPool,
        quoteForPointOnePol: decimal18(quote[0]),
        publicPolSynrAbsent: true,
        publicSynaSynrAbsent: true,
        publicUsdtSynaAbsent: true,
        publicUsdtSynrAbsent: true,
        zeroQuoteRejected: true,
        duplicateCommitRejected: true,
        commitRevealPassed: true,
        hardDeviationCapsEnabled: true,
        sandwichLossBoundPassed: true
      },
      externalExitPools: {
        count: 2,
        quickSwapV2PolUsdt: externalV2,
        quickSwapV3PolUsdt: externalV3
      },
      graph: {
        totalPoolCount: 9,
        validExternalNetProfitUsdt: decimal6(netProfit),
        fakeQeRevenueRejected: true,
        settlementAsset: USDT,
        internalUsdtEdgeUsed: true,
        includesInternalAndExternalEdges: true
      },
      pass: true
    };

    fs.mkdirSync(path.join(process.cwd(), "reports"), { recursive: true });
    fs.writeFileSync(
      path.join(process.cwd(), "reports", "synergy_graph_v7_polygon_fork.json"),
      JSON.stringify(result, null, 2)
    );
    console.log("SYNERGY_GRAPH_V7_RESULT", JSON.stringify(result));
  });
});
