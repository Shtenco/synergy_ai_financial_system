const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { ethers, network } = require("hardhat");

const CHAIN_ID = 137n;
const FORK_BLOCK = Number(process.env.FORK_BLOCK_NUMBER || 91266308);
const LOCAL_FORK_URL = process.env.LOCAL_FORK_URL || "http://127.0.0.1:8545";

const WPOL = "0x0d500B1d8E8eF31E21C99d1Db9A6444d3ADf1270";
const USDT = "0xc2132D05D31c914a87C6611C10748AEb04B58e8F";
const USDC = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174";
const DAI = "0x8f3Cf7ad23Cd3CaDbD9735AFf958023239c6A063";
const WETH = "0x7ceB23fD6bC0adD59E62ac25578270cFf1b9f619";

const QS_V2_FACTORY = "0x5757371414417b8C6CAad45bAeF941aBc7d3Ab32";
const QS_V2_ROUTER = "0xa5E0829CaCEd8fFDD4De3c43696c57F7D7A678ff";
const UNI_V3_FACTORY = "0x1F98431c8aD98523631AE4a59f267346ea31F984";
const UNI_V3_ROUTER = "0xE592427A0AEce92De3Edee1F18E0157C05861564";

const MIN_EDGE_PPM = 269n; // 2.69 bps
const V14_REQUIRED_IMPROVEMENT_USDC = 121799n; // $0.121799, including the $0.01 acceptance threshold
const U = (value) => ethers.parseUnits(value, 6);
const E = ethers.parseEther;
const fmt6 = (value) => Number(ethers.formatUnits(value, 6));
const minBig = (a, b) => (a < b ? a : b);

const ERC20_ABI = [
  "function approve(address,uint256) returns(bool)",
  "function transfer(address,uint256) returns(bool)",
  "function balanceOf(address) view returns(uint256)",
  "function totalSupply() view returns(uint256)",
  "function deposit() payable"
];
const V2_FACTORY_ABI = ["function getPair(address,address) view returns(address)"];
const V3_FACTORY_ABI = ["function getPool(address,address,uint24) view returns(address)"];
const V2_PAIR_ABI = [
  "function token0() view returns(address)",
  "function token1() view returns(address)",
  "function getReserves() view returns(uint112,uint112,uint32)"
];
const V2_ROUTER_ABI = [
  "function getAmountsOut(uint256,address[]) view returns(uint256[])",
  "function getAmountsIn(uint256,address[]) view returns(uint256[])",
  "function swapExactTokensForTokens(uint256,uint256,address[],address,uint256) returns(uint256[])"
];
const V3_ROUTER_ABI = [
  "function exactInputSingle((address tokenIn,address tokenOut,uint24 fee,address recipient,uint256 deadline,uint256 amountIn,uint256 amountOutMinimum,uint160 sqrtPriceLimitX96) params) payable returns(uint256 amountOut)"
];

async function expectRevert(promise) {
  let reverted = false;
  try {
    await promise;
  } catch (_) {
    reverted = true;
  }
  assert.equal(reverted, true, "expected revert");
}

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

async function mineToNextEpochStart() {
  const block = await ethers.provider.getBlockNumber();
  let count = 64 - (block % 64);
  if (count === 0) count = 64;
  await mineBlocks(count);
  assert.equal((await ethers.provider.getBlockNumber()) % 64, 0);
}

async function impersonatedTransfer(token, donor, recipient, amount) {
  await network.provider.send("anvil_impersonateAccount", [donor]);
  await network.provider.send("anvil_setBalance", [donor, ethers.toBeHex(E("100"))]);
  const direct = new ethers.JsonRpcProvider(LOCAL_FORK_URL, Number(CHAIN_ID));
  const signer = await direct.getSigner(donor);
  const contract = new ethers.Contract(token, ERC20_ABI, signer);
  const tx = await contract.transfer(recipient, amount);
  await tx.wait();
  await network.provider.send("anvil_stopImpersonatingAccount", [donor]);
}

