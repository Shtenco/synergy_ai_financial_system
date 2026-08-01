const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { ethers, network } = require("hardhat");

const WPOL = "0x0d500B1d8E8eF31E21C99d1Db9A6444d3ADf1270";
const USDT = "0xc2132D05D31c914a87C6611C10748AEb04B58e8F";
const USDC = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174";
const DAI = "0x8f3Cf7ad23Cd3CaDbD9735AFf958023239c6A063";
const WETH = "0x7ceB23fD6bC0adD59E62ac25578270cFf1b9f619";

const QS_V2_FACTORY = "0x5757371414417b8C6CAad45bAeF941aBc7d3Ab32";
const QS_V2_ROUTER = "0xa5E0829CaCEd8fFDD4De3c43696c57F7D7A678ff";
const QS_V3_FACTORY = "0x411b0fAcC3489691f28ad58c47006AF5E3Ab3A28";
const QS_V3_QUOTER = "0xa15F0D7377B2A0C0c10db057f641beD21028FC89";
const QS_V3_ROUTER = "0xf5b509bB0909a69B1c207E495f687a596C168E12";

const GAS_PRICE = 274_000_000_000n;
const SUCCESS_CYCLES = Number(process.env.SUPERCYCLE_COUNT || 3);
const U = (value) => ethers.parseUnits(value, 6);
const E = ethers.parseEther;
const source = (label) => ethers.keccak256(ethers.toUtf8Bytes(label));
const fmt6 = (value) => Number(ethers.formatUnits(value, 6));

const ERC20_ABI = [
  "function approve(address,uint256) returns(bool)",
  "function transfer(address,uint256) returns(bool)",
  "function balanceOf(address) view returns(uint256)",
  "function deposit() payable"
];
const FACTORY_V2_ABI = ["function getPair(address,address) view returns(address)"];
const FACTORY_V3_ABI = ["function poolByPair(address,address) view returns(address)"];
const PAIR_ABI = [
  "function token0() view returns(address)",
  "function token1() view returns(address)",
  "function getReserves() view returns(uint112,uint112,uint32)"
];
const V2_ROUTER_ABI = [
  "function getAmountsOut(uint256,address[]) view returns(uint256[])",
  "function swapExactTokensForTokens(uint256,uint256,address[],address,uint256) returns(uint256[])"
];
const V3_QUOTER_ABI = [
  "function quoteExactInputSingle(address,address,uint256,uint160) returns(uint256,uint16)"
];

async function expectRevert(promise) {
  let reverted = false;
  try {
    await promise;
  } catch (_) {
    reverted = true;
  }
  assert.equal(reverted, true);
}

async function eligible(registry, admin, account, label) {
  const block = await ethers.provider.getBlock("latest");
  await (
    await registry.connect(admin).setParticipant(
      account,
      true,
      BigInt(block.timestamp + 86400),
      source(label)
    )
  ).wait();
}

async function impersonatedTransfer(token, donor, recipient, amount) {
  await network.provider.send("anvil_impersonateAccount", [donor]);
  await network.provider.send("anvil_setBalance", [donor, ethers.toBeHex(E("100"))]);
  const direct = new ethers.JsonRpcProvider(
    process.env.LOCAL_FORK_URL || "http://127.0.0.1:8545"
  );
  const signer = await direct.getSigner(donor);
  const contract = new ethers.Contract(token, ERC20_ABI, signer);
  await (await contract.transfer(recipient, amount)).wait();
  await network.provider.send("anvil_stopImpersonatingAccount", [donor]);
}

async function findDonor(factory, token, otherTokens, excluded, minimum) {
  const blocked = new Set(excluded.map((value) => value.toLowerCase()));
  const candidates = [];
  for (const other of otherTokens) {
    if (other.toLowerCase() === token.toLowerCase()) continue;
    const pair = await factory.getPair(token, other);
    if (pair === ethers.ZeroAddress || blocked.has(pair.toLowerCase())) continue;
    const balance = await new ethers.Contract(token, ERC20_ABI, ethers.provider).balanceOf(pair);
    candidates.push({ pair, balance, other });
  }
  candidates.sort((a, b) => (a.balance > b.balance ? -1 : a.balance < b.balance ? 1 : 0));
  if (!candidates.length || candidates[0].balance < minimum) {
    throw new Error(`No donor for ${token}; candidates=${JSON.stringify(candidates)}`);
  }
  return candidates[0];
}

