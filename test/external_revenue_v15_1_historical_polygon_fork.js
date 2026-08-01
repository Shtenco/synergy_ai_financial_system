"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { ethers, network } = require("hardhat");

const CHAIN_ID = 137n;
const HISTORICAL_TX_HASH = process.env.HISTORICAL_VICTIM_TX_HASH || "";
const HISTORICAL_BLOCK = Number(process.env.HISTORICAL_VICTIM_BLOCK || 0);
const UPSTREAM_RPC = process.env.SELECTED_POLYGON_RPC || process.env.POLYGON_RPC_URL || "";

const WPOL = "0x0d500B1d8E8eF31E21C99d1Db9A6444d3ADf1270";
const USDC = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174";
const QS_V2_FACTORY = "0x5757371414417b8C6CAad45bAeF941aBc7d3Ab32";
const QS_V2_ROUTER = "0xa5E0829CaCEd8fFDD4De3c43696c57F7D7A678ff";
const UNI_V3_FACTORY = "0x1F98431c8aD98523631AE4a59f267346ea31F984";
const UNI_V3_ROUTER = "0xE592427A0AEce92De3Edee1F18E0157C05861564";
const UNI_V3_QUOTER = "0xb27308f9F90D607463bb33eA1BeBb41C27CE5AB6";
const FIXTURE_USDC_DONOR = "0x853Ee4b2A13f8a742d64C8F088bE7bA2131f670d";

const MIN_EDGE_PPM = 269n;
const V14_REQUIRED_TREASURY_USDC = 121799n;
const U = (value) => ethers.parseUnits(value, 6);
const E = ethers.parseEther;
const minBig = (a, b) => (a < b ? a : b);
const fmt6 = (value) => Number(ethers.formatUnits(value, 6));

const ERC20_ABI = [
  "function approve(address,uint256) returns(bool)",
  "function transfer(address,uint256) returns(bool)",
  "function balanceOf(address) view returns(uint256)",
  "function totalSupply() view returns(uint256)"
];
const V2_FACTORY_ABI = ["function getPair(address,address) view returns(address)"];
const V3_FACTORY_ABI = ["function getPool(address,address,uint24) view returns(address)"];
const V2_ROUTER_ABI = [
  "function getAmountsOut(uint256,address[]) view returns(uint256[])",
  "function swapExactTokensForTokens(uint256,uint256,address[],address,uint256) returns(uint256[])"
];
const QUOTER_ABI = [
  "function quoteExactInputSingle(address,address,uint24,uint256,uint160) returns(uint256)"
];

async function setAutomine(enabled) {
  try {
    await network.provider.send("evm_setAutomine", [enabled]);
  } catch (_) {
    await network.provider.send("anvil_setAutomine", [enabled]);
  }
}

async function mineBlocks(count) {
  for (let i = 0; i < count; i += 1) {
    await network.provider.send("evm_mine", []);
  }
}

async function impersonate(address) {
  await network.provider.send("anvil_impersonateAccount", [address]);
  await network.provider.send("anvil_setBalance", [address, ethers.toBeHex(E("1000000"))]);
  return ethers.provider.getSigner(address);
}

async function stopImpersonating(address) {
  await network.provider.send("anvil_stopImpersonatingAccount", [address]);
}

async function fixtureTransfer(token, donor, recipient, amount) {
  const signer = await impersonate(donor);
  const contract = new ethers.Contract(token, ERC20_ABI, signer);
  const receipt = await (await contract.transfer(recipient, amount)).wait();
  await stopImpersonating(donor);
  return receipt;
}

async function quoteV3(quoter, tokenMid, fee, amountIn) {
  return quoter.quoteExactInputSingle.staticCall(USDC, tokenMid, fee, amountIn, 0n);
}

async function selectVenue(factoryV2, factoryV3, tokenMid) {
  const targetPair = await factoryV2.getPair(USDC, tokenMid);
  if (targetPair === ethers.ZeroAddress || await ethers.provider.getCode(targetPair) === "0x") {
    throw new Error("missing QuickSwap V2 victim venue");
  }
  for (const fee of [100, 500, 3000, 10000]) {
    const sourcePool = await factoryV3.getPool(USDC, tokenMid, fee);
    if (sourcePool !== ethers.ZeroAddress && await ethers.provider.getCode(sourcePool) !== "0x") {
      return { tokenMid, fee, targetPair, sourcePool };
    }
  }
  throw new Error("missing Uniswap V3 source venue");
}

