#!/usr/bin/env python3
"""Batch Anvil mining and add fine-grained solver-auction diagnostics."""
from pathlib import Path

path = Path("test/external_revenue_v15_polygon_fork.js")
text = path.read_text(encoding="utf-8")

old_mining = '''async function mineBlocks(count) {
  for (let i = 0; i < count; i += 1) {
    await network.provider.send("evm_mine", []);
  }
}
'''
new_mining = '''async function mineBlocks(count) {
  try {
    await network.provider.send("anvil_mine", [ethers.toQuantity(count)]);
    return;
  } catch (error) {
    console.log(`V15_STAGE batch-mine-fallback count=${count} reason=${error.shortMessage || error.message}`);
  }
  for (let i = 0; i < count; i += 1) {
    await network.provider.send("evm_mine", []);
  }
}
'''

old_auction = '''async function runSolverAuction({ auction, coordinator, treasury, solvers, solutionHash, tokenMid, label }) {
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
'''

new_auction = '''async function runSolverAuction({ auction, coordinator, treasury, solvers, solutionHash, tokenMid, label }) {
  console.log(`V15_STAGE auction-${label}-align-start block=${await ethers.provider.getBlockNumber()}`);
  await mineToNextEpochStart();
  console.log(`V15_STAGE auction-${label}-aligned block=${await ethers.provider.getBlockNumber()}`);
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
  console.log(`V15_STAGE auction-${label}-published epoch=${epoch}`);

  const bids = [E("0.10"), E("0.20"), E("0.30")];
  for (let i = 0; i < solvers.length; i += 1) {
    receipts.push(await (await auction.connect(solvers[i]).bid(solutionHash, { value: bids[i] })).wait());
    console.log(`V15_STAGE auction-${label}-bid index=${i} amount=${bids[i]}`);
  }
  const expectedWinner = solvers[2];
  const nativeBefore = await ethers.provider.getBalance(treasury.address);
  console.log(`V15_STAGE auction-${label}-settlement-align-start block=${await ethers.provider.getBlockNumber()}`);
  await mineToNextEpochStart();
  console.log(`V15_STAGE auction-${label}-settlement-aligned block=${await ethers.provider.getBlockNumber()}`);
  receipts.push(await (await auction.connect(coordinator).settle(epoch)).wait());
  console.log(`V15_STAGE auction-${label}-settled epoch=${epoch}`);
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
'''

for old, new in ((old_mining, new_mining), (old_auction, new_auction)):
    if old not in text:
        raise SystemExit(f"required V15 mining/auction fragment not found: {old[:120]!r}")
    text = text.replace(old, new, 1)

path.write_text(text, encoding="utf-8")
print("patched V15 batch mining and auction stage diagnostics")