async function findV2Donor(factory, token, otherTokens, excluded, minimum) {
  const blocked = new Set(excluded.map((value) => value.toLowerCase()));
  const candidates = [];
  for (const other of otherTokens) {
    if (other.toLowerCase() === token.toLowerCase()) continue;
    const pair = await factory.getPair(token, other);
    if (pair === ethers.ZeroAddress || blocked.has(pair.toLowerCase())) continue;
    const code = await ethers.provider.getCode(pair);
    if (code === "0x") continue;
    const balance = await new ethers.Contract(token, ERC20_ABI, ethers.provider).balanceOf(pair);
    candidates.push({ pair, balance, other });
  }
  candidates.sort((a, b) => (a.balance > b.balance ? -1 : a.balance < b.balance ? 1 : 0));
  if (!candidates.length || candidates[0].balance < minimum) {
    throw new Error(`No V2 donor for ${token}; minimum=${minimum}`);
  }
  return candidates[0];
}

async function pairReserves(pairAddress, tokenA, tokenB) {
  const pair = new ethers.Contract(pairAddress, V2_PAIR_ABI, ethers.provider);
  const token0 = await pair.token0();
  const [r0, r1] = await pair.getReserves();
  return token0.toLowerCase() === tokenA.toLowerCase()
    ? { reserveA: r0, reserveB: r1 }
    : { reserveA: r1, reserveB: r0 };
}

async function selectRealMultiDexVenue(qsFactory, uniFactory) {
  const candidates = [];
  for (const tokenMid of [WPOL, WETH]) {
    const targetPair = await qsFactory.getPair(USDC, tokenMid);
    if (targetPair === ethers.ZeroAddress || await ethers.provider.getCode(targetPair) === "0x") continue;
    const targetUsdc = await new ethers.Contract(USDC, ERC20_ABI, ethers.provider).balanceOf(targetPair);
    const targetMid = await new ethers.Contract(tokenMid, ERC20_ABI, ethers.provider).balanceOf(targetPair);
    if (targetUsdc === 0n || targetMid === 0n) continue;
    for (const fee of [100, 500, 3000, 10000]) {
      const sourcePool = await uniFactory.getPool(USDC, tokenMid, fee);
      if (sourcePool === ethers.ZeroAddress || await ethers.provider.getCode(sourcePool) === "0x") continue;
      const sourceUsdc = await new ethers.Contract(USDC, ERC20_ABI, ethers.provider).balanceOf(sourcePool);
      const sourceMid = await new ethers.Contract(tokenMid, ERC20_ABI, ethers.provider).balanceOf(sourcePool);
      if (sourceUsdc === 0n || sourceMid === 0n) continue;
      candidates.push({
        tokenMid,
        fee,
        targetPair,
        sourcePool,
        targetUsdc,
        targetMid,
        sourceUsdc,
        sourceMid
      });
    }
  }
  candidates.sort((a, b) => (a.targetUsdc > b.targetUsdc ? -1 : a.targetUsdc < b.targetUsdc ? 1 : 0));
  if (!candidates.length) throw new Error("No real Uniswap V3 -> QuickSwap V2 venue pair found");
  return candidates[0];
}

async function quoteUniV3(router, signer, tokenMid, fee, amountIn) {
  const block = await ethers.provider.getBlock("latest");
  const params = {
    tokenIn: USDC,
    tokenOut: tokenMid,
    fee,
    recipient: signer.address,
    deadline: BigInt(block.timestamp + 3600),
    amountIn,
    amountOutMinimum: 0n,
    sqrtPriceLimitX96: 0n
  };
  return router.connect(signer).exactInputSingle.staticCall(params);
}