async function replayHistoricalVictim(upstreamTx, gasPrice) {
  const victimSigner = await impersonate(upstreamTx.from);
  const tx = await victimSigner.sendTransaction({
    to: upstreamTx.to,
    data: upstreamTx.data,
    value: upstreamTx.value,
    gasLimit: upstreamTx.gasLimit || 2_500_000n,
    gasPrice
  });
  return { tx, victimSigner };
}

async function findCandidate({ upstreamTx, qsRouter, quoter, venue, solverBalance }) {
  const snapshot = await network.provider.send("evm_snapshot", []);
  try {
    const replay = await replayHistoricalVictim(upstreamTx, 200_000_000_000n);
    await (await replay.tx.wait());
    await stopImpersonating(upstreamTx.from);

    const targetUsdc = await new ethers.Contract(USDC, ERC20_ABI, ethers.provider)
      .balanceOf(venue.targetPair);
    const fractionsBps = [2n, 5n, 10n, 20n, 50n, 100n, 200n];
    let best = null;
    for (const fraction of fractionsBps) {
      const amountIn = minBig(targetUsdc * fraction / 10_000n, solverBalance * 80n / 100n);
      if (amountIn < U("25")) continue;
      try {
        const midOut = await quoteV3(quoter, venue.tokenMid, venue.fee, amountIn);
        const finalAmounts = await qsRouter.getAmountsOut(midOut, [venue.tokenMid, USDC]);
        const finalOut = finalAmounts[1];
        if (finalOut <= amountIn) continue;
        const grossProfit = finalOut - amountIn;
        const edgePpm = grossProfit * 1_000_000n / amountIn;
        const record = { amountIn, midOut, finalOut, grossProfit, edgePpm };
        if (!best || record.grossProfit > best.grossProfit) best = record;
      } catch (_) {
        // Quote is not executable at this size.
      }
    }
    return best;
  } finally {
    await network.provider.send("evm_revert", [snapshot]);
  }
}

async function receiptGasWei(receipt) {
  if (!receipt) return 0n;
  const tx = await ethers.provider.getTransaction(receipt.hash);
  const gasPrice = receipt.gasPrice ?? tx.gasPrice ?? 0n;
  return receipt.gasUsed * gasPrice;
}

function txIndex(receipt) {
  return Number(receipt.index ?? receipt.transactionIndex ?? -1);
}

function writeReport(report) {
  const reports = path.join(process.cwd(), "reports");
  fs.mkdirSync(reports, { recursive: true });
  fs.writeFileSync(
    path.join(reports, "v15_1_historical_polygon_fork.json"),
    JSON.stringify(report, null, 2)
  );
}

