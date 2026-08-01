const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { ethers, network } = require("hardhat");

const WPOL = "0x0d500B1d8E8eF31E21C99d1Db9A6444d3ADf1270";
const USDT = "0xc2132D05D31c914a87C6611C10748AEb04B58e8F";
const USDC = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174";
const DAI = "0x8f3Cf7ad23Cd3CaDbD9735AFf958023239c6A063";
const WETH = "0x7ceB23fD6bC0adD59E62ac25578270cFf1b9f619";

const QUICKSWAP_FACTORY = "0x5757371414417b8C6CAad45bAeF941aBc7d3Ab32";
const QUICKSWAP_ROUTER = "0xa5E0829CaCEd8fFDD4De3c43696c57F7D7A678ff";
const SUSHISWAP_FACTORY = "0xc35DADB65012eC5796536bD9864eD8773aBc74C4";
const SUSHISWAP_ROUTER = "0x1b02da8cb0d097eb8d57a175b88c7d8b47997506";

const V14_NOTIONAL_USDT = ethers.parseUnits("453.602562", 6);
const V14_REQUIRED_EDGE_USDT = ethers.parseUnits("0.121799", 6);
const REQUIRED_EDGE_BPS = 2.68515;
const U6 = (v) => ethers.parseUnits(v, 6);
const E = ethers.parseEther;
const fmt6 = (v) => Number(ethers.formatUnits(v, 6));

const ERC20_ABI = [
  "function approve(address,uint256) returns(bool)",
  "function transfer(address,uint256) returns(bool)",
  "function balanceOf(address) view returns(uint256)",
  "function deposit() payable"
];
const FACTORY_ABI = ["function getPair(address,address) view returns(address)"];
const PAIR_ABI = [
  "function token0() view returns(address)",
  "function token1() view returns(address)",
  "function getReserves() view returns(uint112,uint112,uint32)"
];
const ROUTER_ABI = [
  "function getAmountsOut(uint256,address[]) view returns(uint256[])",
  "function swapExactTokensForTokens(uint256,uint256,address[],address,uint256) returns(uint256[])"
];

function amountOut(amountIn, reserveIn, reserveOut) {
  const amountInWithFee = amountIn * 997n;
  return (amountInWithFee * reserveOut) / (reserveIn * 1000n + amountInWithFee);
}

async function pairState(pairAddress, stable) {
  const pair = new ethers.Contract(pairAddress, PAIR_ABI, ethers.provider);
  const token0 = (await pair.token0()).toLowerCase();
  const [r0, r1] = await pair.getReserves();
  return token0 === stable.toLowerCase()
    ? { stable: r0, wpol: r1 }
    : { stable: r1, wpol: r0 };
}

async function impersonatedTransfer(token, donor, recipient, amount) {
  await network.provider.send("anvil_impersonateAccount", [donor]);
  await network.provider.send("anvil_setBalance", [donor, ethers.toBeHex(E("100"))]);
  const direct = new ethers.JsonRpcProvider(process.env.LOCAL_FORK_URL || "http://127.0.0.1:8545");
  const signer = await direct.getSigner(donor);
  const contract = new ethers.Contract(token, ERC20_ABI, signer);
  await (await contract.transfer(recipient, amount)).wait();
  await network.provider.send("anvil_stopImpersonatingAccount", [donor]);
}

async function findStableDonor(factory, stable, excluded, minimum) {
  const blocked = new Set(excluded.map((x) => x.toLowerCase()));
  const candidates = [];
  for (const other of [USDC, DAI, WETH, WPOL]) {
    if (other.toLowerCase() === stable.toLowerCase()) continue;
    const pair = await factory.getPair(stable, other);
    if (pair === ethers.ZeroAddress || blocked.has(pair.toLowerCase())) continue;
    const balance = await new ethers.Contract(stable, ERC20_ABI, ethers.provider).balanceOf(pair);
    candidates.push({ pair, balance });
  }
  candidates.sort((a, b) => (a.balance > b.balance ? -1 : a.balance < b.balance ? 1 : 0));
  assert.ok(candidates.length && candidates[0].balance >= minimum, "no independent stable donor");
  return candidates[0];
}