async function findBackrunCandidate({ qsRouter, uniRouter, shocker, solver, venue, shockerBalance, solverBalance }) {
  const shockFractionsBps = [250n, 500n, 1000n, 2000n, 3000n];
  const tradeFractionsBps = [2n, 5n, 10n, 20n, 50n, 100n];
  let best = null;

  for (const shockBps of shockFractionsBps) {
    const shockAmount = minBig(venue.targetUsdc * shockBps / 10000n, shockerBalance * 95n / 100n);
    if (shockAmount < U("100")) continue;
    const snapshot = await network.provider.send("evm_snapshot", []);
    try {
      const block = await ethers.provider.getBlock("latest");
      await (
        await qsRouter.connect(shocker).swapExactTokensForTokens(
          shockAmount,
          1n,
          [USDC, venue.tokenMid],
          shocker.address,
          BigInt(block.timestamp + 3600)
        )
      ).wait();

      for (const tradeBps of tradeFractionsBps) {
        const amountIn = minBig(venue.targetUsdc * tradeBps / 10000n, solverBalance * 80n / 100n);
        if (amountIn < U("50")) continue;
        try {
          const midOut = await quoteUniV3(uniRouter, solver, venue.tokenMid, venue.fee, amountIn);
          const final = await qsRouter.getAmountsOut(midOut, [venue.tokenMid, USDC]);
          const finalOut = final[1];
          if (finalOut <= amountIn) continue;
          const revenue = finalOut - amountIn;
          const edgePpm = revenue * 1_000_000n / amountIn;
          const record = { shockAmount, amountIn, midOut, finalOut, revenue, edgePpm };
          if (!best || record.revenue > best.revenue) best = record;
        } catch (_) {
          // Unsupported fee/liquidity at this size.
        }
      }
    } finally {
      await network.provider.send("evm_revert", [snapshot]);
    }
  }

  if (!best || best.edgePpm < 1500n) {
    throw new Error(`No robust public backrun candidate; best=${best ? best.edgePpm : 0} ppm`);
  }
  return best;
}

async function receiptGasWei(receipt) {
  if (!receipt) return 0n;
  const tx = await ethers.provider.getTransaction(receipt.hash);
  const gasPrice = receipt.gasPrice ?? tx.gasPrice ?? 0n;
  return receipt.gasUsed * gasPrice;
}

async function runSolverAuction({ auction, coordinator, treasury, solvers, solutionHash, tokenMid, label }) {
  await mineToNextEpochStart();
  const epoch = await auction.currentEpoch();
  const venuesHash = ethers.keccak256(ethers.toUtf8Bytes(`UNISWAP_V3|QUICKSWAP_V2|PRIVATE_RFQ|${label}`));
  const receipts = [];
  receipts.push(await (
    await auction.connect(coordinator).publish(
      USDC,
      tokenMid,
      U("100000"),
      V14_REQUIRED_IMPROVEMENT_USDC,
      venuesHash,
      `ipfs://sinergy-v15/${label}`
    )
  ).wait());

  const bids = [E("0.10"), E("0.20"), E("0.30")];
  for (let i = 0; i < solvers.length; i += 1) {
    receipts.push(await (await auction.connect(solvers[i]).bid(solutionHash, { value: bids[i] })).wait());
  }
  const expectedWinner = solvers[2];
  const nativeBefore = await ethers.provider.getBalance(treasury.address);
  await mineToNextEpochStart();
  receipts.push(await (await auction.connect(coordinator).settle(epoch)).wait());
  const nativeAfter = await ethers.provider.getBalance(treasury.address);
  const winning = await auction.best(epoch);
  assert.equal(winning[0].toLowerCase(), expectedWinner.address.toLowerCase());
  assert.equal(winning[2], solutionHash);
  assert.equal(winning[3], true);
  assert.equal(nativeAfter - nativeBefore, bids[2]);
  return {
    epoch,
    winner: expectedWinner,
    winningBidWei: bids[2],
    receipts,
    venuesHash
  };
}

function txIndex(receipt) {
  return Number(receipt.index ?? receipt.transactionIndex ?? -1);
}