describe("SYNERGY V15.1 strict historical Polygon replay", function () {
  this.timeout(2_400_000);

  it("counts only a real historical victim and rational realized route profit", async function () {
    assert.ok(HISTORICAL_TX_HASH, "HISTORICAL_VICTIM_TX_HASH is required");
    assert.ok(HISTORICAL_BLOCK > 0, "HISTORICAL_VICTIM_BLOCK is required");
    assert.ok(UPSTREAM_RPC, "SELECTED_POLYGON_RPC or POLYGON_RPC_URL is required");
    assert.equal((await ethers.provider.getNetwork()).chainId, CHAIN_ID);
    assert.equal(await ethers.provider.getBlockNumber(), HISTORICAL_BLOCK - 1);

    const upstream = new ethers.JsonRpcProvider(UPSTREAM_RPC, 137, { staticNetwork: true });
    const upstreamTx = await upstream.getTransaction(HISTORICAL_TX_HASH);
    const upstreamReceipt = await upstream.getTransactionReceipt(HISTORICAL_TX_HASH);
    assert.ok(upstreamTx && upstreamReceipt && upstreamReceipt.status === 1);
    assert.equal(upstreamReceipt.blockNumber, HISTORICAL_BLOCK);
    assert.equal(upstreamTx.to.toLowerCase(), QS_V2_ROUTER.toLowerCase());

    const tokenMid = ethers.getAddress(process.env.HISTORICAL_TOKEN_MID);
    const [coordinator, treasury, solver1, solver2, solver3] = await ethers.getSigners();
    const usdc = new ethers.Contract(USDC, ERC20_ABI, coordinator);
    const qsFactory = new ethers.Contract(QS_V2_FACTORY, V2_FACTORY_ABI, coordinator);
    const uniFactory = new ethers.Contract(UNI_V3_FACTORY, V3_FACTORY_ABI, coordinator);
    const qsRouter = new ethers.Contract(QS_V2_ROUTER, V2_ROUTER_ABI, coordinator);
    const quoter = new ethers.Contract(UNI_V3_QUOTER, QUOTER_ABI, coordinator);
    const venue = await selectVenue(qsFactory, uniFactory, tokenMid);

    const donorBalanceBefore = await usdc.balanceOf(FIXTURE_USDC_DONOR);
    const targetPairBalanceBeforeFunding = await usdc.balanceOf(venue.targetPair);
    const solverFunding = minBig(donorBalanceBefore / 100n, U("100000"));
    assert.ok(solverFunding >= U("100"));
    const fundingReceipt = await fixtureTransfer(USDC, FIXTURE_USDC_DONOR, solver3.address, solverFunding);
    const donorBalanceAfterFunding = await usdc.balanceOf(FIXTURE_USDC_DONOR);
    assert.equal(donorBalanceBefore - donorBalanceAfterFunding, solverFunding);
    assert.equal(await usdc.balanceOf(venue.targetPair), targetPairBalanceBeforeFunding);

    const candidate = await findCandidate({
      upstreamTx,
      qsRouter,
      quoter,
      venue,
      solverBalance: await usdc.balanceOf(solver3.address)
    });

    if (!candidate || candidate.edgePpm < MIN_EDGE_PPM) {
      writeReport({
        scenario: "synergy_v15_1_historical_polygon_fork",
        evidenceStatus: "NO_HISTORICAL_EDGE_PROVEN_IN_SELECTED_TRANSACTION",
        chainId: 137,
        forkBlock: HISTORICAL_BLOCK - 1,
        historicalVictim: {
          transactionHash: HISTORICAL_TX_HASH,
          blockNumber: HISTORICAL_BLOCK,
          originalSender: upstreamTx.from,
          originalTarget: upstreamTx.to,
          originalCalldataHash: ethers.keccak256(upstreamTx.data),
          originalValue: upstreamTx.value.toString()
        },
        candidate: candidate ? {
          principalRaw: candidate.amountIn.toString(),
          grossProfitRaw: candidate.grossProfit.toString(),
          edgePpm: Number(candidate.edgePpm)
        } : null,
        fixtureFunding: {
          countedAsRevenue: false,
          source: FIXTURE_USDC_DONOR,
          amountRaw: solverFunding.toString(),
          selectedExecutionPoolUntouchedByFunding: true
        },
        strictCountedRevenueRaw: "0"
      });
      return;
    }

    const Auction = await ethers.getContractFactory("SolverAuctionV151", coordinator);
    const auction = await Auction.deploy(treasury.address, coordinator.address, E("0.05"));
    await auction.waitForDeployment();
    const Engine = await ethers.getContractFactory("ExternalRevenueEngineV151", coordinator);
    const engine = await Engine.deploy(await auction.getAddress(), treasury.address, coordinator.address);
    await engine.waitForDeployment();
    const V2Adapter = await ethers.getContractFactory("V2RouterAdapterV151", coordinator);
    const v2Adapter = await V2Adapter.deploy(QS_V2_ROUTER);
    await v2Adapter.waitForDeployment();
    const V3Adapter = await ethers.getContractFactory("V3RouterAdapterV151", coordinator);
    const v3Adapter = await V3Adapter.deploy(UNI_V3_ROUTER);
    await v3Adapter.waitForDeployment();

    const consumerReceipt = await (await auction.connect(treasury).setConsumer(await engine.getAddress())).wait();
    await (await engine.setAdapter(await v2Adapter.getAddress(), true)).wait();
    await (await engine.setAdapter(await v3Adapter.getAddress(), true)).wait();
    const approvalReceipt = await (await usdc.connect(solver3).approve(await engine.getAddress(), ethers.MaxUint256)).wait();

    const latest = await ethers.provider.getBlock("latest");
    const deadline = BigInt(latest.timestamp + 3600);
    const minMidOut = candidate.midOut * 998n / 1000n;
    const minFinalOut = candidate.finalOut * 997n / 1000n;
    const steps = [
      {
        adapter: await v3Adapter.getAddress(),
        tokenIn: USDC,
        tokenOut: tokenMid,
        minAmountOut: minMidOut,
        data: ethers.AbiCoder.defaultAbiCoder().encode(
          ["uint24", "uint160", "uint256"],
          [venue.fee, 0n, deadline]
        )
      },
      {
        adapter: await v2Adapter.getAddress(),
        tokenIn: tokenMid,
        tokenOut: USDC,
        minAmountOut: minFinalOut,
        data: ethers.AbiCoder.defaultAbiCoder().encode(
          ["address[]", "uint256"],
          [[tokenMid, USDC], deadline]
        )
      }
    ];

    const venuesHash = ethers.keccak256(
      ethers.AbiCoder.defaultAbiCoder().encode(
        ["string", "address", "address", "address", "address", "uint24"],
        ["UNISWAP_V3_TO_QUICKSWAP_V2", venue.sourcePool, venue.targetPair, UNI_V3_ROUTER, QS_V2_ROUTER, venue.fee]
      )
    );
    const beforePublishBlock = await ethers.provider.getBlockNumber();
    const closeBlock = beforePublishBlock + 8;
    const expiryBlock = closeBlock + 40;
    const publishReceipt = await (
      await auction.publish(
        USDC,
        candidate.amountIn,
        V14_REQUIRED_TREASURY_USDC,
        MIN_EDGE_PPM,
        5000,
        closeBlock,
        expiryBlock,
        venuesHash
      )
    ).wait();
    const epoch = await auction.currentEpoch();
    const solutionHash = await engine.hashRoute(epoch, USDC, candidate.amountIn, steps);

    const bidReceipts = [];
    for (const [solver, share] of [[solver1, 6000], [solver2, 7000], [solver3, 8000]]) {
      bidReceipts.push(await (
        await auction.connect(solver).bid(epoch, solutionHash, share, { value: E("0.05") })
      ).wait());
    }
    const nowBlock = await ethers.provider.getBlockNumber();
    if (nowBlock <= closeBlock) await mineBlocks(closeBlock - nowBlock + 1);
    const settleReceipt = await (await auction.settle(epoch)).wait();

    const winning = await auction.best(epoch);
    assert.equal(winning[0].toLowerCase(), solver3.address.toLowerCase());
    assert.equal(Number(winning[2]), 8000);
    assert.equal(winning[3], solutionHash);

    const treasuryBefore = await usdc.balanceOf(treasury.address);
    const solverBefore = await usdc.balanceOf(solver3.address);
    const targetPairBeforeExecution = await usdc.balanceOf(venue.targetPair);
    const sourcePoolBeforeExecution = await usdc.balanceOf(venue.sourcePool);
    const totalSupplyBefore = await usdc.totalSupply();

    const block = await ethers.provider.getBlock("latest");
    const baseFee = block.baseFeePerGas || 30_000_000_000n;
    const victimGasPrice = baseFee * 4n + 2_000_000_000n;
    const backrunGasPrice = baseFee * 3n + 1_000_000_000n;

    await setAutomine(false);
    let replay;
    let backrunTx;
    try {
      replay = await replayHistoricalVictim(upstreamTx, victimGasPrice);
      backrunTx = await engine.connect(solver3).execute(
        epoch,
        solutionHash,
        USDC,
        candidate.amountIn,
        steps,
        { gasLimit: 3_500_000n, gasPrice: backrunGasPrice }
      );
      await network.provider.send("evm_mine", []);
    } finally {
      await setAutomine(true);
    }

    const victimReceipt = await replay.tx.wait();
    const backrunReceipt = await backrunTx.wait();
    await stopImpersonating(upstreamTx.from);
    assert.equal(victimReceipt.status, 1);
    assert.equal(backrunReceipt.status, 1);
    assert.equal(victimReceipt.blockNumber, backrunReceipt.blockNumber);
    assert.ok(txIndex(victimReceipt) < txIndex(backrunReceipt));

    const treasuryRevenue = (await usdc.balanceOf(treasury.address)) - treasuryBefore;
    const solverRevenue = (await usdc.balanceOf(solver3.address)) - solverBefore;
    const grossProfit = treasuryRevenue + solverRevenue;
    const edgePpm = grossProfit * 1_000_000n / candidate.amountIn;
    assert.ok(treasuryRevenue >= V14_REQUIRED_TREASURY_USDC);
    assert.ok(edgePpm >= MIN_EDGE_PPM);
    assert.ok(solverRevenue > 0n);
    assert.equal(await auction.consumed(epoch), true);
    assert.equal(await usdc.totalSupply(), totalSupplyBefore);

    const refundReceipt = await (await auction.connect(solver3).withdrawRefund()).wait();

    const countedReceipts = [
      consumerReceipt,
      approvalReceipt,
      publishReceipt,
      bidReceipts[2],
      settleReceipt,
      backrunReceipt,
      refundReceipt
    ];
    let operationalGasWei = 0n;
    for (const receipt of countedReceipts) operationalGasWei += await receiptGasWei(receipt);
    const gasQuote = await qsRouter.getAmountsOut(operationalGasWei, [WPOL, USDC]);
    const operationalGasUsdc = gasQuote[1];
    const aggregateNetAfterGas = grossProfit > operationalGasUsdc
      ? grossProfit - operationalGasUsdc
      : 0n;
    const solverExecutionGasWei = await receiptGasWei(bidReceipts[2])
      + await receiptGasWei(backrunReceipt)
      + await receiptGasWei(refundReceipt)
      + await receiptGasWei(approvalReceipt);
    const solverGasQuote = await qsRouter.getAmountsOut(solverExecutionGasWei, [WPOL, USDC]);
    const solverNetAfterGas = solverRevenue > solverGasQuote[1]
      ? solverRevenue - solverGasQuote[1]
      : 0n;

    const targetPairAfterExecution = await usdc.balanceOf(venue.targetPair);
    const sourcePoolAfterExecution = await usdc.balanceOf(venue.sourcePool);
    const strictStatus = aggregateNetAfterGas >= V14_REQUIRED_TREASURY_USDC
      && solverNetAfterGas > 0n
      ? "HISTORICAL_EDGE_PASS"
      : "HISTORICAL_EXECUTION_BUT_NET_GATE_FAILED";

    writeReport({
      scenario: "synergy_v15_1_historical_polygon_fork",
      evidenceStatus: strictStatus,
      chainId: 137,
      forkBlock: HISTORICAL_BLOCK - 1,
      historicalVictim: {
        transactionHash: HISTORICAL_TX_HASH,
        originalBlockNumber: HISTORICAL_BLOCK,
        originalTransactionIndex: upstreamReceipt.index,
        originalSender: upstreamTx.from,
        originalTarget: upstreamTx.to,
        originalCalldataHash: ethers.keccak256(upstreamTx.data),
        originalValue: upstreamTx.value.toString(),
        replayTransactionHash: victimReceipt.hash,
        replayBlockNumber: victimReceipt.blockNumber,
        replayTransactionIndex: txIndex(victimReceipt),
        backrunTransactionHash: backrunReceipt.hash,
        backrunTransactionIndex: txIndex(backrunReceipt),
        sameBlock: victimReceipt.blockNumber === backrunReceipt.blockNumber,
        victimBeforeBackrun: txIndex(victimReceipt) < txIndex(backrunReceipt)
      },
      venues: {
        uniswapV3Pool: venue.sourcePool,
        uniswapV3Fee: venue.fee,
        quickswapV2Pair: venue.targetPair,
        uniswapV3Router: UNI_V3_ROUTER,
        quickswapV2Router: QS_V2_ROUTER,
        distinctDexFamilies: true
      },
      auction: {
        epoch: Number(epoch),
        winningSolver: winning[0],
        treasuryShareBps: Number(winning[2]),
        refundableBondWei: E("0.05").toString(),
        bondCountedAsRevenue: false,
        solutionConsumed: true,
        solutionHash,
        venuesHash
      },
      rawAccounting: {
        principalUsdcRaw: candidate.amountIn.toString(),
        grossOutputUsdcRaw: (candidate.amountIn + grossProfit).toString(),
        grossProfitUsdcRaw: grossProfit.toString(),
        treasuryRevenueUsdcRaw: treasuryRevenue.toString(),
        solverRevenueUsdcRaw: solverRevenue.toString(),
        operationalGasUsdcRaw: operationalGasUsdc.toString(),
        aggregateNetAfterGasUsdcRaw: aggregateNetAfterGas.toString(),
        solverGasUsdcRaw: solverGasQuote[1].toString(),
        solverNetAfterGasUsdcRaw: solverNetAfterGas.toString(),
        realizedEdgePpm: Number(edgePpm),
        v14RequiredTreasuryUsdcRaw: V14_REQUIRED_TREASURY_USDC.toString()
      },
      fixtureFunding: {
        source: FIXTURE_USDC_DONOR,
        amountUsdcRaw: solverFunding.toString(),
        countedAsRevenue: false,
        donorBalanceBeforeRaw: donorBalanceBefore.toString(),
        donorBalanceAfterRaw: donorBalanceAfterFunding.toString(),
        selectedExecutionPoolUntouchedDuringFunding: true
      },
      invariants: {
        usdcTotalSupplyBefore: totalSupplyBefore.toString(),
        usdcTotalSupplyAfter: (await usdc.totalSupply()).toString(),
        engineSettlementBalanceAfter: (await usdc.balanceOf(await engine.getAddress())).toString(),
        targetPairUsdcBeforeExecution: targetPairBeforeExecution.toString(),
        targetPairUsdcAfterExecution: targetPairAfterExecution.toString(),
        sourcePoolUsdcBeforeExecution: sourcePoolBeforeExecution.toString(),
        sourcePoolUsdcAfterExecution: sourcePoolAfterExecution.toString(),
        syntheticMintBurnInterfaceUsed: false,
        simulatedRfqRevenueCounted: false,
        solverBondCountedAsRevenue: false
      }
    });
  });
});
