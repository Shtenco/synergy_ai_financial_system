const assert = require("node:assert/strict");
const fs = require("node:fs");
const { ethers, network } = require("hardhat");

const WPOL = "0x0d500B1d8E8eF31E21C99d1Db9A6444d3ADf1270";
const USDT = "0xc2132D05D31c914a87C6611C10748AEb04B58e8F";
const USDC_E = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174";
const USDC = "0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359";
const DAI = "0x8f3Cf7ad23Cd3CaDbD9735AFf958023239c6A063";
const QS_V2_FACTORY = "0x5757371414417b8C6CAad45bAeF941aBc7d3Ab32";
const QS_V2_WPOL_USDT = "0x604229c960e5CACF2aaEAc8Be68Ac07BA9dF81c3";
const QS_V3_WPOL_USDT = "0x5b41EEDCfC8e0AE47493d4945Aa1AE4fe05430ff";

const ERC20_ABI = [
  "function balanceOf(address) view returns(uint256)",
  "function transfer(address,uint256) returns(bool)",
  "function approve(address,uint256) returns(bool)",
  "function deposit() payable",
  "function totalSupply() view returns(uint256)"
];
const FACTORY_ABI = ["function getPair(address,address) view returns(address)"];
const PAIR_ABI = [
  "function token0() view returns(address)",
  "function token1() view returns(address)",
  "function getReserves() view returns(uint112,uint112,uint32)",
  "function swap(uint256,uint256,address,bytes)"
];

const U = (v) => ethers.parseUnits(String(v), 6);
const E = (v) => ethers.parseEther(String(v));
const min = (a, b) => (a < b ? a : b);
const abs = (x) => (x < 0n ? -x : x);
const fmt6 = (x) => Number(ethers.formatUnits(x, 6));
const fmt18 = (x) => Number(ethers.formatUnits(x, 18));

function quoteV2(amountIn, reserveIn, reserveOut) {
  if (amountIn <= 0n) return 0n;
  const amountInWithFee = amountIn * 997n;
  return amountInWithFee * reserveOut / (reserveIn * 1000n + amountInWithFee);
}

async function pairState(pair) {
  const token0 = (await pair.token0()).toLowerCase();
  const token1 = (await pair.token1()).toLowerCase();
  const [r0, r1] = await pair.getReserves();
  if (token0 === WPOL.toLowerCase() && token1 === USDT.toLowerCase()) {
    return { reserveWpol: r0, reserveUsdt: r1, token0 };
  }
  if (token1 === WPOL.toLowerCase() && token0 === USDT.toLowerCase()) {
    return { reserveWpol: r1, reserveUsdt: r0, token0 };
  }
  throw new Error("Unexpected QuickSwap V2 pair tokens");
}

async function swapWpolForUsdt(pair, wpol, amountIn, recipient) {
  const before = await new ethers.Contract(USDT, ERC20_ABI, ethers.provider)
    .balanceOf(recipient);
  const state = await pairState(pair);
  const amountOut = quoteV2(amountIn, state.reserveWpol, state.reserveUsdt);
  await (await wpol.transfer(await pair.getAddress(), amountIn)).wait();
  const token0 = (await pair.token0()).toLowerCase();
  const amount0Out = token0 === USDT.toLowerCase() ? amountOut : 0n;
  const amount1Out = token0 === USDT.toLowerCase() ? 0n : amountOut;
  const receipt = await (await pair.swap(amount0Out, amount1Out, recipient, "0x")).wait();
  const after = await new ethers.Contract(USDT, ERC20_ABI, ethers.provider)
    .balanceOf(recipient);
  assert.equal(after - before, amountOut);
  return { amountOut, receipt };
}

async function findUsdtDonor(factory, usdt) {
  const candidates = [];
  for (const token of [USDC_E, USDC, DAI]) {
    const pair = await factory.getPair(USDT, token);
    if (pair !== ethers.ZeroAddress && pair.toLowerCase() !== QS_V2_WPOL_USDT.toLowerCase()) {
      candidates.push(pair);
    }
  }
  candidates.push(QS_V3_WPOL_USDT);
  let best = null;
  for (const address of candidates) {
    const code = await ethers.provider.getCode(address);
    if (code === "0x") continue;
    const balance = await usdt.balanceOf(address);
    if (!best || balance > best.balance) best = { address, balance };
  }
  if (!best || best.balance < U("5000")) {
    throw new Error(`No independent USDT donor found; best=${best ? fmt6(best.balance) : 0}`);
  }
  return best;
}

