const fs = require("fs");
const path = require("path");
const { expect } = require("chai");
const { ethers, network } = require("hardhat");

const USDT = "0xc2132D05D31c914a87C6611C10748AaCbA1b58e8F";
const WPOL = "0x0d500B1d8E8eF31E21C99d1Db9A6444d3ADf1270";
const WPOL_USDT_PAIR = "0x604229c960e5CACF2aaEAc8Be68Ac07BA9dF81c3";
const FIXTURE_DONOR = WPOL_USDT_PAIR;
const DEV_MNEMONIC = "test test test test test test test test test test test junk";

const ERC20_ABI = [
  "function balanceOf(address) view returns (uint256)",
  "function transfer(address,uint256) returns (bool)",
  "function approve(address,uint256) returns (bool)",
];
const PAIR_ABI = [
  "function token0() view returns (address)",
  "function token1() view returns (address)",
  "function getReserves() view returns (uint112,uint112,uint32)",
];

async function rpc(method, params = []) {
  try {
    return await network.provider.send(method, params);
  } catch (first) {
    const fallback = method.startsWith("anvil_")
      ? method.replace("anvil_", "hardhat_")
      : method;
    if (fallback === method) throw first;
    return network.provider.send(fallback, params);
  }
}

async function mineBlocks(count) {
  try {
    await network.provider.send("anvil_mine", [`0x${count.toString(16)}`]);
  } catch (_) {
    await network.provider.send("hardhat_mine", [`0x${count.toString(16)}`]);
  }
}

async function polPriceUsdt() {
  const pair = new ethers.Contract(WPOL_USDT_PAIR, PAIR_ABI, ethers.provider);
  const [token0, token1, reserves] = await Promise.all([
    pair.token0(),
    pair.token1(),
    pair.getReserves(),
  ]);
  const r0 = reserves[0];
  const r1 = reserves[1];
  let usdtReserve;
  let wpolReserve;
  if (token0.toLowerCase() === USDT.toLowerCase() && token1.toLowerCase() === WPOL.toLowerCase()) {
    usdtReserve = r0;
    wpolReserve = r1;
  } else if (token1.toLowerCase() === USDT.toLowerCase() && token0.toLowerCase() === WPOL.toLowerCase()) {
    usdtReserve = r1;
    wpolReserve = r0;
  } else {
    throw new Error("Pinned pair is not WPOL/USDT");
  }
  return Number(ethers.formatUnits(usdtReserve, 6)) / Number(ethers.formatEther(wpolReserve));
}