function optimizeBackrun(sushi, quickAfterVictim, maxInput) {
  let best = null;
  for (let i = 1n; i <= 160n; i++) {
    const input = (maxInput * i) / 160n;
    if (input === 0n) continue;
    const wpolBought = amountOut(input, sushi.stable, sushi.wpol);
    const stableOut = amountOut(wpolBought, quickAfterVictim.wpol, quickAfterVictim.stable);
    const profit = stableOut - input;
    if (!best || profit > best.profit) best = { input, wpolBought, stableOut, profit };
  }
  return best;
}

async function receiptGasStable(receipt, stablePerWpol) {
  const price = receipt.gasPrice ?? receipt.effectiveGasPrice ?? 0n;
  return (receipt.gasUsed * price * stablePerWpol) / E("1");
}

async function mineControlledBundle(transactions) {
  await network.provider.send("evm_setAutomine", [false]);
  const pending = [];
  try {
    for (const send of transactions) pending.push(await send());
    await network.provider.send("evm_mine", []);
  } finally {
    await network.provider.send("evm_setAutomine", [true]);
  }
  return Promise.all(pending.map((tx) => tx.wait()));
}

async function bestRouterQuote(routers, amountIn, route) {
  const quotes = [];
  for (const item of routers) {
    try {
      const amounts = await item.router.getAmountsOut(amountIn, route);
      quotes.push({ ...item, output: amounts[amounts.length - 1] });
    } catch (_) {}
  }
  quotes.sort((a, b) => (a.output > b.output ? -1 : a.output < b.output ? 1 : 0));
  assert.ok(quotes.length, "no public quote");
  return quotes[0];
}

