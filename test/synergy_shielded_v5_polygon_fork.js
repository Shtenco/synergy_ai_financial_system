const assert = require("assert");
const hre = require("hardhat");
const { ethers, network } = hre;

const ROUTER = "0xa5E0829CaCEd8fFDD4De3c43696c57F7D7A678ff";
const USDT = "0xc2132d05d31c914a87c6611c10748aeb04b58e8f";
const WPOL = "0x0d500B1d8E8eF31E21C99d1Db9A6444d3ADf1270";
const WPOL_USDT_PAIR = "0x604229c960e5CACF2aaEAc8Be68Ac07BA9dF81c3";
const ERC20 = [
  "function balanceOf(address) view returns(uint256)",
  "function transfer(address,uint256) returns(bool)",
  "function approve(address,uint256) returns(bool)",
];
const PAIR = [
  "function token0() view returns(address)",
  "function token1() view returns(address)",
  "function getReserves() view returns(uint112,uint112,uint32)",
  "function sync()",
];

function cost(receipt) {
  return receipt.gasUsed * (receipt.gasPrice || 0n);
}

async function fundUsdt(target, amount) {
  await network.provider.send("hardhat_setBalance", [WPOL_USDT_PAIR, "0x3635c9adc5dea00000"]);
  await network.provider.send("hardhat_impersonateAccount", [WPOL_USDT_PAIR]);
  const donor = await ethers.getSigner(WPOL_USDT_PAIR);
  const usdt = new ethers.Contract(USDT, ERC20, donor);
  await (await usdt.transfer(target, amount)).wait();
  await (await new ethers.Contract(WPOL_USDT_PAIR, PAIR, donor).sync()).wait();
  await network.provider.send("hardhat_stopImpersonatingAccount", [WPOL_USDT_PAIR]);
}

async function polPriceUsdt() {
  const pair = new ethers.Contract(WPOL_USDT_PAIR, PAIR, ethers.provider);
  const [token0, token1, reserves] = await Promise.all([
    pair.token0(), pair.token1(), pair.getReserves()
  ]);
  let usdtReserve;
  let polReserve;
  if (token0.toLowerCase() === USDT && token1.toLowerCase() === WPOL.toLowerCase()) {
    usdtReserve = reserves[0];
    polReserve = reserves[1];
  } else {
    usdtReserve = reserves[1];
    polReserve = reserves[0];
  }
  return Number(ethers.formatUnits(usdtReserve, 6)) / Number(ethers.formatEther(polReserve));
}

async function deployAtomicFixture() {
  const [admin] = await ethers.getSigners();
  const adminAddress = await admin.getAddress();
  await fundUsdt(adminAddress, 3_000_000n);
  const usdt = new ethers.Contract(USDT, ERC20, admin);
  let setupGas = 0n;

  const Bootstrap = await ethers.getContractFactory("SynergyQuickSwapBootstrapV5", admin);
  const bootstrap = await Bootstrap.deploy(adminAddress);
  setupGas += cost(await bootstrap.deploymentTransaction().wait());
  setupGas += cost(await (await usdt.approve(await bootstrap.getAddress(), 2_000_000n)).wait());
  const block = await ethers.provider.getBlock("latest");
  setupGas += cost(await (await bootstrap.bootstrap(block.timestamp + 90)).wait());

  const token = await ethers.getContractAt("RebaseSynaExactV3", await bootstrap.token(), admin);
  const controller = await ethers.getContractAt(
    "BullishQuickSwapShieldedV5",
    await bootstrap.controller(),
    admin
  );
  return { admin, adminAddress, bootstrap, token, controller, setupGas };
}

async function protectedCycle(bootstrap, controller, minMetric = 0n) {
  const block = await ethers.provider.getBlock("latest");
  const stateHash = await controller.currentExecutionStateHash();
  const nonce = await controller.nonce();
  return bootstrap.executeProtectedCycle(
    nonce,
    stateHash,
    block.hash,
    block.timestamp + 60,
    ethers.parseUnits("500", "gwei"),
    minMetric
  );
}

async function expectRevert(promise, pattern) {
  let reverted = false;
  try {
    await promise;
  } catch (error) {
    reverted = true;
    assert(
      String(error.message).includes(pattern),
      `expected ${pattern}, got ${error.message}`
    );
  }
  assert(reverted, `expected revert ${pattern}`);
}