describe("SYNERGY bullish CB microcycle on pinned Polygon fork", function () {
  it("runs 15 atomic cycles over 150 blocks and rejects false economic profit", async function () {
    const chainId = Number((await ethers.provider.getNetwork()).chainId);
    expect(chainId).to.equal(137);

    const owner = ethers.Wallet.fromPhrase(DEV_MNEMONIC).connect(ethers.provider);
    await rpc("anvil_setBalance", [owner.address, "0x152d02c7e14af6800000"]);
    await rpc("anvil_setBalance", [FIXTURE_DONOR, "0x3635c9adc5dea00000"]);
    await rpc("anvil_impersonateAccount", [FIXTURE_DONOR]);
    const donor = await ethers.getImpersonatedSigner(FIXTURE_DONOR);

    const usdt = new ethers.Contract(USDT, ERC20_ABI, owner);
    const donorUsdt = usdt.connect(donor);
    const ownerBefore = await usdt.balanceOf(owner.address);
    await (await donorUsdt.transfer(owner.address, 2_000_000n)).wait();
    expect((await usdt.balanceOf(owner.address)) - ownerBefore).to.equal(2_000_000n);

    const Token = await ethers.getContractFactory("RebaseSynaV1", owner);
    const token = await Token.deploy(owner.address);
    await token.waitForDeployment();

    const Controller = await ethers.getContractFactory("BullishCentralBankV1", owner);
    const controller = await Controller.deploy(owner.address, USDT, await token.getAddress());
    await controller.waitForDeployment();

    const Pool = await ethers.getContractFactory("SecureSynaUsdtPoolV1", owner);
    const pool = await Pool.deploy(USDT, await token.getAddress(), await controller.getAddress());
    await pool.waitForDeployment();

    await (await token.setController(await controller.getAddress())).wait();
    await (await controller.setPool(await pool.getAddress())).wait();
    await (await usdt.approve(await controller.getAddress(), 2_000_000n)).wait();
    await (await controller.initialize(
      ethers.parseEther("1000000"),
      ethers.parseEther("500000"),
      1_000_000n,
      1_000_000n,
    )).wait();

    const initialBlock = await ethers.provider.getBlockNumber();
    const initialPrice = await pool.priceX18();
    const initialSupply = await token.totalSupply();
    const initialHardNav = await controller.hardNavUsdt();
    const initialPoolUsdt = await usdt.balanceOf(await pool.getAddress());
    expect(initialHardNav).to.equal(2_000_000n);

    let totalGasWei = 0n;
    const cycles = [];
    for (let i = 0; i < 15; i += 1) {
      const block = await ethers.provider.getBlock("latest");
      const tx = await controller.executeCycle(i, block.timestamp + 3600, 2_000_000n);
      const receipt = await tx.wait();
      const gasPrice = receipt.gasPrice ?? tx.gasPrice ?? 0n;
      totalGasWei += receipt.gasUsed * gasPrice;
      cycles.push({
        cycle: i + 1,
        blockNumber: receipt.blockNumber,
        gasUsed: receipt.gasUsed.toString(),
        gasPriceWei: gasPrice.toString(),
        priceX18: (await pool.priceX18()).toString(),
        supply: (await token.totalSupply()).toString(),
        hardNavUsdtRaw: (await controller.hardNavUsdt()).toString(),
      });
      await mineBlocks(9);
    }

    const finalBlock = await ethers.provider.getBlockNumber();
    const finalPrice = await pool.priceX18();
    const finalSupply = await token.totalSupply();
    const finalHardNav = await controller.hardNavUsdt();
    const finalPoolUsdt = await usdt.balanceOf(await pool.getAddress());
    const controllerUsdt = await usdt.balanceOf(await controller.getAddress());
    const polUsdt = await polPriceUsdt();
    const gasPol = Number(ethers.formatEther(totalGasWei));
    const gasUsdt = gasPol * polUsdt;
    const grossTvlInitial = Number(ethers.formatUnits(initialPoolUsdt * 2n, 6));
    const grossTvlFinal = Number(ethers.formatUnits(finalPoolUsdt * 2n, 6));
    const hardNavInitialWithGas = 3.0;
    const hardNavFinalWithGas = Number(ethers.formatUnits(finalHardNav, 6)) + Math.max(0, 1.0 - gasUsdt);
    const hardNavDelta = hardNavFinalWithGas - hardNavInitialWithGas;

    expect(finalBlock - initialBlock).to.equal(150);
    expect(finalPrice).to.be.greaterThan(initialPrice);
    expect(finalSupply).to.be.lessThan(initialSupply);
    expect(finalHardNav).to.equal(initialHardNav);
    expect(controllerUsdt + finalPoolUsdt).to.equal(2_000_000n);
    expect(gasUsdt).to.be.lessThan(1.0);
    expect(hardNavDelta).to.be.lessThan(0.0);

    const report = {
      scenario: "SYNERGY_BULLISH_CB_MICROCYCLE_V1_POLYGON_FORK",
      evidenceClass: "STRUCTURAL_FORK_WITH_REAL_POLYGON_GAS_AND_USDT_FIXTURE",
      chainId,
      forkBlockConfigured: Number(process.env.FORK_BLOCK_NUMBER || 0),
      coveredBlocks: finalBlock - initialBlock,
      cycles: 15,
      trades: 105,
      startingCapital: {
        cbAndRobotUsdt: 1,
        poolUsdt: 1,
        gasBudgetUsdt: 1,
        fixtureSource: FIXTURE_DONOR,
        fixtureIsRevenue: false,
      },
      price: {
        initialX18: initialPrice.toString(),
        finalX18: finalPrice.toString(),
        multiple: Number(finalPrice) / Number(initialPrice),
      },
      supply: {
        initial: initialSupply.toString(),
        final: finalSupply.toString(),
        changePct: (Number(finalSupply) / Number(initialSupply) - 1) * 100,
      },
      tvl: {
        grossInitialUsdt: grossTvlInitial,
        grossFinalUsdt: grossTvlFinal,
        grossChangeUsdt: grossTvlFinal - grossTvlInitial,
        organicExternalChangeUsdt: 0,
      },
      accounting: {
        hardNavBeforeGasUsdt: Number(ethers.formatUnits(finalHardNav, 6)),
        externalRevenueUsdt: 0,
        totalGasWei: totalGasWei.toString(),
        gasPol,
        polUsdt,
        gasUsdt,
        hardNavInitialIncludingGasUsdt: hardNavInitialWithGas,
        hardNavFinalIncludingRemainingGasUsdt: hardNavFinalWithGas,
        hardNavDeltaUsdt: hardNavDelta,
      },
      protections: {
        atomicSevenTradeBatch: true,
        poolControllerOnly: true,
        zeroPriceGuard: true,
        nonce: true,
        deadline: true,
        hardNavGate: true,
        publicIntermediateState: false,
      },
      strictVerdict: "FAIL_NO_EXTERNAL_VALUE",
      mainnetGate: "BLOCKED_BY_FORK_ECONOMICS",
      cyclesDetail: cycles,
    };

    fs.mkdirSync(path.join(process.cwd(), "reports"), { recursive: true });
    fs.writeFileSync(
      path.join(process.cwd(), "reports", "bullish_cb_microcycle_polygon_fork.json"),
      JSON.stringify(report, null, 2),
    );
  });

  it("rejects public pool use, nonce replay, stale deadline and invented NAV", async function () {
    const owner = ethers.Wallet.fromPhrase(DEV_MNEMONIC).connect(ethers.provider);
    const attacker = ethers.Wallet.createRandom().connect(ethers.provider);
    await rpc("anvil_setBalance", [attacker.address, "0x3635c9adc5dea00000"]);
    await rpc("anvil_setBalance", [FIXTURE_DONOR, "0x3635c9adc5dea00000"]);
    await rpc("anvil_impersonateAccount", [FIXTURE_DONOR]);
    const donor = await ethers.getImpersonatedSigner(FIXTURE_DONOR);
    const usdt = new ethers.Contract(USDT, ERC20_ABI, owner);
    await (await usdt.connect(donor).transfer(owner.address, 2_000_000n)).wait();

    const Token = await ethers.getContractFactory("RebaseSynaV1", owner);
    const token = await Token.deploy(owner.address);
    await token.waitForDeployment();
    const Controller = await ethers.getContractFactory("BullishCentralBankV1", owner);
    const controller = await Controller.deploy(owner.address, USDT, await token.getAddress());
    await controller.waitForDeployment();
    const Pool = await ethers.getContractFactory("SecureSynaUsdtPoolV1", owner);
    const pool = await Pool.deploy(USDT, await token.getAddress(), await controller.getAddress());
    await pool.waitForDeployment();
    await (await token.setController(await controller.getAddress())).wait();
    await (await controller.setPool(await pool.getAddress())).wait();
    await (await usdt.approve(await controller.getAddress(), 2_000_000n)).wait();
    await (await controller.initialize(ethers.parseEther("1000000"), ethers.parseEther("500000"), 1_000_000n, 1_000_000n)).wait();

    await expect(pool.connect(attacker).buyWithNetUsdt(1n, 1n)).to.be.revertedWith("CONTROLLER");
    const block = await ethers.provider.getBlock("latest");
    await expect(controller.executeCycle(1, block.timestamp + 100, 2_000_000n)).to.be.revertedWith("NONCE");
    await expect(controller.executeCycle(0, block.timestamp - 1, 2_000_000n)).to.be.revertedWith("DEADLINE");
    await expect(controller.executeCycle(0, block.timestamp + 100, 2_000_001n)).to.be.revertedWith("HARD_NAV_LOSS");
  });
});
