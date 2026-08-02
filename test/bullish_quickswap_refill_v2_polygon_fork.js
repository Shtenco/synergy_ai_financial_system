const assert = require("assert");
const hre = require("hardhat");
const { ethers, network } = hre;

const ROUTER = "0xa5E0829CaCEd8fFDD4De3c43696c57F7D7A678ff";
const FACTORY = "0x5757371414417b8C6CAad45bAeF941aBc7d3Ab32";
const USDT = "0xc2132D05D31c914a87C6611C10748AaCb58e8F";
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
];

function receiptCost(receipt) {
  return receipt.gasUsed * (receipt.gasPrice || 0n);
}

async function fundUsdt(target, amount) {
  await network.provider.send("hardhat_setBalance", [WPOL_USDT_PAIR, "0x3635c9adc5dea00000"]);
  await network.provider.send("hardhat_impersonateAccount", [WPOL_USDT_PAIR]);
  const donor = await ethers.getSigner(WPOL_USDT_PAIR);
  const token = new ethers.Contract(USDT, ERC20, donor);
  await (await token.transfer(target, amount)).wait();
  await network.provider.send("hardhat_stopImpersonatingAccount", [WPOL_USDT_PAIR]);
}

async function polPriceUsdt() {
  const pair = new ethers.Contract(WPOL_USDT_PAIR, PAIR, ethers.provider);
  const [token0, token1, reserves] = await Promise.all([pair.token0(), pair.token1(), pair.getReserves()]);
  let usdtReserve;
  let polReserve;
  if (token0.toLowerCase() === USDT.toLowerCase() && token1.toLowerCase() === WPOL.toLowerCase()) {
    usdtReserve = reserves[0];
    polReserve = reserves[1];
  } else {
    assert.equal(token1.toLowerCase(), USDT.toLowerCase());
    assert.equal(token0.toLowerCase(), WPOL.toLowerCase());
    usdtReserve = reserves[1];
    polReserve = reserves[0];
  }
  return Number(ethers.formatUnits(usdtReserve, 6)) / Number(ethers.formatEther(polReserve));
}

async function deployFixture() {
  const [owner] = await ethers.getSigners();
  const ownerAddress = await owner.getAddress();
  assert.notEqual(await ethers.provider.getCode(ROUTER), "0x");
  assert.notEqual(await ethers.provider.getCode(FACTORY), "0x");
  assert.notEqual(await ethers.provider.getCode(USDT), "0x");
  assert.notEqual(await ethers.provider.getCode(WPOL), "0x");
  await fundUsdt(ownerAddress, 3_000_000n);

  let setupGas = 0n;
  const Token = await ethers.getContractFactory("RebaseSynaV2", owner);
  const token = await Token.deploy(ownerAddress);
  setupGas += receiptCost(await token.deploymentTransaction().wait());

  const Controller = await ethers.getContractFactory("BullishQuickSwapCentralBankV2", owner);
  const controller = await Controller.deploy(ownerAddress, ROUTER, USDT, WPOL, await token.getAddress());
  setupGas += receiptCost(await controller.deploymentTransaction().wait());

  setupGas += receiptCost(await (await token.setController(await controller.getAddress())).wait());
  const usdt = new ethers.Contract(USDT, ERC20, owner);
  setupGas += receiptCost(await (await usdt.approve(await controller.getAddress(), 2_000_000n)).wait());
  const block = await ethers.provider.getBlock("latest");
  setupGas += receiptCost(await (
    await controller.initialize(
      ethers.parseEther("1000000"),
      ethers.parseEther("500000"),
      1_000_000n,
      1_000_000n,
      block.timestamp + 3600
    )
  ).wait());
  return { owner, token, controller, setupGas };
}

describe("BullishQuickSwapCentralBankV2 on Polygon fork", function () {
  this.timeout(300000);

  it("makes the first ten cycles positive after full setup and cycle gas", async function () {
    const { controller, setupGas } = await deployFixture();
    const initialMetric = await controller.systemMetricUsdt();
    const initialPrice = await controller.spotPriceX18();
    let cycleGas = 0n;
    for (let i = 0; i < 10; i += 1) {
      const block = await ethers.provider.getBlock("latest");
      const receipt = await (await controller.executeCycle(i, block.timestamp + 3600, 0)).wait();
      cycleGas += receiptCost(receipt);
    }
    const finalMetric = await controller.systemMetricUsdt();
    const finalPrice = await controller.spotPriceX18();
    const totalGasPol = Number(ethers.formatEther(setupGas + cycleGas));
    const gasUsdt = totalGasPol * await polPriceUsdt();
    const grossGrowth = Number(ethers.formatUnits(finalMetric - initialMetric, 6));
    const net = grossGrowth - gasUsdt;
    console.log(JSON.stringify({
      cycles: 10,
      initialMetricUsdt: Number(ethers.formatUnits(initialMetric, 6)),
      finalMetricUsdt: Number(ethers.formatUnits(finalMetric, 6)),
      grossGrowthUsdt: grossGrowth,
      fullGasPol: totalGasPol,
      fullGasUsdt: gasUsdt,
      netGrowthAfterGasUsdt: net,
      priceMultiple: Number(finalPrice) / Number(initialPrice),
    }));
    assert(finalPrice > initialPrice, "price did not rise");
    assert(net > 0, `first ten cycles were not positive: ${net}`);
  });

  it("continues beyond the old 140-cycle robot-capital exhaustion point", async function () {
    const { controller } = await deployFixture();
    await (await controller.setRefillConfig(300_000n, 0, 100, 500, 10)).wait();
    for (let i = 0; i < 160; i += 1) {
      const block = await ethers.provider.getBlock("latest");
      await (await controller.executeCycle(i, block.timestamp + 3600, 0)).wait();
    }
    assert.equal(await controller.nonce(), 160n);
    assert((await controller.robotUsdt()) >= 200_000n, "robot capital below one-cycle minimum");

    const router = new ethers.Contract(
      ROUTER,
      ["function getAmountsIn(uint256,address[]) view returns(uint256[] memory)"],
      ethers.provider
    );
    const exactPol = ethers.parseEther("0.0001");
    const quote = await router.getAmountsIn(exactPol, [USDT, WPOL]);
    const maxUsdt = quote[0] * 10100n / 10000n + 1n;
    const treasury = await controller.treasuryUsdt();
    if (treasury >= maxUsdt) {
      const block = await ethers.provider.getBlock("latest");
      await (await controller.refillKeeperGas(exactPol, maxUsdt, block.timestamp + 3600)).wait();
      assert((await controller.cumulativeGasRefillUsdt()) > 0n);
    }
  });
});