describe("SYNERGY V15 external revenue engine on pinned Polygon fork", function () {
  this.timeout(1_800_000);

  it("covers the V14 closure gap using real intrablock multi-DEX backrun plus signed RFQ and solver auction", async function () {
    const [admin, protocolBackrunner, victim, rfqTaker, rfqMaker, treasury, solver1, solver2, solver3] = await ethers.getSigners();
    for (const address of [WPOL, USDT, QUICKSWAP_FACTORY, QUICKSWAP_ROUTER, SUSHISWAP_FACTORY, SUSHISWAP_ROUTER]) {
      assert.notEqual(await ethers.provider.getCode(address), "0x", `missing fork code ${address}`);
    }

    const quickFactory = new ethers.Contract(QUICKSWAP_FACTORY, FACTORY_ABI, admin);
    const sushiFactory = new ethers.Contract(SUSHISWAP_FACTORY, FACTORY_ABI, admin);
    const quickRouter = new ethers.Contract(QUICKSWAP_ROUTER, ROUTER_ABI, admin);
    const sushiRouter = new ethers.Contract(SUSHISWAP_ROUTER, ROUTER_ABI, admin);
    const stable = new ethers.Contract(USDT, ERC20_ABI, admin);
    const wpol = new ethers.Contract(WPOL, ERC20_ABI, admin);

    const quickPair = await quickFactory.getPair(USDT, WPOL);
    const sushiPair = await sushiFactory.getPair(USDT, WPOL);
    assert.notEqual(quickPair, ethers.ZeroAddress, "missing QuickSwap USDT/WPOL");
    assert.notEqual(sushiPair, ethers.ZeroAddress, "missing SushiSwap USDT/WPOL");
    assert.notEqual(await ethers.provider.getCode(quickPair), "0x");
    assert.notEqual(await ethers.provider.getCode(sushiPair), "0x");

    const quickBefore = await pairState(quickPair, USDT);
    const sushiBefore = await pairState(sushiPair, USDT);
    assert.ok(quickBefore.stable > U6("1000") && sushiBefore.stable > U6("1000"), "insufficient real liquidity");

    const donor = await findStableDonor(quickFactory, USDT, [quickPair, sushiPair], U6("10000"));
    const usableDonor = (donor.balance * 60n) / 100n;
    const victimAmount = quickBefore.stable / 20n < usableDonor / 2n
      ? quickBefore.stable / 20n
      : usableDonor / 2n;
    const maxBackrunInput = sushiBefore.stable / 20n < usableDonor / 4n
      ? sushiBefore.stable / 20n
      : usableDonor / 4n;
    assert.ok(victimAmount >= U6("1000") && maxBackrunInput >= U6("500"), "donor-limited test size too small");
    await impersonatedTransfer(USDT, donor.pair, victim.address, victimAmount);
    await impersonatedTransfer(USDT, donor.pair, protocolBackrunner.address, maxBackrunInput);
    await impersonatedTransfer(USDT, donor.pair, rfqTaker.address, U6("2000"));
    for (const solver of [solver1, solver2, solver3]) {
      await impersonatedTransfer(USDT, donor.pair, solver.address, U6("5"));
    }

    const victimWpol = amountOut(victimAmount, quickBefore.stable, quickBefore.wpol);
    const quickAfterVictim = {
      stable: quickBefore.stable + victimAmount,
      wpol: quickBefore.wpol - victimWpol
    };
    const plan = optimizeBackrun(sushiBefore, quickAfterVictim, maxBackrunInput);
    assert.ok(plan && plan.profit > V14_REQUIRED_EDGE_USDT, "victim shock did not create sufficient backrun");

    await (await stable.connect(victim).approve(QUICKSWAP_ROUTER, victimAmount)).wait();
    await (await stable.connect(protocolBackrunner).approve(SUSHISWAP_ROUTER, plan.input)).wait();
    await (await wpol.connect(protocolBackrunner).approve(QUICKSWAP_ROUTER, plan.wpolBought)).wait();

    const block = await ethers.provider.getBlock("latest");
    const baseFee = block.baseFeePerGas || ethers.parseUnits("30", "gwei");
    const deadline = BigInt(block.timestamp + 3600);
    const backrunBalanceBefore = await stable.balanceOf(protocolBackrunner.address);
    const [victimReceipt, buyReceipt, sellReceipt] = await mineControlledBundle([
      () => quickRouter.connect(victim).swapExactTokensForTokens(
        victimAmount, 1n, [USDT, WPOL], victim.address, deadline,
        { gasPrice: baseFee + ethers.parseUnits("30", "gwei") }
      ),
      () => sushiRouter.connect(protocolBackrunner).swapExactTokensForTokens(
        plan.input, 1n, [USDT, WPOL], protocolBackrunner.address, deadline,
        { gasPrice: baseFee + ethers.parseUnits("20", "gwei") }
      ),
      () => quickRouter.connect(protocolBackrunner).swapExactTokensForTokens(
        plan.wpolBought, 1n, [WPOL, USDT], protocolBackrunner.address, deadline,
        { gasPrice: baseFee + ethers.parseUnits("10", "gwei") }
      )
    ]);
    assert.equal(victimReceipt.blockNumber, buyReceipt.blockNumber);
    assert.equal(buyReceipt.blockNumber, sellReceipt.blockNumber);

    const stablePerWpol = (await quickRouter.getAmountsOut(E("1"), [WPOL, USDT]))[1];
    const backrunBalanceAfter = await stable.balanceOf(protocolBackrunner.address);
    const backrunGross = backrunBalanceAfter - backrunBalanceBefore;
    const backrunGas = await receiptGasStable(buyReceipt, stablePerWpol)
      + await receiptGasStable(sellReceipt, stablePerWpol);
    const backrunNet = backrunGross - backrunGas;
    assert.ok(backrunNet > 0n, "backrun not profitable after gas");

    const Engine = await ethers.getContractFactory("V15ExternalRevenueEngine", admin);
    const engine = await Engine.deploy(USDT, treasury.address, [solver1.address, solver2.address, solver3.address]);
    await engine.waitForDeployment();
    const engineAddress = await engine.getAddress();

    await (await wpol.connect(rfqMaker).deposit({ value: E("20") })).wait();
    const rfqInput = U6("1000");
    const publicBuy = await bestRouterQuote([
      { name: "QuickSwapV2", router: quickRouter, address: QUICKSWAP_ROUTER },
      { name: "SushiSwapV2", router: sushiRouter, address: SUSHISWAP_ROUTER }
    ], rfqInput, [USDT, WPOL]);
    const rfqOutput = (publicBuy.output * 10100n) / 10000n;
    await (await stable.connect(rfqTaker).approve(engineAddress, rfqInput)).wait();
    await (await wpol.connect(rfqMaker).approve(engineAddress, rfqOutput)).wait();
    const rfqBlock = await ethers.provider.getBlock("latest");
    const rfqDeadline = BigInt(rfqBlock.timestamp + 3600);
    const nonce = 15n;
    const quoteHash = await engine.quoteHash(
      rfqMaker.address, rfqTaker.address, USDT, WPOL, rfqInput, rfqOutput, nonce, rfqDeadline
    );
    const signature = await rfqMaker.signMessage(ethers.getBytes(quoteHash));
    const rfqStableBefore = await stable.balanceOf(rfqTaker.address);
    const fillReceipt = await (await engine.connect(rfqTaker).fillSignedQuote(
      rfqMaker.address, USDT, WPOL, rfqInput, rfqOutput, nonce, rfqDeadline, signature
    )).wait();
    const publicSell = await bestRouterQuote([
      { name: "QuickSwapV2", router: quickRouter, address: QUICKSWAP_ROUTER },
      { name: "SushiSwapV2", router: sushiRouter, address: SUSHISWAP_ROUTER }
    ], rfqOutput, [WPOL, USDT]);
    await (await wpol.connect(rfqTaker).approve(publicSell.address, rfqOutput)).wait();
    const sellRfqReceipt = await (await publicSell.router.connect(rfqTaker).swapExactTokensForTokens(
      rfqOutput, 1n, [WPOL, USDT], rfqTaker.address, BigInt(rfqBlock.timestamp + 3600)
    )).wait();
    const rfqStableAfter = await stable.balanceOf(rfqTaker.address);
    const rfqGross = rfqStableAfter - rfqStableBefore;
    const rfqGas = await receiptGasStable(fillReceipt, stablePerWpol)
      + await receiptGasStable(sellRfqReceipt, stablePerWpol);
    const rfqNet = rfqGross - rfqGas;
    assert.ok(rfqNet > 0n, "signed RFQ not profitable after gas");

    const bids = [U6("0.05"), U6("0.10"), U6("0.20")];
    for (let i = 0; i < 3; i++) {
      const solver = [solver1, solver2, solver3][i];
      await (await stable.connect(solver).approve(engineAddress, bids[i])).wait();
      await (await engine.connect(solver).bid(bids[i])).wait();
    }
    const treasuryBefore = await stable.balanceOf(treasury.address);
    const settleReceipt = await (await engine.connect(treasury).settleAuction()).wait();
    const treasuryAfter = await stable.balanceOf(treasury.address);
    const solverRevenue = treasuryAfter - treasuryBefore;
    const settleGas = await receiptGasStable(settleReceipt, stablePerWpol);
    const solverNet = solverRevenue - settleGas;
    assert.ok(solverNet > 0n, "solver auction revenue not positive after settlement gas");

    const totalExternalRevenueAfterGas = backrunNet + rfqNet + solverNet;
    const coverageBps = Number(totalExternalRevenueAfterGas * 10000n) / Number(V14_NOTIONAL_USDT);
    assert.ok(totalExternalRevenueAfterGas > V14_REQUIRED_EDGE_USDT, "V15 did not cover V14 gap");
    assert.ok(coverageBps > REQUIRED_EDGE_BPS, "V15 coverage below required bps");

    const report = {
      version: "V15_EXTERNAL_REVENUE_ENGINE",
      chainId: Number((await ethers.provider.getNetwork()).chainId),
      forkBlock: Number(process.env.FORK_BLOCK_NUMBER || 90790000),
      v14ClosureRequirement: {
        notionalUsdt: fmt6(V14_NOTIONAL_USDT),
        requiredExternalRevenueUsdt: fmt6(V14_REQUIRED_EDGE_USDT),
        requiredBps: REQUIRED_EDGE_BPS
      },
      multiDex: {
        dexes: ["QuickSwap V2", "SushiSwap V2"],
        quickPair,
        sushiPair,
        victimVenue: "QuickSwap V2",
        backrunBuyVenue: "SushiSwap V2",
        backrunSellVenue: "QuickSwap V2"
      },
      privateExecution: {
        model: "controlled fork bundle semantics; not a live Polygon private relay",
        automineDisabled: true,
        victimBlock: victimReceipt.blockNumber,
        backrunBuyBlock: buyReceipt.blockNumber,
        backrunSellBlock: sellReceipt.blockNumber,
        sameBlockOrderedBundle: victimReceipt.blockNumber === sellReceipt.blockNumber
      },
      intrablockBackrun: {
        victimInputUsdt: fmt6(victimAmount),
        backrunInputUsdt: fmt6(plan.input),
        grossProfitUsdt: fmt6(backrunGross),
        gasUsdt: fmt6(backrunGas),
        netProfitUsdt: fmt6(backrunNet)
      },
      signedRfq: {
        signatureVerifiedOnchain: true,
        maker: rfqMaker.address,
        taker: rfqTaker.address,
        inputUsdt: fmt6(rfqInput),
        outputWpol: Number(ethers.formatEther(rfqOutput)),
        publicBuyVenue: publicBuy.name,
        publicSellVenue: publicSell.name,
        grossProfitUsdt: fmt6(rfqGross),
        gasUsdt: fmt6(rfqGas),
        netProfitUsdt: fmt6(rfqNet)
      },
      solverAuction: {
        bidders: [solver1.address, solver2.address, solver3.address],
        bidsUsdt: bids.map(fmt6),
        winner: await engine.bestSolver(),
        winningBidUsdt: fmt6(await engine.bestBid()),
        treasuryReceivedUsdt: fmt6(solverRevenue),
        settlementGasUsdt: fmt6(settleGas),
        netRevenueUsdt: fmt6(solverNet)
      },
      accounting: {
        internalSyntheticSupplyDelta: 0,
        backrunNetUsdt: fmt6(backrunNet),
        rfqNetUsdt: fmt6(rfqNet),
        solverNetUsdt: fmt6(solverNet),
        totalExternalRevenueAfterGasUsdt: fmt6(totalExternalRevenueAfterGas),
        coverageBps,
        coverageMultiple: Number(totalExternalRevenueAfterGas) / Number(V14_REQUIRED_EDGE_USDT),
        v14GapCovered: totalExternalRevenueAfterGas > V14_REQUIRED_EDGE_USDT
      },
      verdict: "PASS",
      limitation: "The two AMM legs use real pinned Polygon state. Bundle ordering is reproduced on Anvil, while RFQ maker inventory and solver bids are fork-local exogenous counterparties; this proves executable accounting and plumbing, not guaranteed live quote availability or relay inclusion."
    };
    fs.mkdirSync(path.join(process.cwd(), "reports"), { recursive: true });
    fs.writeFileSync(
      path.join(process.cwd(), "reports", "v15_external_revenue_fork.json"),
      JSON.stringify(report, null, 2)
    );
    console.log("V15_EXTERNAL_REVENUE_RESULT", JSON.stringify(report.accounting));
  });
});
