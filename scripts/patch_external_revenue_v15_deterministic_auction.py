#!/usr/bin/env python3
"""Use the deterministic funded V15 auction instead of long fork block epochs."""
from pathlib import Path
import re

path = Path("test/external_revenue_v15_polygon_fork.js")
text = path.read_text(encoding="utf-8")

text = text.replace(
    'const Auction = await ethers.getContractFactory("OrderflowAuction", coordinator);',
    'const Auction = await ethers.getContractFactory("OrderflowAuctionV15", coordinator);',
    1,
)

pattern = re.compile(
    r'async function runSolverAuction\(\{ auction, coordinator, treasury, solvers, solutionHash, tokenMid, label \}\) \{.*?\n\}\n\nfunction txIndex',
    re.DOTALL,
)
replacement = '''async function runSolverAuction({ auction, coordinator, treasury, solvers, solutionHash, tokenMid, label }) {
  const epoch = await auction.currentEpoch();
  const venuesHash = ethers.keccak256(ethers.toUtf8Bytes(`UNISWAP_V3|QUICKSWAP_V2|PRIVATE_RFQ|${label}`));
  const receipts = [];
  console.log(`V15_STAGE auction-${label}-publish epoch=${epoch} block=${await ethers.provider.getBlockNumber()}`);
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
    console.log(`V15_STAGE auction-${label}-bid index=${i} amount=${bids[i]}`);
  }

  const expectedWinner = solvers[2];
  const nativeBefore = await ethers.provider.getBalance(treasury.address);
  receipts.push(await (await auction.connect(coordinator).settle(epoch)).wait());
  const nativeAfter = await ethers.provider.getBalance(treasury.address);
  const winning = await auction.best(epoch);
  assert.equal(winning[0].toLowerCase(), expectedWinner.address.toLowerCase());
  assert.equal(winning[2], solutionHash);
  assert.equal(winning[3], true);
  assert.equal(await auction.bidCount(epoch), 3n);
  assert.equal(nativeAfter - nativeBefore, bids[2]);
  console.log(`V15_STAGE auction-${label}-settled epoch=${epoch} winner=${expectedWinner.address}`);
  return {
    epoch,
    winner: expectedWinner,
    winningBidWei: bids[2],
    receipts,
    venuesHash
  };
}

function txIndex'''

text, count = pattern.subn(replacement, text, count=1)
if count != 1:
    raise SystemExit("failed to replace V15 solver auction function")
if 'getContractFactory("OrderflowAuctionV15"' not in text:
    raise SystemExit("failed to switch V15 auction contract")

path.write_text(text, encoding="utf-8")
print("patched V15 to deterministic funded three-solver auction")
