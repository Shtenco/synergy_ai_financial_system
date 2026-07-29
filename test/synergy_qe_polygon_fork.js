const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { ethers, network } = require("hardhat");

const WPOL = "0x0d500B1d8E8eF31E21C99d1Db9A6444d3ADf1270";
const QUICKSWAP_FACTORY = "0x5757371414417b8C6CAad45bAeF941aBc7d3Ab32";
const AAVE_POOL = "0x794a61358D6845594F94dc1DB02A252b5b4814aD";
const GAS_PRICE = 274_000_000_000n;
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
const AAVE_ABI = ["function getReservesList() view returns(address[])"];

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
  assert.notEqual(await ethers.provider.getCode(AAVE_POOL), "0x", "Aave Pool missing");

  const aave = new ethers.Contract(AAVE_POOL, AAVE_ABI, ethers.provider);
  const reserves = (await aave.getReservesList()).map((x) => x.toLowerCase());
  assert.ok(reserves.includes(WPOL.toLowerCase()), "Aave fork has no WPOL reserve");

  const wpol = new ethers.Contract(WPOL, WPOL_ABI, gov);
  await (await wpol.deposit({ value: E("10") })).wait();
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

  const Solver = await ethers.getContractFactory("AaveFlashQESolver");
  const solver = await Solver.deploy(AAVE_POOL, WPOL, await syn.getAddress(), await demand.getAddress(), await auction.getAddress());
  await solver.waitForDeployment();
  const attackerSolver = await Solver.deploy(AAVE_POOL, WPOL, await syn.getAddress(), await demand.getAddress(), await auction.getAddress());
  await attackerSolver.waitForDeployment();

  return { gov, treasury, bridge, attacker, wpol, syn, demand, auction, solver, attackerSolver };
}

describe("Synergy QE: Polygon fork / real Aave + QuickSwap", function () {
  this.timeout(240000);

  after(function () {
    fs.mkdirSync(path.join(process.cwd(), "reports"), { recursive: true });
    fs.writeFileSync(
      path.join(process.cwd(), "reports", "synergy_qe_polygon_fork_results.json"),
      JSON.stringify({ generatedAt: new Date().toISOString(), results: RESULTS }, null, 2)
    );
  });

  it("proves open AMM QE is flash-loan extractable and measures LVR", async function () {
    const f = await deployFixture();
    const factory = new ethers.Contract(QUICKSWAP_FACTORY, FACTORY_ABI, f.gov);
    await (await factory.createPair(await f.syn.getAddress(), WPOL)).wait();
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

    const tx = await f.solver.runOpen(E("1.5"), pairAddress, E("0.1"));
    const receipt = await tx.wait();

    const solverAfter = await f.wpol.balanceOf(await f.solver.getAddress());
    const afterReserves = await pair.getReserves();
    const afterFair = fairValue(afterReserves, token0, await f.syn.getAddress());
    const lvr = beforeFair - afterFair;
    const solverProfit = solverAfter - solverBefore;
    const gasCost = receipt.gasUsed * GAS_PRICE;

    assert.ok(solverProfit > E("0.1"), "flash solver did not extract public-pool spread");
    assert.ok(lvr > 0n, "protocol LP did not lose fair-value inventory");
    assert.ok(solverProfit > gasCost, "trade is not profitable after observed Polygon gas");
    record({
      scenario: "open_amm",
      forkBlock: await ethers.provider.getBlockNumber(),
      solverProfitWPOL: Number(ethers.formatEther(solverProfit)),
      protocolLvrWPOL: Number(ethers.formatEther(lvr)),
      treasuryGainWPOL: 0,
      bridgeGainWPOL: 0,
      gasUsed: Number(receipt.gasUsed),
      gasCostPOLAt274Gwei: Number(ethers.formatEther(gasCost))
    });
  });

  it("transfers funded L1 demand through proportional QE while growing liquid bridge and treasury", async function () {
    const f = await deployFixture();
    const treasuryBefore = await f.wpol.balanceOf(f.treasury.address);
    const bridgeBefore = await f.wpol.balanceOf(f.bridge.address);

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
    const tx = await f.solver.runClosed(E("1.5"), 0, baseAmount, maxPayment, salt, deadline, E("0.2"));
    const receipt = await tx.wait();
    const solverAfter = await f.wpol.balanceOf(solverAddress);
    const treasuryAfter = await f.wpol.balanceOf(f.treasury.address);
    const bridgeAfter = await f.wpol.balanceOf(f.bridge.address);
    const gasCost = receipt.gasUsed * GAS_PRICE;

    assert.equal(treasuryAfter - treasuryBefore, E("0.75"));
    assert.equal(bridgeAfter - bridgeBefore, E("0.75"));
    assert.ok(solverAfter - solverBefore > E("0.2"));
    assert.ok(solverAfter - solverBefore > gasCost, "closed fill is not profitable after observed gas");
    assert.equal(await f.wpol.balanceOf(await f.auction.getAddress()), 0n, "auction retained unaccounted WPOL");
    record({
      scenario: "closed_qe_vault",
      forkBlock: await ethers.provider.getBlockNumber(),
      treasuryGainWPOL: Number(ethers.formatEther(treasuryAfter - treasuryBefore)),
      bridgeGainWPOL: Number(ethers.formatEther(bridgeAfter - bridgeBefore)),
      solverProfitWPOL: Number(ethers.formatEther(solverAfter - solverBefore)),
      protocolLvrWPOL: 0,
      gasUsed: Number(receipt.gasUsed),
      gasCostPOLAt274Gwei: Number(ethers.formatEther(gasCost))
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
      f.attackerSolver.runClosed(E("1.5"), 0, baseAmount, maxPayment, salt, deadline, 0)
    );
    await (await f.solver.runClosed(E("1.5"), 0, baseAmount, maxPayment, salt, deadline, E("0.2"))).wait();
    record({
      scenario: "security_guards",
      forkBlock: await ethers.provider.getBlockNumber(),
      zeroPriceRejected: true,
      frontRunRejected: true
    });
  });
});