async function discoverExternalPools(factoryV2, factoryV3) {
  const specs = [
    [WPOL, USDT, "v2"],
    [WPOL, USDT, "v3"],
    [WPOL, USDC, "auto"],
    [WPOL, WETH, "auto"],
    [WPOL, DAI, "auto"],
    [USDT, USDC, "auto"],
    [USDT, WETH, "auto"],
    [USDT, DAI, "auto"],
    [USDC, WETH, "auto"],
    [USDC, DAI, "auto"]
  ];
  const pools = [];
  const metadata = [];
  for (const [tokenA, tokenB, requestedKind] of specs) {
    let pool = ethers.ZeroAddress;
    let kind = requestedKind;
    if (requestedKind === "v3" || requestedKind === "auto") {
      pool = await factoryV3.poolByPair(tokenA, tokenB);
      if (pool !== ethers.ZeroAddress) kind = "v3";
    }
    if (pool === ethers.ZeroAddress && (requestedKind === "v2" || requestedKind === "auto")) {
      pool = await factoryV2.getPair(tokenA, tokenB);
      if (pool !== ethers.ZeroAddress) kind = "v2";
    }
    assert.notEqual(pool, ethers.ZeroAddress, `missing external pool ${tokenA}/${tokenB}`);
    assert.notEqual(await ethers.provider.getCode(pool), "0x", `no code at ${pool}`);
    const balanceA = await new ethers.Contract(tokenA, ERC20_ABI, ethers.provider).balanceOf(pool);
    const balanceB = await new ethers.Contract(tokenB, ERC20_ABI, ethers.provider).balanceOf(pool);
    assert.ok(balanceA > 0n && balanceB > 0n, `empty external pool ${pool}`);
    pools.push(pool);
    metadata.push({ tokenA, tokenB, kind, pool });
  }
  assert.equal(pools.length, 10);
  assert.equal(new Set(pools.map((value) => value.toLowerCase())).size, 10);
  return { pools, metadata };
}

function internalQuote(amountIn, reserveIn, reserveOut) {
  const effective = amountIn * 9970n;
  return (effective * reserveOut) / (reserveIn * 10000n + effective);
}

function internalAmountIn(amountOut, reserveIn, reserveOut) {
  return (reserveIn * amountOut * 10000n) / ((reserveOut - amountOut) * 9970n) + 1n;
}

async function pairState(pair, synthetic, liquid) {
  const token0 = await pair.token0();
  const [r0, r1] = await pair.getReserves();
  const syntheticReserve = token0.toLowerCase() === synthetic.toLowerCase() ? r0 : r1;
  const liquidReserve = token0.toLowerCase() === liquid.toLowerCase() ? r0 : r1;
  return {
    syntheticReserve,
    liquidReserve,
    k: syntheticReserve * liquidReserve
  };
}

async function externalQuote(quoter, v2Router, amountUsdt) {
  const v3 = await quoter.quoteExactInputSingle.staticCall(USDT, WPOL, amountUsdt, 0);
  const wpolOut = v3[0];
  const v2 = await v2Router.getAmountsOut(wpolOut, [WPOL, USDT]);
  return { wpolOut, usdtOut: v2[1] };
}

async function choosePlan(pair, syntheticAddress, quoter, v2Router, minimumProfit) {
  const state = await pairState(pair, syntheticAddress, USDT);
  for (const bps of [10n, 25n, 50n, 100n, 200n, 400n, 700n]) {
    const mint = (state.syntheticReserve * bps) / 10000n;
    if (mint === 0n) continue;
    const extracted = internalQuote(mint, state.syntheticReserve, state.liquidReserve);
    const syntheticAfter = state.syntheticReserve + mint;
    const liquidAfter = state.liquidReserve - extracted;
    const buyback = internalAmountIn(mint, liquidAfter, syntheticAfter);
    const external = await externalQuote(quoter, v2Router, extracted);
    if (external.usdtOut > buyback + minimumProfit) {
      return { mint, extracted, buyback, ...external };
    }
  }
  return null;
}

