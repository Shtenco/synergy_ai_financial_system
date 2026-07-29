const assert = require('node:assert/strict');
const { ethers } = require('hardhat');

describe('Full QE QT solvency dividend relay integration', function () {
  this.timeout(900000);

  it('runs recovery, dividend relay and destination settlement in one test', async function () {
    const [deployer, owner, user] = await ethers.getSigners();

    const MockRelay = await ethers.getContractFactory('MockAcrossSpokePoolV3');
    const mockRelay = await MockRelay.deploy(owner.address);
    await mockRelay.waitForDeployment();

    const Adapter = await ethers.getContractFactory('AcrossMainnetDividendRelay');

    const MockToken = await ethers.getContractFactory('ForkSynQTToken');
    const token = await MockToken.deploy();
    await token.waitForDeployment();

    const adapter = await Adapter.deploy(
      await token.getAddress(),
      await mockRelay.getAddress(),
      owner.address,
      await token.getAddress(),
      100
    );
    await adapter.waitForDeployment();

    await token.mint(await adapter.getAddress(), ethers.parseEther('1.013'));

    const before = await token.balanceOf(owner.address);

    const now = Math.floor(Date.now()/1000);
    await adapter.relayPending(
      ethers.parseEther('1.00287'),
      ethers.ZeroAddress,
      now,
      now + 3600,
      0
    );

    const after = await token.balanceOf(owner.address);

    assert.equal(await mockRelay.deposits(), 1n);
    assert.equal(after - before, ethers.parseEther('1.00287'));
    assert.equal(await adapter.totalRelayedWPOL(), ethers.parseEther('1.013'));

    await assert.rejects(
      adapter.relayPending(ethers.parseEther('1'), ethers.ZeroAddress, now, now + 3600, 0)
    );

    await assert.rejects(
      adapter.relayPending(ethers.parseEther('0.9'), ethers.ZeroAddress, now, now + 3600, 0)
    );
  });
});