describe("Synergy Coin Shielded V5 on pinned Polygon fork", function () {
  this.timeout(600000);

  it("atomically creates Synergy Coin, controller and QuickSwap SYNA/USDT pair", async function () {
    const { admin, bootstrap, token, controller } = await deployAtomicFixture();
    assert.equal(await token.name(), "Synergy Coin");
    assert.equal(await token.symbol(), "SYNA");
    assert.equal(await bootstrap.bootstrapped(), true);
    assert.notEqual(await bootstrap.pair(), ethers.ZeroAddress);
    assert.notEqual(await ethers.provider.getCode(await bootstrap.pair()), "0x");
    assert.equal(await controller.owner(), await bootstrap.getAddress());

    const block = await ethers.provider.getBlock("latest");
    await expectRevert(
      controller.connect(admin).executeCycle(0, block.timestamp + 60, 0),
      "OPERATOR"
    );
  });

  it("fails closed on zero router output and stale/front-run state", async function () {
    const { bootstrap, token, controller } = await deployAtomicFixture();
    await expectRevert(
      controller.checkedQuoteOut(await token.getAddress(), USDT, 1n),
      "ZERO_LOCAL_PRICE"
    );

    const staleState = await controller.currentExecutionStateHash();
    const before = await ethers.provider.getBlock("latest");
    await (await protectedCycle(bootstrap, controller)).wait();
    const after = await ethers.provider.getBlock("latest");
    await expectRevert(
      bootstrap.executeProtectedCycle(
        await controller.nonce(),
        staleState,
        after.hash,
        after.timestamp + 60,
        ethers.parseUnits("500", "gwei"),
        0
      ),
      "STATE_CHANGED"
    );
    await expectRevert(
      bootstrap.executeProtectedCycle(
        await controller.nonce(),
        await controller.currentExecutionStateHash(),
        before.hash,
        after.timestamp + 60,
        ethers.parseUnits("500", "gwei"),
        0
      ),
      "PARENT_BLOCK_CHANGED"
    );
  });

  it("keeps the first ten cycles positive after complete V5 setup and runtime gas", async function () {
    const { bootstrap, controller, setupGas } = await deployAtomicFixture();
    const initialMetric = await controller.systemMetricUsdt();
    const initialPrice = await controller.spotPriceX18();
    let runtimeGas = 0n;
    for (let i = 0; i < 10; i += 1) {
      runtimeGas += cost(await (await protectedCycle(bootstrap, controller)).wait());
    }
    const finalMetric = await controller.systemMetricUsdt();
    const finalPrice = await controller.spotPriceX18();
    const fullGasPol = Number(ethers.formatEther(setupGas + runtimeGas));
    const fullGasUsdt = fullGasPol * await polPriceUsdt();
    const gross = Number(ethers.formatUnits(finalMetric - initialMetric, 6));
    const net = gross - fullGasUsdt;
    const report = {
      initialMetricUsdt: Number(ethers.formatUnits(initialMetric, 6)),
      finalMetricUsdt: Number(ethers.formatUnits(finalMetric, 6)),
      grossGrowthUsdt: gross,
      fullGasPol,
      fullGasUsdt,
      netGrowthAfterGasUsdt: net,
      priceMultiple: Number(finalPrice) / Number(initialPrice),
    };
    console.log("SHIELDED_V5_FIRST10", JSON.stringify(report));
    assert(finalPrice > initialPrice, "price did not rise");
    assert(net > 0, `V5 first ten net is non-positive: ${net}`);
  });

  it("passes protected robot and exact POL refill", async function () {
    const { bootstrap, controller } = await deployAtomicFixture();
    await (await bootstrap.setRefillConfig(1_040_000n, 0, 100, 500, 10)).wait();

    const block0 = await ethers.provider.getBlock("latest");
    const state0 = await controller.currentExecutionStateHash();
    const robotBefore = await controller.robotUsdt();
    await (await bootstrap.refillRobotCapitalProtected(
      1_040_000n,
      state0,
      block0.hash,
      block0.timestamp + 60,
      ethers.parseUnits("500", "gwei")
    )).wait();
    assert((await controller.robotUsdt()) > robotBefore);

    await (await protectedCycle(bootstrap, controller)).wait();
    const exactPol = ethers.parseEther("0.001");
    const required = await controller.checkedQuoteIn(USDT, WPOL, exactPol);
    const maxUsdt = required * 10100n / 10000n + 1n;
    const block1 = await ethers.provider.getBlock("latest");
    const routeState = await controller.currentGasRouteStateHash();
    await (await bootstrap.refillKeeperGasProtected(
      exactPol,
      maxUsdt,
      routeState,
      block1.hash,
      block1.timestamp + 60,
      ethers.parseUnits("500", "gwei")
    )).wait();
    assert((await controller.cumulativeGasRefillUsdt()) > 0n);
  });
});
