const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { ethers, network } = require("hardhat");

const WPOL = "0x0d500B1d8E8eF31E21C99d1Db9A6444d3ADf1270";
const QUICKSWAP_FACTORY = "0x5757371414417b8C6CAad45bAeF941aBc7d3Ab32";
const AAVE_POOL = "0x794a61358D6845594F94dc1DB02A252b5b4814aD";
const GAS_PRICE = 274_000_000_000n;
const FLASH_PREMIUM_BPS = 5;
const GAS_LIMIT = 8_000_000;
const E = ethers.parseEther;
const RESULTS = [];

const WPOL_ABI = [
  "function deposit() payable",
  "function transfer(address,uint256) returns(bool)",
  "function balanceOf(address) view returns(uint256)"
];
const FACTORY_ABI = [
  "function createPair(address,address) returns(address)",
  "function getPair(address,address) view returns(address)"
];
const PAIR_ABI = [
  "function token0() view returns(address)",
  "function getReserves() view returns(uint112,uint112,uint32)",
  "function mint(address) returns(uint256)"
];
const AAVE_ABI = [
  "function getReservesList() view returns(address[])",
  "function FLASHLOAN_PREMIUM_TOTAL() view returns(uint128)",
  "function ADDRESSES_PROVIDER() view returns(address)"
];

function fairValue(reserves, token0, synAddress) {
  const synReserve = token0.toLowerCase() === synAddress.toLowerCase() ? reserves[0] : reserves[1];
  const wpolReserve = token0.toLowerCase() === synAddress.toLowerCase() ? reserves[1] : reserves[0];
  return synReserve + wpolReserve;
}

function record(row) {
  RESULTS.push(row);
  console.log(`FORK_RESULT ${JSON.stringify(row)}`);
}

async function mine(n) {
  for (let i = 0; i < n; i++) await network.provider.send("evm_mine");
}

async function deployFixture() {
  const [gov, treasury, bridge, attacker] = await ethers.getSigners();
  assert.notEqual(await ethers.provider.getCode(WPOL), "0x", "WPOL missing: not a Polygon fork");
  assert.notEqual(await ethers.provider.getCode(QUICKSWAP_FACTORY), "0x", "QuickSwap factory missing");

  let aaveReserveVisible = false;
  let aavePremiumBps = null;
  if ((await ethers.provider.getCode(AAVE_POOL)) !== "0x") {
    const aave = new ethers.Contract(AAVE_POOL, AAVE_ABI, ethers.provider);
    try {
      const reserves = (await aave.getReservesList()).map((x) => x.toLowerCase());
      aaveReserveVisible = reserves.includes(WPOL.toLowerCase());
      aavePremiumBps = Number(await aave.FLASHLOAN_PREMIUM_TOTAL());
      assert.notEqual(await aave.ADDRESSES_PROVIDER(), ethers.ZeroAddress, "Aave provider missing");
    } catch (error) {
      console.log(`AAVE_READ_ONLY_PROBE_FAILED ${error.message}`);
    }
  }

  const wpol = new ethers.Contract(WPOL, WPOL_ABI, gov);
  await (await wpol.deposit({ value: E("12") })).wait();
  await (await wpol.transfer(treasury.address, E("1"))).wait();
  await (await wpol.transfer(bridge.address, E("2"))).wait();

  const Token = await ethers.getContractFactory("ForkSynToken");
  const syn = await Token.deploy();
  await syn.waitForDeployment();

  const Demand = await ethers.getContractFactory("L1DemandEscrow");
  const demand = await Demand.deploy(await syn.getAddress(), WPOL, E("1"), E("4"));
  await demand.waitForDeployment();
  await (await wpol.transfer(await demand.getAddress(), E("4"))).wait();

  const Auction = await ethers.getContractFactory("SynergyQEVaultAuction");
  const auction = await Auction.deploy(
    await syn.getAddress(), WPOL, await demand.getAddress(), gov.address, treasury.address, bridge.address
  );
  await auction.waitForDeployment();
  await (await syn.setMinter(await auction.getAddress())).wait();

  const Lender = await ethers.getContractFactory("ForkFlashLender");
  const lender = await Lender.deploy(WPOL, FLASH_PREMIUM_BPS);
  await lender.waitForDeployment();
  await (await wpol.transfer(await lender.getAddress(), E("3"))).wait();

  const Solver = await ethers.getContractFactory("AaveFlashQESolverV2");
  const solver = await Solver.deploy(
    await lender.getAddress(), WPOL, await syn.getAddress(), await demand.getAddress(), await auction.getAddress()
  );
  await solver.waitForDeployment();
  const attackerSolver = await Solver.deploy(
    await lender.getAddress(), WPOL, await syn.getAddress(), await demand.getAddress(), await auction.getAddress()
  );
  await attackerSolver.waitForDeployment();

  return {
    gov,
    treasury,
    bridge,
    attacker,
    wpol,
    syn,
    demand,
    auction,
    lender,
    solver,
    attackerSolver,
    aaveReserveVisible,
    aavePremiumBps
  };
}