async function shockV2(shocker, usdt, v2Router, amount) {
  await (await usdt.connect(shocker).approve(QS_V2_ROUTER, amount)).wait();
  const block = await ethers.provider.getBlock("latest");
  await (
    await v2Router.connect(shocker).swapExactTokensForTokens(
      amount,
      1n,
      [USDT, WPOL],
      shocker.address,
      BigInt(block.timestamp + 600)
    )
  ).wait();
}

async function boundaryTotals(tokens, addresses) {
  const totals = {};
  for (const token of tokens) {
    const contract = new ethers.Contract(token, ERC20_ABI, ethers.provider);
    let total = 0n;
    for (const account of addresses) total += await contract.balanceOf(account);
    totals[token.toLowerCase()] = total;
  }
  return totals;
}

async function addLiquidity(router, tokenA, tokenB, amountA, amountB, provider) {
  const block = await provider.getBlock("latest");
  await (
    await router.addLiquidity(
      tokenA,
      tokenB,
      amountA,
      amountB,
      await router.runner.getAddress(),
      BigInt(block.timestamp + 3600)
    )
  ).wait();
}

describe("SYNERGY V8 restored stateful 10x10 graph on pinned Polygon fork", function () {
  this.timeout(1_800_000);

  it("runs real profitable managed QE/QT cycles while preserving consolidated protocol assets", async function () {
    const [admin, keeper, treasury, shocker, attacker] = await ethers.getSigners();
    for (const address of [
      WPOL,
      USDT,
      USDC,
      DAI,
      WETH,
      QS_V2_FACTORY,
      QS_V2_ROUTER,
      QS_V3_FACTORY,
      QS_V3_QUOTER,
      QS_V3_ROUTER
    ]) {
      assert.notEqual(await ethers.provider.getCode(address), "0x", `missing code ${address}`);
    }

    const factoryV2 = new ethers.Contract(QS_V2_FACTORY, FACTORY_V2_ABI, admin);
    const factoryV3 = new ethers.Contract(QS_V3_FACTORY, FACTORY_V3_ABI, admin);
    const v2Router = new ethers.Contract(QS_V2_ROUTER, V2_ROUTER_ABI, admin);
    const quoter = new ethers.Contract(QS_V3_QUOTER, V3_QUOTER_ABI, admin);
    const external = await discoverExternalPools(factoryV2, factoryV3);
    const routeV2 = await factoryV2.getPair(WPOL, USDT);
    const routeV3 = await factoryV3.poolByPair(WPOL, USDT);
    assert.ok(external.pools.some((pool) => pool.toLowerCase() === routeV2.toLowerCase()));
    assert.ok(external.pools.some((pool) => pool.toLowerCase() === routeV3.toLowerCase()));

    const wpol = new ethers.Contract(WPOL, ERC20_ABI, admin);
    const usdt = new ethers.Contract(USDT, ERC20_ABI, admin);
    const usdc = new ethers.Contract(USDC, ERC20_ABI, admin);
    const weth = new ethers.Contract(WETH, ERC20_ABI, admin);
    await (await wpol.deposit({ value: E("100") })).wait();

    const usdtDonor = await findDonor(
      factoryV2,
      USDT,
      [USDC, DAI, WETH, WPOL],
      [routeV2],
      U("20000")
    );
    const adminUsdtFunding = (usdtDonor.balance * 30n) / 100n;
    const shockFunding = (usdtDonor.balance * 60n) / 100n;
    const mainPoolDepth = (adminUsdtFunding * 70n) / 100n;
    assert.ok(mainPoolDepth >= U("3000"));
    await impersonatedTransfer(USDT, usdtDonor.pair, admin.address, adminUsdtFunding);
    await impersonatedTransfer(USDT, usdtDonor.pair, shocker.address, shockFunding);

    const usdcDonor = await findDonor(factoryV2, USDC, [USDT, DAI, WETH, WPOL], [], U("1000"));
    const wethDonor = await findDonor(factoryV2, WETH, [USDT, USDC, DAI, WPOL], [], E("2"));
    await impersonatedTransfer(USDC, usdcDonor.pair, admin.address, U("1000"));
    await impersonatedTransfer(WETH, wethDonor.pair, admin.address, E("2"));

    const Registry = await ethers.getContractFactory("ParticipantTaxRegistry", admin);
    const registry = await Registry.deploy(admin.address);
    await registry.waitForDeployment();
    await eligible(registry, admin, admin.address, "v8-admin");
    await eligible(registry, admin, keeper.address, "v8-keeper");
    await eligible(registry, admin, treasury.address, "v8-treasury");

    const Factory = await ethers.getContractFactory("SynergyDexFactoryV5", admin);
    const internalFactory = await Factory.deploy(await registry.getAddress());
    await internalFactory.waitForDeployment();
    const Router = await ethers.getContractFactory("SynergyDexRouterV5", admin);
    const internalRouter = await Router.deploy(
      await registry.getAddress(),
      await internalFactory.getAddress()
    );
    await internalRouter.waitForDeployment();
    await (await internalFactory.setRouter(await internalRouter.getAddress(), true)).wait();

    const Token = await ethers.getContractFactory("TemporaryQETokenV11", admin);
    const synthetic = await Token.deploy();
    await synthetic.waitForDeployment();
    const SYN = await synthetic.getAddress();

    const internalPairSpecs = [
      [SYN, WPOL],
      [SYN, USDT],
      [SYN, USDC],
      [SYN, WETH],
      [WPOL, USDT],
      [WPOL, USDC],
      [WPOL, WETH],
      [USDT, USDC],
      [USDT, WETH],
      [USDC, WETH]
    ];
    for (const [tokenA, tokenB] of internalPairSpecs) {
      await (await internalFactory.createPair(tokenA, tokenB)).wait();
    }
    assert.equal(await internalFactory.allPairsLength(), 10n);
    const internalPools = [];
    for (const [tokenA, tokenB] of internalPairSpecs) {
      const pair = await internalFactory.getPair(tokenA, tokenB);
      assert.notEqual(pair, ethers.ZeroAddress);
      internalPools.push(pair);
    }
    assert.equal(new Set(internalPools.map((pool) => pool.toLowerCase())).size, 10);

    const syntheticBootstrap = mainPoolDepth + U("4000");
    await (await synthetic.mintBootstrap(admin.address, syntheticBootstrap)).wait();
    for (const token of [synthetic, wpol, usdt, usdc, weth]) {
      await (await token.approve(await internalRouter.getAddress(), ethers.MaxUint256)).wait();
    }

    const add = async (a, b, amountA, amountB) => {
      const block = await ethers.provider.getBlock("latest");
      await (
        await internalRouter.addLiquidity(
          a,
          b,
          amountA,
          amountB,
          admin.address,
          BigInt(block.timestamp + 3600)
        )
      ).wait();
    };
    await add(SYN, WPOL, U("500"), E("1"));
    await add(SYN, USDT, mainPoolDepth, mainPoolDepth);
    await add(SYN, USDC, U("500"), U("100"));
    await add(SYN, WETH, U("500"), E("0.1"));
    await add(WPOL, USDT, E("1"), U("10"));
    await add(WPOL, USDC, E("1"), U("10"));
    await add(WPOL, WETH, E("1"), E("0.01"));
    await add(USDT, USDC, U("10"), U("10"));
    await add(USDT, WETH, U("10"), E("0.01"));
    await add(USDC, WETH, U("10"), E("0.01"));

    for (const pool of internalPools) {
      const pair = new ethers.Contract(pool, PAIR_ABI, admin);
      const [r0, r1] = await pair.getReserves();
      assert.ok(r0 > 0n && r1 > 0n, `empty internal pool ${pool}`);
    }

    const mainPairAddress = await internalFactory.getPair(SYN, USDT);
    const mainPair = new ethers.Contract(mainPairAddress, PAIR_ABI, admin);
    const Executor = await ethers.getContractFactory("SynergyAtomicQeQtCycleV11", admin);
    const executor = await Executor.deploy(
      SYN,
      USDT,
      WPOL,
      await internalRouter.getAddress(),
      mainPairAddress,
      QS_V3_ROUTER,
      QS_V2_ROUTER,
      treasury.address
    );
    await executor.waitForDeployment();
    await (await synthetic.setController(await executor.getAddress())).wait();
    await eligible(registry, admin, await executor.getAddress(), "v8-executor");

    const V8 = await ethers.getContractFactory("StatefulSupercycleV8", admin);
    const supercycle = await V8.deploy(
      await executor.getAddress(),
      USDT,
      treasury.address,
      U("0.25")
    );
    await supercycle.waitForDeployment();
    await (await supercycle.setKeeper(keeper.address, true)).wait();
    await (await executor.setKeeper(await supercycle.getAddress(), true)).wait();
    await (await supercycle.configureTopology(internalPools, external.pools)).wait();
    assert.equal(await supercycle.topologyConfigured(), true);

    const boundary = [
      treasury.address,
      await executor.getAddress(),
      await supercycle.getAddress(),
      ...internalPools
    ];
    const realAssets = [WPOL, USDT, USDC, WETH];
    const totalsBefore = await boundaryTotals(realAssets, boundary);
    const supplyBefore = await synthetic.totalSupply();
    const mainBefore = await pairState(mainPair, SYN, USDT);

    const preShockPlan = await choosePlan(mainPair, SYN, quoter, v2Router, U("0.5"));
    assert.equal(preShockPlan, null, "unexpected profitable route without independent order flow");

    let remainingShock = shockFunding;
    let totalGasUsdt = 0n;
    let totalIndependentShock = 0n;
    const cycleRows = [];

    for (let cycle = 1; cycle <= SUCCESS_CYCLES; cycle++) {
      let chosen = await choosePlan(mainPair, SYN, quoter, v2Router, U("0.5"));
      for (const fractionBps of [500n, 750n, 1000n, 1250n, 1500n]) {
        if (chosen) break;
        const amount = (shockFunding * fractionBps) / 10000n;
        if (amount === 0n || amount > remainingShock) continue;
        await shockV2(shocker, usdt, v2Router, amount);
        remainingShock -= amount;
        totalIndependentShock += amount;
        chosen = await choosePlan(mainPair, SYN, quoter, v2Router, U("0.5"));
      }
      assert.ok(chosen, `cycle ${cycle}: no profitable real external route`);

      const block = await ethers.provider.getBlock("latest");
      const plan = {
        sourceId: source(`v8-cycle-source-${cycle}`),
        nonce: BigInt(cycle),
        deadline: BigInt(block.timestamp + 600),
        qeMint: chosen.mint,
        minExtractedUsdt: (chosen.extracted * 999n) / 1000n,
        minWpolFromV3: (chosen.wpolOut * 995n) / 1000n,
        minUsdtFromV2: (chosen.usdtOut * 995n) / 1000n,
        minTreasuryProfit: U("0.25")
      };

      const pairBefore = await pairState(mainPair, SYN, USDT);
      const treasuryBefore = await usdt.balanceOf(treasury.address);
      const tx = await supercycle
        .connect(keeper)
        .executeCycle(plan, source(`v8-cycle-id-${cycle}`), { gasPrice: GAS_PRICE });
      const receipt = await tx.wait();
      const pairAfter = await pairState(mainPair, SYN, USDT);
      const treasuryAfter = await usdt.balanceOf(treasury.address);

      const gasPol = receipt.gasUsed * receipt.gasPrice;
      const gasQuote = await v2Router.getAmountsOut(gasPol, [WPOL, USDT]);
      const gasUsdt = gasQuote[1];
      totalGasUsdt += gasUsdt;

      assert.equal(await executor.temporaryOutstanding(), 0n);
      assert.equal(await synthetic.totalSupply(), supplyBefore);
      assert.ok(pairAfter.syntheticReserve + (await executor.lastSyntheticDust()) >= pairBefore.syntheticReserve);
      assert.ok(pairAfter.liquidReserve >= pairBefore.liquidReserve);
      assert.ok(pairAfter.k >= pairBefore.k);
      assert.ok(treasuryAfter > treasuryBefore);
      assert.ok(treasuryAfter - treasuryBefore > gasUsdt);

      cycleRows.push({
        cycle,
        qeMint: fmt6(chosen.mint),
        extractedUsdt: fmt6(await executor.lastExtractedUsdt()),
        externalUsdt: fmt6(await executor.lastExternalUsdt()),
        buybackUsdt: fmt6(await executor.lastBuybackUsdt()),
        treasuryProfitUsdt: fmt6(treasuryAfter - treasuryBefore),
        lpLiquidGainUsdt: fmt6(pairAfter.liquidReserve - pairBefore.liquidReserve),
        gasUsdt: fmt6(gasUsdt),
        kBefore: pairBefore.k.toString(),
        kAfter: pairAfter.k.toString()
      });
    }

    const totalsAfter = await boundaryTotals(realAssets, boundary);
    const mainAfter = await pairState(mainPair, SYN, USDT);
    assert.equal(totalsAfter[WPOL.toLowerCase()], totalsBefore[WPOL.toLowerCase()]);
    assert.equal(totalsAfter[USDC.toLowerCase()], totalsBefore[USDC.toLowerCase()]);
    assert.equal(totalsAfter[WETH.toLowerCase()], totalsBefore[WETH.toLowerCase()]);
    assert.ok(totalsAfter[USDT.toLowerCase()] > totalsBefore[USDT.toLowerCase()]);
    assert.ok(mainAfter.liquidReserve >= mainBefore.liquidReserve);
    assert.ok(mainAfter.syntheticReserve >= mainBefore.syntheticReserve);
    assert.ok(mainAfter.k >= mainBefore.k);
    assert.equal(await supercycle.completedCycles(), BigInt(SUCCESS_CYCLES));
    assert.ok(await supercycle.cumulativeConsolidatedProfit() > totalGasUsdt);

    const firstPlan = {
      sourceId: source("v8-replay-source"),
      nonce: 999n,
      deadline: BigInt((await ethers.provider.getBlock("latest")).timestamp + 600),
      qeMint: 1n,
      minExtractedUsdt: 1n,
      minWpolFromV3: 1n,
      minUsdtFromV2: 1n,
      minTreasuryProfit: 1n
    };
    await expectRevert(
      supercycle.connect(attacker).executeCycle(firstPlan, source("v8-unauthorized"))
    );

    const report = {
      scenario: "stateful_supercycle_v8_10x10_polygon_fork",
      forkBlock: Number(process.env.FORK_BLOCK_NUMBER || 90790000),
      realPolygonContracts: true,
      internalPermissionedPools: internalPools.length,
      externalQuickSwapPools: external.pools.length,
      internalPoolAddresses: internalPools,
      externalPoolMetadata: external.metadata,
      successfulCycles: SUCCESS_CYCLES,
      independentExternalShockUsdt: fmt6(totalIndependentShock),
      cumulativeTreasuryProfitUsdt: fmt6(await supercycle.cumulativeConsolidatedProfit()),
      cumulativeGasUsdtAt274Gwei: fmt6(totalGasUsdt),
      consolidatedUsdtGain: fmt6(
        totalsAfter[USDT.toLowerCase()] - totalsBefore[USDT.toLowerCase()]
      ),
      otherProtocolAssetsPreserved: true,
      syntheticSupplyRestored: (await synthetic.totalSupply()) === supplyBefore,
      temporarySupplyClosed: (await executor.temporaryOutstanding()) === 0n,
      mainPoolLiquidRestored: mainAfter.liquidReserve >= mainBefore.liquidReserve,
      mainPoolSyntheticRestored: mainAfter.syntheticReserve >= mainBefore.syntheticReserve,
      mainPoolKNonDecreasing: mainAfter.k >= mainBefore.k,
      profitAfterGasPositive:
        (await supercycle.cumulativeConsolidatedProfit()) > totalGasUsdt,
      internalTransferRevenue: 0,
      limitation:
        "The external price edge is created by independent fork order flow. QE sizes the internal gradient and QT closes it; internal repricing alone is not counted as external profit. No live-mainnet profitability is claimed.",
      cycles: cycleRows,
      pass: true
    };

    fs.mkdirSync(path.join(process.cwd(), "reports"), { recursive: true });
    fs.writeFileSync(
      path.join(process.cwd(), "reports", "stateful_supercycle_v8_10x10_polygon_fork.json"),
      JSON.stringify(report, null, 2)
    );
    console.log(`STATEFUL_V8_10X10_RESULT ${JSON.stringify(report)}`);
  });
});