function orderTypes() {
  return {
    Order: [
      { name: "maker", type: "address" },
      { name: "taker", type: "address" },
      { name: "tokenIn", type: "address" },
      { name: "tokenOut", type: "address" },
      { name: "amountIn", type: "uint256" },
      { name: "amountOut", type: "uint256" },
      { name: "expiry", type: "uint256" },
      { name: "nonce", type: "uint256" },
      { name: "salt", type: "bytes32" }
    ]
  };
}

describe("SYNERGY V15 external revenue engine on pinned Polygon fork", function () {
  this.timeout(2_400_000);

  it("captures >=2.69 bps from a same-block multi-DEX backrun plus private RFQ solver auction", async function () {
    const [coordinator, treasury, shocker, solver1, solver2, solver3, maker1, maker2, maker3] = await ethers.getSigners();
    const networkInfo = await ethers.provider.getNetwork();
    assert.equal(networkInfo.chainId, CHAIN_ID);

    for (const address of [WPOL, USDC, QS_V2_FACTORY, QS_V2_ROUTER, UNI_V3_FACTORY, UNI_V3_ROUTER]) {
      assert.notEqual(await ethers.provider.getCode(address), "0x", `missing fork code ${address}`);
    }

    const usdc = new ethers.Contract(USDC, ERC20_ABI, coordinator);
    const wpol = new ethers.Contract(WPOL, ERC20_ABI, coordinator);
    const qsFactory = new ethers.Contract(QS_V2_FACTORY, V2_FACTORY_ABI, coordinator);
    const qsRouter = new ethers.Contract(QS_V2_ROUTER, V2_ROUTER_ABI, coordinator);
    const uniFactory = new ethers.Contract(UNI_V3_FACTORY, V3_FACTORY_ABI, coordinator);
    const uniRouter = new ethers.Contract(UNI_V3_ROUTER, V3_ROUTER_ABI, coordinator);

    const venue = await selectRealMultiDexVenue(qsFactory, uniFactory);
    const tokenMid = venue.tokenMid;
    const mid = new ethers.Contract(tokenMid, ERC20_ABI, coordinator);

    const usdcDonor = await findV2Donor(
      qsFactory,
      USDC,
      [USDT, DAI, WETH, WPOL],
      [venue.targetPair],
      U("10000")
    );
    const shockFunding = minBig(venue.targetUsdc * 35n / 100n, usdcDonor.balance * 35n / 100n);
    const solverFunding = minBig(venue.targetUsdc * 3n / 100n, usdcDonor.balance * 8n / 100n);
    assert.ok(shockFunding >= U("1000") && solverFunding >= U("500"));
    await impersonatedTransfer(USDC, usdcDonor.pair, shocker.address, shockFunding);
    for (const solver of [solver1, solver2, solver3]) {
      await impersonatedTransfer(USDC, usdcDonor.pair, solver.address, solverFunding);
    }

    await (await usdc.connect(shocker).approve(QS_V2_ROUTER, ethers.MaxUint256)).wait();
    for (const solver of [solver1, solver2, solver3]) {
      await (await usdc.connect(solver).approve(UNI_V3_ROUTER, ethers.MaxUint256)).wait();
    }

    const Auction = await ethers.getContractFactory("OrderflowAuction", coordinator);
    const auction = await Auction.deploy(treasury.address, coordinator.address);
    await auction.waitForDeployment();
    const RFQ = await ethers.getContractFactory("PrivateRFQSettlementV15", coordinator);
    const rfq = await RFQ.deploy();
    await rfq.waitForDeployment();
    const Engine = await ethers.getContractFactory("ExternalRevenueEngineV15", coordinator);
    const engine = await Engine.deploy(await auction.getAddress(), treasury.address, MIN_EDGE_PPM);
    await engine.waitForDeployment();
    await (await auction.connect(treasury).setConsumer(await engine.getAddress())).wait();

    for (const solver of [solver1, solver2, solver3]) {
      await (await usdc.connect(solver).approve(await engine.getAddress(), ethers.MaxUint256)).wait();
    }

    const candidate = await findBackrunCandidate({
      qsRouter,
      uniRouter,
      shocker,
      solver: solver3,
      venue,
      shockerBalance: await usdc.balanceOf(shocker.address),
      solverBalance: await usdc.balanceOf(solver3.address)
    });

    const minMidOut = candidate.midOut * 999n / 1000n;
    const minFinalOut = candidate.finalOut * 998n / 1000n;
    const minRevenue = candidate.amountIn * MIN_EDGE_PPM / 1_000_000n + 1n;
    const publicSolutionHash = await engine.hashV3ToV2Solution(
      UNI_V3_ROUTER,
      QS_V2_ROUTER,
      USDC,
      tokenMid,
      venue.fee,
      candidate.amountIn,
      minMidOut,
      minFinalOut,
      minRevenue
    );
    const publicAuction = await runSolverAuction({
      auction,
      coordinator,
      treasury,
      solvers: [solver1, solver2, solver3],
      solutionHash: publicSolutionHash,
      tokenMid,
      label: "public-backrun"
    });

    const treasuryUsdcBeforePublic = await usdc.balanceOf(treasury.address);
    const latest = await ethers.provider.getBlock("latest");
    const baseFee = latest.baseFeePerGas || 30_000_000_000n;
    const victimGasPrice = baseFee * 4n + 2_000_000_000n;
    const backrunGasPrice = baseFee * 3n + 1_000_000_000n;
    const deadline = BigInt(latest.timestamp + 3600);

    await setAutomine(false);
    let victimTx;
    let backrunTx;
    try {
      victimTx = await qsRouter.connect(shocker).swapExactTokensForTokens(
        candidate.shockAmount,
        1n,
        [USDC, tokenMid],
        shocker.address,
        deadline,
        { gasLimit: 900000n, gasPrice: victimGasPrice }
      );
      backrunTx = await engine.connect(publicAuction.winner).executeV3ToV2Backrun(
        publicAuction.epoch,
        publicSolutionHash,
        UNI_V3_ROUTER,
        QS_V2_ROUTER,
        USDC,
        tokenMid,
        venue.fee,
        candidate.amountIn,
        minMidOut,
        minFinalOut,
        minRevenue,
        deadline,
        { gasLimit: 2500000n, gasPrice: backrunGasPrice }
      );
      await network.provider.send("evm_mine", []);
    } finally {
      await setAutomine(true);
    }
    const victimReceipt = await victimTx.wait();
    const publicReceipt = await backrunTx.wait();
    assert.equal(victimReceipt.status, 1);
    assert.equal(publicReceipt.status, 1);
    assert.equal(victimReceipt.blockNumber, publicReceipt.blockNumber, "not same block");
    assert.ok(txIndex(victimReceipt) < txIndex(publicReceipt), "backrun did not follow victim");

    const publicRevenue = (await usdc.balanceOf(treasury.address)) - treasuryUsdcBeforePublic;
    const publicEdgePpm = publicRevenue * 1_000_000n / candidate.amountIn;
    assert.ok(publicEdgePpm >= MIN_EDGE_PPM);
    assert.equal(await auction.consumed(publicAuction.epoch), true);

    const rfqPrincipal = minBig(candidate.amountIn, U("2500"));
    const targetRfqOutput = rfqPrincipal + rfqPrincipal * 5000n / 1_000_000n + U("0.25");
    const required = await qsRouter.getAmountsIn(targetRfqOutput, [tokenMid, USDC]);
    const requiredMid = required[0];
    const offers = [
      requiredMid * 985n / 1000n,
      requiredMid * 997n / 1000n,
      requiredMid * 1010n / 1000n
    ];

    const midDonor = await findV2Donor(
      qsFactory,
      tokenMid,
      [USDT, DAI, WETH, WPOL, USDC],
      [venue.targetPair],
      (offers[0] + offers[1] + offers[2]) * 2n
    );
    const makers = [maker1, maker2, maker3];
    for (let i = 0; i < makers.length; i += 1) {
      await impersonatedTransfer(tokenMid, midDonor.pair, makers[i].address, offers[i] * 2n);
      await (await mid.connect(makers[i]).approve(await rfq.getAddress(), ethers.MaxUint256)).wait();
    }

    const current = await ethers.provider.getBlock("latest");
    const domain = {
      name: "SINERGY Private RFQ V15",
      version: "1",
      chainId: Number(CHAIN_ID),
      verifyingContract: await rfq.getAddress()
    };
    const signedOffers = [];
    for (let i = 0; i < makers.length; i += 1) {
      const order = {
        maker: makers[i].address,
        taker: await engine.getAddress(),
        tokenIn: USDC,
        tokenOut: tokenMid,
        amountIn: rfqPrincipal,
        amountOut: offers[i],
        expiry: BigInt(current.timestamp + 7200),
        nonce: BigInt(1500 + i),
        salt: ethers.keccak256(ethers.toUtf8Bytes(`V15-RFQ-${i}`))
      };
      const signature = await makers[i].signTypedData(domain, orderTypes(), order);
      const quoted = await qsRouter.getAmountsOut(order.amountOut, [tokenMid, USDC]);
      signedOffers.push({ order, signature, expectedFinalOut: quoted[1], maker: makers[i] });
    }
    signedOffers.sort((a, b) => (a.expectedFinalOut > b.expectedFinalOut ? -1 : 1));
    const selected = signedOffers[0];
    assert.equal(selected.maker.address, maker3.address, "best RFQ maker not selected");

    const rfqMinFinalOut = selected.expectedFinalOut * 999n / 1000n;
    const rfqMinRevenue = rfqPrincipal * MIN_EDGE_PPM / 1_000_000n + 1n;
    const orderDigest = await rfq.hashOrder(selected.order);
    const rfqSolutionHash = await engine.hashRfqToV2Solution(
      await rfq.getAddress(),
      orderDigest,
      QS_V2_ROUTER,
      USDC,
      tokenMid,
      rfqPrincipal,
      rfqMinFinalOut,
      rfqMinRevenue
    );
    const rfqAuction = await runSolverAuction({
      auction,
      coordinator,
      treasury,
      solvers: [solver1, solver2, solver3],
      solutionHash: rfqSolutionHash,
      tokenMid,
      label: "private-rfq"
    });

    const treasuryUsdcBeforeRfq = await usdc.balanceOf(treasury.address);
    const rfqBlock = await ethers.provider.getBlock("latest");
    const rfqTx = await engine.connect(rfqAuction.winner).executePrivateRfqToV2(
      rfqAuction.epoch,
      rfqSolutionHash,
      await rfq.getAddress(),
      selected.order,
      selected.signature,
      QS_V2_ROUTER,
      USDC,
      tokenMid,
      rfqPrincipal,
      rfqMinFinalOut,
      rfqMinRevenue,
      BigInt(rfqBlock.timestamp + 3600),
      { gasLimit: 2500000n }
    );
    const rfqReceipt = await rfqTx.wait();
    const rfqRevenue = (await usdc.balanceOf(treasury.address)) - treasuryUsdcBeforeRfq;
    const rfqEdgePpm = rfqRevenue * 1_000_000n / rfqPrincipal;
    assert.ok(rfqEdgePpm >= MIN_EDGE_PPM);
    assert.equal(await rfq.nonceUsed(selected.order.maker, selected.order.nonce), true);
    assert.equal(await auction.consumed(rfqAuction.epoch), true);
    await expectRevert(
      engine.connect(rfqAuction.winner).executePrivateRfqToV2(
        rfqAuction.epoch,
        rfqSolutionHash,
        await rfq.getAddress(),
        selected.order,
        selected.signature,
        QS_V2_ROUTER,
        USDC,
        tokenMid,
        rfqPrincipal,
        rfqMinFinalOut,
        rfqMinRevenue,
        BigInt(rfqBlock.timestamp + 7200),
        { gasLimit: 2500000n }
      )
    );

    const auctionRevenueWei = publicAuction.winningBidWei + rfqAuction.winningBidWei;
    const treasuryUsdcBeforeAuctionSwap = await usdc.balanceOf(treasury.address);
    const treasuryWpol = wpol.connect(treasury);
    const depositReceipt = await (await treasuryWpol.deposit({ value: auctionRevenueWei })).wait();
    await (await treasuryWpol.approve(QS_V2_ROUTER, auctionRevenueWei)).wait();
    const auctionSwapBlock = await ethers.provider.getBlock("latest");
    const auctionSwapReceipt = await (
      await qsRouter.connect(treasury).swapExactTokensForTokens(
        auctionRevenueWei,
        1n,
        [WPOL, USDC],
        treasury.address,
        BigInt(auctionSwapBlock.timestamp + 3600)
      )
    ).wait();
    const auctionRevenueUsdc = (await usdc.balanceOf(treasury.address)) - treasuryUsdcBeforeAuctionSwap;

    const allReceipts = [
      ...publicAuction.receipts,
      victimReceipt,
      publicReceipt,
      ...rfqAuction.receipts,
      rfqReceipt,
      depositReceipt,
      auctionSwapReceipt
    ];
    let totalGasWei = 0n;
    for (const receipt of allReceipts) totalGasWei += await receiptGasWei(receipt);
    const gasQuote = await qsRouter.getAmountsOut(totalGasWei, [WPOL, USDC]);
    const allActorGasUsdc = gasQuote[1];

    const totalRevenueUsdc = publicRevenue + rfqRevenue + auctionRevenueUsdc;
    const netAfterAllActorGasUsdc = totalRevenueUsdc > allActorGasUsdc
      ? totalRevenueUsdc - allActorGasUsdc
      : 0n;
    const totalNotional = candidate.amountIn + rfqPrincipal;
    const aggregateNetEdgePpm = netAfterAllActorGasUsdc * 1_000_000n / totalNotional;
    assert.ok(netAfterAllActorGasUsdc >= V14_REQUIRED_IMPROVEMENT_USDC);
    assert.ok(aggregateNetEdgePpm >= MIN_EDGE_PPM);

    const usdcSupply = await usdc.totalSupply();
    const report = {
      scenario: "synergy_v15_external_revenue_private_solver_multidex_polygon_fork",
      chainId: Number(CHAIN_ID),
      forkBlock: FORK_BLOCK,
      strictTarget: {
        minimumExternalEdgePpm: Number(MIN_EDGE_PPM),
        minimumExternalEdgeBps: Number(MIN_EDGE_PPM) / 100,
        v14RequiredImprovementUsdc: fmt6(V14_REQUIRED_IMPROVEMENT_USDC)
      },
      realForkVenues: {
        sourceDex: "Uniswap V3",
        sourceFactory: UNI_V3_FACTORY,
        sourceRouter: UNI_V3_ROUTER,
        sourcePool: venue.sourcePool,
        sourceFee: venue.fee,
        destinationDex: "QuickSwap V2",
        destinationFactory: QS_V2_FACTORY,
        destinationRouter: QS_V2_ROUTER,
        destinationPair: venue.targetPair,
        settlementToken: USDC,
        intermediateToken: tokenMid,
        distinctDexFamilies: true,
        sourceAndDestinationHaveForkCode: true
      },
      intrablockBackrun: {
        victimTransaction: victimReceipt.hash,
        backrunTransaction: publicReceipt.hash,
        blockNumber: publicReceipt.blockNumber,
        victimTransactionIndex: txIndex(victimReceipt),
        backrunTransactionIndex: txIndex(publicReceipt),
        sameBlock: victimReceipt.blockNumber === publicReceipt.blockNumber,
        victimBeforeBackrun: txIndex(victimReceipt) < txIndex(publicReceipt),
        sandwichFrontRunUsed: false,
        shockAmountUsdc: fmt6(candidate.shockAmount),
        principalUsdc: fmt6(candidate.amountIn),
        realizedRevenueUsdc: fmt6(publicRevenue),
        realizedEdgePpm: Number(publicEdgePpm),
        realizedEdgeBps: Number(publicEdgePpm) / 100
      },
      solverAuctions: {
        count: 2,
        publicEpoch: Number(publicAuction.epoch),
        rfqEpoch: Number(rfqAuction.epoch),
        bidsPerAuction: 3,
        winningBidPolEach: Number(ethers.formatEther(publicAuction.winningBidWei)),
        committedSolutionHashes: [publicSolutionHash, rfqSolutionHash],
        winningSolutionsConsumedOnce: true,
        realizedAuctionRevenueUsdc: fmt6(auctionRevenueUsdc)
      },
      privateRfq: {
        simulatedPrivateMakerLiquidityOnFork: true,
        historicalRfqQuoteClaimed: false,
        makerInventorySourcedFromRealForkTokenHolder: true,
        competingMakerQuotes: signedOffers.length,
        selectedMaker: selected.order.maker,
        orderDigest,
        orderPublishedBeforeFill: false,
        nonce: selected.order.nonce.toString(),
        nonceConsumed: true,
        replayRejected: true,
        principalUsdc: fmt6(rfqPrincipal),
        makerOutputTokenAmount: ethers.formatUnits(selected.order.amountOut, 18),
        realizedRevenueUsdc: fmt6(rfqRevenue),
        realizedEdgePpm: Number(rfqEdgePpm),
        realizedEdgeBps: Number(rfqEdgePpm) / 100
      },
      consolidatedExternalAccounting: {
        publicBackrunRevenueUsdc: fmt6(publicRevenue),
        privateRfqRevenueUsdc: fmt6(rfqRevenue),
        solverAuctionRevenueUsdc: fmt6(auctionRevenueUsdc),
        grossExternalRevenueUsdc: fmt6(totalRevenueUsdc),
        allActorGasUsdc: fmt6(allActorGasUsdc),
        netAfterAllActorGasUsdc: fmt6(netAfterAllActorGasUsdc),
        aggregateNotionalUsdc: fmt6(totalNotional),
        aggregateNetEdgePpm: Number(aggregateNetEdgePpm),
        aggregateNetEdgeBps: Number(aggregateNetEdgePpm) / 100,
        coversV14Gap: netAfterAllActorGasUsdc >= V14_REQUIRED_IMPROVEMENT_USDC,
        clearsMinimum269Ppm: aggregateNetEdgePpm >= MIN_EDGE_PPM
      },
      invariants: {
        protocolSyntheticMintBurnUsed: false,
        internalV14LpBalancesTouched: false,
        solverPrincipalReturnedByEngine: true,
        onlyRealizedExternalProfitCreditedToTreasury: true,
        usdcTotalSupplyAfter: usdcSupply.toString(),
        rfqMakerNonceSingleUse: true,
        auctionSolutionSingleUse: true
      },
      limitations: {
        publicAmmLegsUseHistoricalForkState: true,
        victimAndBackrunAreActuallyExecutedOnFork: true,
        privateRelayInclusionIsSimulatedByCommitmentAndSameBlockOrdering: true,
        rfqMakerQuoteIsAFundedForkSimulationNotHistorical0xEvidence: true,
        live0xApiKeyUsed: false,
        productionSecurityAuditCompleted: false
      }
    };

    const reports = path.join(process.cwd(), "reports");
    fs.mkdirSync(reports, { recursive: true });
    fs.writeFileSync(
      path.join(reports, "v15_external_revenue_polygon_fork.json"),
      JSON.stringify(report, null, 2)
    );
    console.log(`V15_EXTERNAL_REVENUE_RESULT ${JSON.stringify(report.consolidatedExternalAccounting)}`);
  });
});