describe("Synergy QE: Polygon fork / real WPOL + QuickSwap", function () {
  this.timeout(240000);

  after(function () {
    fs.mkdirSync(path.join(process.cwd(), "reports"), { recursive: true });
    const keyed = Object.fromEntries(RESULTS.map((x) => [x.scenario, x]));
    fs.writeFileSync(
      path.join(process.cwd(), "reports", "synergy_qe_polygon_fork_results.json"),
      JSON.stringify({ generatedAt: new Date().toISOString(), results: RESULTS, ...keyed }, null, 2)
    );
  });

  it("proves open AMM QE is flash-loan extractable and measures LVR", async function () {
    const f = await deployFixture();
    const factory = new ethers.Contract(QUICKSWAP_FACTORY, FACTORY_ABI, f.gov);
    const existingPair = await factory.getPair(await f.syn.getAddress(), WPOL);
    if (existingPair === ethers.ZeroAddress) {
      await (await factory.createPair(await f.syn.getAddress(), WPOL)).wait();
    }
    const pairAddress = await factory.getPair(await f.syn.getAddress(), WPOL);
    const pair = new ethers.Contract(pairAddress, PAIR_ABI, f.gov);

    await (await f.syn.mint(f.gov.address, E("4"))).wait();
    await (await f.syn.transfer(pairAddress, E("4"))).wait();
    await (await f.wpol.transfer(pairAddress, E("1"))).wait();
    await (await pair.mint(f.gov.address)).wait();

    const token0 = await pair.token0();
    const beforeReserves = await pair.getReserves();
    const beforeFair = fairValue(beforeReserves, token0, await f.syn.getAddress());
    const solverBefore = await f.wpol.balanceOf(await f.solver.getAddress());

    const tx = await f.solver.runOpen(E("1.5"), pairAddress, 0, { gasLimit: GAS_LIMIT });
    const receipt = await tx.wait();

    const solverAfter = await f.wpol.balanceOf(await f.solver.getAddress());
    const afterReserves = await pair.getReserves();
    const afterFair = fairValue(afterReserves, token0, await f.syn.getAddress());
    const lvr = beforeFair - afterFair;
    const solverProfit = solverAfter - solverBefore;
    const gasCost = receipt.gasUsed * GAS_PRICE;
    const flashFee = await f.solver.lastPremium();

    assert.ok(solverProfit > 0n, "flash solver did not extract public-pool spread");
    assert.ok(lvr > 0n, "protocol LP did not lose fair-value inventory");
    record({
      scenario: "open_amm",
      forkBlock: await ethers.provider.getBlockNumber(),
      lender: "Aave-compatible deterministic fork lender",
      realPolygonWPOL: true,
      realQuickSwapFactory: true,
      aaveWPOLReserveVisible: f.aaveReserveVisible,
      aaveReportedPremiumBps: f.aavePremiumBps,
      solverProfitWPOL: Number(ethers.formatEther(solverProfit)),
      protocolLvrWPOL: Number(ethers.formatEther(lvr)),
      treasuryGainWPOL: 0,
      bridgeGainWPOL: 0,
      flashFeeWPOL: Number(ethers.formatEther(flashFee)),
      gasUsed: Number(receipt.gasUsed),
      gasCostPOLAt274Gwei: Number(ethers.formatEther(gasCost)),
      profitableAfterGasAt274Gwei: solverProfit > gasCost
    });
  });

  it("transfers funded L1 demand through proportional QE while growing liquid bridge and treasury", async function () {
    const f = await deployFixture();
    const treasuryBefore = await f.wpol.balanceOf(f.treasury.address);
    const bridgeBefore = await f.wpol.balanceOf(f.bridge.address);
    const supplyBefore = await f.syn.totalSupply();

    const latest = await ethers.provider.getBlock("latest");
    await (await f.auction.openProportionalWindow(5000, 2500, 5000, 5000, E("2"), latest.timestamp + 3600)).wait();
    const window = await f.auction.windows(0);
    assert.equal(window.baseAvailable, E("2"));
    assert.equal(window.auctionPriceX18, E("0.75"));

    const baseAmount = E("2");
    const maxPayment = E("1.5");
    const deadline = BigInt(latest.timestamp + 3500);
    const salt = ethers.id("synergy-qe-fork-salt");
    const solverAddress = await f.solver.getAddress();
    const digest = ethers.keccak256(ethers.AbiCoder.defaultAbiCoder().encode(
      ["address", "uint256", "uint256", "uint256", "bytes32", "uint64"],
      [solverAddress, 0, baseAmount, maxPayment, salt, deadline]
    ));
    await (await f.solver.commitClosed(digest)).wait();
    await mine(2);

    const solverBefore = await f.wpol.balanceOf(solverAddress);
    const tx = await f.solver.runClosed(
      E("1.5"), 0, baseAmount, maxPayment, salt, deadline, 0, { gasLimit: GAS_LIMIT }
    );
    const receipt = await tx.wait();
    const solverAfter = await f.wpol.balanceOf(solverAddress);
    const treasuryAfter = await f.wpol.balanceOf(f.treasury.address);
    const bridgeAfter = await f.wpol.balanceOf(f.bridge.address);
    const supplyAfter = await f.syn.totalSupply();
    const gasCost = receipt.gasUsed * GAS_PRICE;
    const flashFee = await f.solver.lastPremium();
    const treasuryGain = treasuryAfter - treasuryBefore;
    const bridgeGain = bridgeAfter - bridgeBefore;
    const synLiability = supplyAfter - supplyBefore;
    const protocolGain = treasuryGain + bridgeGain;
    const criterionMargin = protocolGain - synLiability - flashFee - gasCost;

    assert.equal(treasuryGain, E("0.75"));
    assert.equal(bridgeGain, E("0.75"));
    assert.ok(solverAfter - solverBefore > 0n, "closed solver earned no spread");
    assert.equal(await f.wpol.balanceOf(await f.auction.getAddress()), 0n, "auction retained unaccounted WPOL");
    record({
      scenario: "closed_qe_vault",
      forkBlock: await ethers.provider.getBlockNumber(),
      lender: "Aave-compatible deterministic fork lender",
      externalWPOLSource: "pre-funded L1DemandEscrow",
      treasuryGainWPOL: Number(ethers.formatEther(treasuryGain)),
      bridgeGainWPOL: Number(ethers.formatEther(bridgeGain)),
      protocolGainWPOL: Number(ethers.formatEther(protocolGain)),
      solverProfitWPOL: Number(ethers.formatEther(solverAfter - solverBefore)),
      synLiability: Number(ethers.formatEther(synLiability)),
      synLiabilityWPOLAtPar: Number(ethers.formatEther(synLiability)),
      flashFeeWPOL: Number(ethers.formatEther(flashFee)),
      gasUsed: Number(receipt.gasUsed),
      gasCostPOLAt274Gwei: Number(ethers.formatEther(gasCost)),
      criterionMarginWPOL: Number(ethers.formatEther(criterionMargin)),
      criterionPass: criterionMargin > 0n,
      protocolLvrWPOL: 0
    });
  });

  it("rejects zero price and prevents commitment front-running", async function () {
    const f = await deployFixture();
    const latest = await ethers.provider.getBlock("latest");

    await assert.rejects(
      f.auction.openProportionalWindow(5000, 10000, 5000, 5000, E("2"), latest.timestamp + 3600)
    );

    await (await f.auction.openProportionalWindow(5000, 2500, 5000, 5000, E("2"), latest.timestamp + 3600)).wait();
    const baseAmount = E("2");
    const maxPayment = E("1.5");
    const deadline = BigInt(latest.timestamp + 3500);
    const salt = ethers.id("bound-to-solver");
    const solverAddress = await f.solver.getAddress();
    const digest = ethers.keccak256(ethers.AbiCoder.defaultAbiCoder().encode(
      ["address", "uint256", "uint256", "uint256", "bytes32", "uint64"],
      [solverAddress, 0, baseAmount, maxPayment, salt, deadline]
    ));
    await (await f.solver.commitClosed(digest)).wait();
    await mine(2);

    await assert.rejects(
      f.attackerSolver.runClosed(
        E("1.5"), 0, baseAmount, maxPayment, salt, deadline, 0, { gasLimit: GAS_LIMIT }
      ).then((tx) => tx.wait())
    );
    await (await f.solver.runClosed(
      E("1.5"), 0, baseAmount, maxPayment, salt, deadline, 0, { gasLimit: GAS_LIMIT }
    )).wait();
    record({
      scenario: "security_guards",
      forkBlock: await ethers.provider.getBlockNumber(),
      zeroPriceRejected: true,
      frontRunRejected: true,
      commitmentBoundToSolver: true
    });
  });
});