async function fundFromDonor(donor, usdt, recipient, amount) {
  await network.provider.send("anvil_impersonateAccount", [donor]);
  await network.provider.send("anvil_setBalance", [donor, ethers.toBeHex(E("100"))]);
  const provider = new ethers.JsonRpcProvider(
    process.env.LOCAL_FORK_URL || "http://127.0.0.1:8545"
  );
  const signer = await provider.getSigner(donor);
  const token = new ethers.Contract(USDT, ERC20_ABI, signer);
  await (await token.transfer(recipient, amount)).wait();
  await network.provider.send("anvil_stopImpersonatingAccount", [donor]);
}

function gasUsdtRaw(receipts, referenceReserveUsdt, referenceReserveWpol) {
  let nativeRaw = 0n;
  for (const receipt of receipts) {
    if (!receipt) continue;
    nativeRaw += receipt.gasUsed * receipt.gasPrice;
  }
  return nativeRaw * referenceReserveUsdt / referenceReserveWpol;
}

async function sendAndTrack(promise, receipts) {
  const tx = await promise;
  const receipt = await tx.wait();
  receipts.push(receipt);
  return receipt;
}

describe("V12 self-created internal gradient on a pinned Polygon fork", function () {
  this.timeout(1_800_000);

  it("measures external USDT paid, wallet profit, LP loss and consolidated NAV without external shock", async function () {
    const [deployer, treasury, fixtureSink] = await ethers.getSigners();
    fs.mkdirSync("reports", { recursive: true });

    for (const address of [WPOL, USDT, QS_V2_FACTORY, QS_V2_WPOL_USDT]) {
      assert.notEqual(await ethers.provider.getCode(address), "0x");
    }

    await network.provider.send("anvil_setBalance", [
      deployer.address,
      ethers.toBeHex(E("1000000"))
    ]);

    const wpol = new ethers.Contract(WPOL, ERC20_ABI, deployer);
    const usdt = new ethers.Contract(USDT, ERC20_ABI, deployer);
    const factory = new ethers.Contract(QS_V2_FACTORY, FACTORY_ABI, deployer);
    const externalPair = new ethers.Contract(QS_V2_WPOL_USDT, PAIR_ABI, deployer);

    const donor = await findUsdtDonor(factory, usdt);
    const targetSeed = U("100000");
    const safeFromDonor = donor.balance / 5n;
    const seedUsdt = min(targetSeed, safeFromDonor);
    assert.ok(seedUsdt >= U("5000"));
    await fundFromDonor(donor.address, usdt, deployer.address, seedUsdt);

    const externalStart = await pairState(externalPair);
    const wpolSeed = seedUsdt * externalStart.reserveWpol / externalStart.reserveUsdt;
    await (await wpol.deposit({ value: wpolSeed + wpolSeed / 10n })).wait();

    const Synth = await ethers.getContractFactory("GradientProbeSyntheticV12", deployer);
    const synth = await Synth.deploy(deployer.address);
    await synth.waitForDeployment();
    const Pool = await ethers.getContractFactory("GradientProbePoolV12", deployer);
    const poolWpol = await Pool.deploy(await synth.getAddress(), WPOL);
    await poolWpol.waitForDeployment();
    const poolUsdt = await Pool.deploy(await synth.getAddress(), USDT);
    await poolUsdt.waitForDeployment();

    const synthSeed = seedUsdt * 10n ** 12n;
    await (await synth.mint(deployer.address, synthSeed * 2n)).wait();
    await (await synth.approve(await poolWpol.getAddress(), ethers.MaxUint256)).wait();
    await (await synth.approve(await poolUsdt.getAddress(), ethers.MaxUint256)).wait();
    await (await wpol.approve(await poolWpol.getAddress(), ethers.MaxUint256)).wait();
    await (await usdt.approve(await poolUsdt.getAddress(), ethers.MaxUint256)).wait();
    await (await poolWpol.seed(synthSeed, wpolSeed)).wait();
    await (await poolUsdt.seed(synthSeed, seedUsdt)).wait();

    // Remove all fixture leftovers before measurement. Test cycles must fund themselves.
    const fixtureUsdtLeft = await usdt.balanceOf(deployer.address);
    if (fixtureUsdtLeft > 0n) await (await usdt.transfer(fixtureSink.address, fixtureUsdtLeft)).wait();
    const fixtureWpolLeft = await wpol.balanceOf(deployer.address);
    if (fixtureWpolLeft > 0n) await (await wpol.transfer(fixtureSink.address, fixtureWpolLeft)).wait();

    // QE/QT creates the entire internal gradient. No external trade or shock occurs here.
    const gradientShift = synthSeed * 40n / 100n;
    await (await synth.burn(await poolWpol.getAddress(), gradientShift)).wait();
    await (await synth.mint(await poolUsdt.getAddress(), gradientShift)).wait();
    await (await poolWpol.sync()).wait();
    await (await poolUsdt.sync()).wait();

    const targetWpolSynth = synthSeed - gradientShift;
    const targetUsdtSynth = synthSeed + gradientShift;
    const totalSupplyBaseline = await synth.totalSupply();
    const [startWpolSynth, startWpolLiquid] = await poolWpol.getReserves();
    const [startUsdtSynth, startUsdtLiquid] = await poolUsdt.getReserves();
    assert.equal(startWpolSynth, targetWpolSynth);
    assert.equal(startUsdtSynth, targetUsdtSynth);

    const referenceReserveWpol = externalStart.reserveWpol;
    const referenceReserveUsdt = externalStart.reserveUsdt;
    const valueWpolInUsdt = (amount) => amount * referenceReserveUsdt / referenceReserveWpol;
    const internalStartNav = valueWpolInUsdt(startWpolLiquid) + startUsdtLiquid;
    const externalStartNav = valueWpolInUsdt(externalStart.reserveWpol) + externalStart.reserveUsdt;
    const externalStartK = externalStart.reserveWpol * externalStart.reserveUsdt;

    const cycles = [];
    let cumulativeExternalUsdtPaid = 0n;
    let cumulativeWalletProfit = 0n;
    let cumulativeGas = 0n;

    for (let cycle = 1; cycle <= 12; cycle++) {
      const [rwSynth] = await poolWpol.getReserves();
      const candidates = [5n, 10n, 20n, 30n, 40n, 50n, 60n, 80n, 100n]
        .map((bps) => rwSynth * bps / 1000n)
        .filter((q) => q > 0n);
      let best = null;
      const ext = await pairState(externalPair);
      for (const q of candidates) {
        const wpolOut = await poolWpol.quoteLiquidOut(q);
        const externalUsdtOut = quoteV2(wpolOut, ext.reserveWpol, ext.reserveUsdt);
        let usdtNeeded;
        try {
          usdtNeeded = await poolUsdt.quoteLiquidForExactSynthetic(q);
        } catch (_) {
          continue;
        }
        const walletProfit = externalUsdtOut - usdtNeeded;
        if (!best || walletProfit > best.walletProfit) {
          best = { q, wpolOut, externalUsdtOut, usdtNeeded, walletProfit };
        }
      }
      if (!best || best.walletProfit <= 0n) break;

      const receipts = [];
      const treasuryBefore = await usdt.balanceOf(treasury.address);
      await sendAndTrack(synth.mint(deployer.address, best.q), receipts);
      await sendAndTrack(
        poolWpol.swapExactSyntheticForLiquid(best.q, 0, deployer.address),
        receipts
      );
      const wpolExtracted = await wpol.balanceOf(deployer.address);
      assert.equal(wpolExtracted, best.wpolOut);

      const externalSwap = await swapWpolForUsdt(
        externalPair,
        wpol,
        wpolExtracted,
        deployer.address
      );
      receipts.push(externalSwap.receipt);
      const externalUsdtPaid = externalSwap.amountOut;
      const buybackUsdt = await poolUsdt.quoteLiquidForExactSynthetic(best.q);
      assert.ok(externalUsdtPaid > buybackUsdt);
      await sendAndTrack(
        poolUsdt.swapLiquidForExactSynthetic(
          best.q,
          externalUsdtPaid,
          deployer.address
        ),
        receipts
      );
      await sendAndTrack(synth.burn(deployer.address, best.q), receipts);

      // Reset the synthetic price gradient only through QE/QT. No liquid is injected.
      await sendAndTrack(synth.burn(await poolWpol.getAddress(), best.q), receipts);
      await sendAndTrack(synth.mint(await poolUsdt.getAddress(), best.q), receipts);
      await sendAndTrack(poolWpol.sync(), receipts);
      await sendAndTrack(poolUsdt.sync(), receipts);

      const walletProfit = await usdt.balanceOf(deployer.address);
      assert.equal(walletProfit, externalUsdtPaid - buybackUsdt);
      await sendAndTrack(usdt.transfer(treasury.address, walletProfit), receipts);
      assert.equal(await usdt.balanceOf(deployer.address), 0n);
      assert.equal(await wpol.balanceOf(deployer.address), 0n);

      const [afterWpolSynth, afterWpolLiquid] = await poolWpol.getReserves();
      const [afterUsdtSynth, afterUsdtLiquid] = await poolUsdt.getReserves();
      assert.equal(afterWpolSynth, targetWpolSynth);
      assert.equal(afterUsdtSynth, targetUsdtSynth);
      assert.equal(await synth.totalSupply(), totalSupplyBaseline);

      const treasuryAfter = await usdt.balanceOf(treasury.address);
      assert.equal(treasuryAfter - treasuryBefore, walletProfit);
      const internalNav = valueWpolInUsdt(afterWpolLiquid) + afterUsdtLiquid;
      const treasuryNav = treasuryAfter;
      const protocolNav = internalNav + treasuryNav;
      const protocolDelta = protocolNav - internalStartNav;
      const internalLpDelta = internalNav - internalStartNav;
      const extAfter = await pairState(externalPair);
      const externalNav = valueWpolInUsdt(extAfter.reserveWpol) + extAfter.reserveUsdt;
      const externalDelta = externalNav - externalStartNav;
      const identityError = protocolDelta + externalDelta;
      const gasRaw = gasUsdtRaw(receipts, referenceReserveUsdt, referenceReserveWpol);

      cumulativeExternalUsdtPaid += externalUsdtPaid;
      cumulativeWalletProfit += walletProfit;
      cumulativeGas += gasRaw;

      cycles.push({
        cycle,
        qeAmountSynth: fmt18(best.q),
        wpolTakenFromInternalPool: fmt18(wpolExtracted),
        wpolMarketValueUsdt: fmt6(valueWpolInUsdt(wpolExtracted)),
        externalPoolUsdtPaid: fmt6(externalUsdtPaid),
        externalPoolWpolReceived: fmt18(wpolExtracted),
        usdtSpentToBuyBackSynthetic: fmt6(buybackUsdt),
        walletProfitUsdt: fmt6(walletProfit),
        internalLpDeltaUsdt: fmt6(internalLpDelta),
        treasuryCumulativeUsdt: fmt6(treasuryAfter),
        protocolConsolidatedDeltaUsdt: fmt6(protocolDelta),
        externalPoolDeltaAtReferenceUsdt: fmt6(externalDelta),
        accountingIdentityErrorUsdt: fmt6(identityError),
        cumulativeGasUsdt: fmt6(cumulativeGas),
        protocolDeltaAfterGasUsdt: fmt6(protocolDelta - cumulativeGas),
        poolWpolLiquidRemainingRatio: Number(afterWpolLiquid) / Number(startWpolLiquid),
        poolUsdtLiquidGrowthRatio: Number(afterUsdtLiquid) / Number(startUsdtLiquid)
      });
      assert.ok(abs(identityError) <= 5n, `value identity error: ${identityError}`);
    }

    assert.ok(cycles.length > 0, "QE/QT gradient did not create even wallet-level profit");
    const [finalWpolSynth, finalWpolLiquid] = await poolWpol.getReserves();
    const [finalUsdtSynth, finalUsdtLiquid] = await poolUsdt.getReserves();
    const treasuryFinal = await usdt.balanceOf(treasury.address);
    const finalInternalNav = valueWpolInUsdt(finalWpolLiquid) + finalUsdtLiquid;
    const finalProtocolNav = finalInternalNav + treasuryFinal;
    const finalProtocolDelta = finalProtocolNav - internalStartNav;
    const externalFinal = await pairState(externalPair);
    const externalFinalNav = valueWpolInUsdt(externalFinal.reserveWpol) + externalFinal.reserveUsdt;
    const externalFinalDelta = externalFinalNav - externalStartNav;
    const externalFinalK = externalFinal.reserveWpol * externalFinal.reserveUsdt;

    // Reinvesting treasury USDT into a protocol-owned pool changes location, not NAV.
    const navBeforeReinvestment = finalProtocolNav;
    if (treasuryFinal > 0n) {
      const usdtTreasury = usdt.connect(treasury);
      await (await usdtTreasury.transfer(await poolUsdt.getAddress(), treasuryFinal)).wait();
      await (await poolUsdt.sync()).wait();
    }
    const [, postReinvestWpolLiquid] = await poolWpol.getReserves();
    const [, postReinvestUsdtLiquid] = await poolUsdt.getReserves();
    const postReinvestTreasury = await usdt.balanceOf(treasury.address);
    const navAfterReinvestment =
      valueWpolInUsdt(postReinvestWpolLiquid) + postReinvestUsdtLiquid + postReinvestTreasury;

    const report = {
      forkBlock: Number(process.env.FORK_BLOCK_NUMBER || 90790000),
      hypothesis: "QE/QT alone creates an internal liquid-token gradient; liquid is sold to an initially unshocked external pool; profit is returned and gradient reset",
      externalShockApplied: false,
      gradientCreatedOnlyByInternalQeQt: true,
      fixtureDonor: donor.address,
      fixtureDonorExcludedFromMeasuredSystem: true,
      externalPair: QS_V2_WPOL_USDT,
      initialReference: {
        seedPerPoolUsdt: fmt6(seedUsdt),
        wpolPriceUsdt: Number(referenceReserveUsdt) / Number(referenceReserveWpol) * 1e12,
        internalProtocolNavUsdt: fmt6(internalStartNav),
        externalPoolNavUsdt: fmt6(externalStartNav)
      },
      gradient: {
        syntheticBurnedFromWpolPool: fmt18(gradientShift),
        syntheticMintedToUsdtPool: fmt18(gradientShift),
        totalSupplyChanged: false,
        wpolPoolSyntheticReserve: fmt18(targetWpolSynth),
        usdtPoolSyntheticReserve: fmt18(targetUsdtSynth)
      },
      cycles,
      totalsBeforeReinvestment: {
        completedCycles: cycles.length,
        externalPoolUsdtPaid: fmt6(cumulativeExternalUsdtPaid),
        treasuryWalletProfitUsdt: fmt6(cumulativeWalletProfit),
        internalLpDeltaUsdt: fmt6(finalInternalNav - internalStartNav),
        protocolConsolidatedDeltaUsdt: fmt6(finalProtocolDelta),
        gasUsdt: fmt6(cumulativeGas),
        protocolDeltaAfterGasUsdt: fmt6(finalProtocolDelta - cumulativeGas),
        externalPoolDeltaAtReferenceUsdt: fmt6(externalFinalDelta),
        protocolPlusExternalIdentityErrorUsdt: fmt6(finalProtocolDelta + externalFinalDelta),
        externalPairKRatio: Number(externalFinalK) / Number(externalStartK),
        wpolPoolLiquidRemainingRatio: Number(finalWpolLiquid) / Number(startWpolLiquid),
        usdtPoolLiquidGrowthRatio: Number(finalUsdtLiquid) / Number(startUsdtLiquid)
      },
      reinvestment: {
        treasuryMovedBackIntoProtocolPool: true,
        navBeforeUsdt: fmt6(navBeforeReinvestment),
        navAfterUsdt: fmt6(navAfterReinvestment),
        navChangeUsdt: fmt6(navAfterReinvestment - navBeforeReinvestment)
      },
      invariants: {
        temporarySupplyZero: (await synth.totalSupply()) === totalSupplyBaseline,
        wpolPoolSyntheticReserveRestored: finalWpolSynth === targetWpolSynth,
        usdtPoolSyntheticReserveRestored: finalUsdtSynth === targetUsdtSynth,
        externalPoolActuallyPaidUsdt: cumulativeExternalUsdtPaid > 0n,
        walletProfitWasPositive: cumulativeWalletProfit > 0n,
        externalPairKNonDecreasing: externalFinalK >= externalStartK,
        accountingIdentityClosed: abs(finalProtocolDelta + externalFinalDelta) <= 5n,
        reinvestmentDoesNotCreateValue: abs(navAfterReinvestment - navBeforeReinvestment) <= 1n
      },
      economicVerdict:
        finalProtocolDelta > 5n
          ? "SELF_CREATED_GRADIENT_INCREASED_CONSOLIDATED_PROTOCOL_NAV"
          : finalProtocolDelta < -5n
            ? "WALLET_PROFIT_CAME_FROM_INTERNAL_LP_VALUE_AND_EXTERNAL_FEES"
            : "SELF_CREATED_GRADIENT_WAS_NAV_NEUTRAL_BEFORE_GAS"
    };

    fs.writeFileSync(
      "reports/self_created_gradient_v12_polygon_fork.json",
      JSON.stringify(report, null, 2)
    );

    for (const [name, passed] of Object.entries(report.invariants)) {
      assert.equal(passed, true, `${name} failed`);
    }
  });
});
