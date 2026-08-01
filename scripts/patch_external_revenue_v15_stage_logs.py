#!/usr/bin/env python3
"""Insert durable stage markers into the generated V15 fork test."""
from pathlib import Path

path = Path("test/external_revenue_v15_polygon_fork.js")
text = path.read_text(encoding="utf-8")

replacements = [
    (
        "    assert.equal(networkInfo.chainId, CHAIN_ID);\n",
        "    assert.equal(networkInfo.chainId, CHAIN_ID);\n"
        "    console.log(`V15_STAGE chain-ready block=${await ethers.provider.getBlockNumber()}`);\n",
    ),
    (
        "    const venue = await selectRealMultiDexVenue(qsFactory, uniFactory, uniQuoter);\n",
        "    console.log(\"V15_STAGE venue-discovery-start\");\n"
        "    const venue = await selectRealMultiDexVenue(qsFactory, uniFactory, uniQuoter);\n"
        "    console.log(`V15_STAGE venue-selected mid=${venue.tokenMid} fee=${venue.fee} v3=${venue.sourcePool} v2=${venue.targetPair} v2Usdc=${venue.targetUsdc}`);\n",
    ),
    (
        "    await (await usdc.connect(shocker).approve(QS_V2_ROUTER, ethers.MaxUint256)).wait();\n",
        "    console.log(`V15_STAGE accounts-funded shock=${shockFunding} solver=${solverFunding} donor=${usdcDonor.pair}`);\n"
        "    await (await usdc.connect(shocker).approve(QS_V2_ROUTER, ethers.MaxUint256)).wait();\n",
    ),
    (
        "    await (await auction.connect(treasury).setConsumer(await engine.getAddress())).wait();\n",
        "    await (await auction.connect(treasury).setConsumer(await engine.getAddress())).wait();\n"
        "    console.log(`V15_STAGE contracts-deployed auction=${await auction.getAddress()} rfq=${await rfq.getAddress()} engine=${await engine.getAddress()}`);\n",
    ),
    (
        "    const candidate = await findBackrunCandidate({\n",
        "    console.log(\"V15_STAGE public-screen-start\");\n"
        "    const candidate = await findBackrunCandidate({\n",
    ),
    (
        "    const minMidOut = candidate.midOut * 999n / 1000n;\n",
        "    console.log(`V15_STAGE public-candidate shock=${candidate.shockAmount} principal=${candidate.amountIn} edgePpm=${candidate.edgePpm} revenue=${candidate.revenue}`);\n"
        "    const minMidOut = candidate.midOut * 999n / 1000n;\n",
    ),
    (
        "    const treasuryUsdcBeforePublic = await usdc.balanceOf(treasury.address);\n",
        "    console.log(`V15_STAGE public-auction-settled epoch=${publicAuction.epoch} winner=${publicAuction.winner.address}`);\n"
        "    const treasuryUsdcBeforePublic = await usdc.balanceOf(treasury.address);\n",
    ),
    (
        "    const publicRevenue = (await usdc.balanceOf(treasury.address)) - treasuryUsdcBeforePublic;\n",
        "    console.log(`V15_STAGE same-block-executed block=${publicReceipt.blockNumber} victimIndex=${txIndex(victimReceipt)} backrunIndex=${txIndex(publicReceipt)}`);\n"
        "    const publicRevenue = (await usdc.balanceOf(treasury.address)) - treasuryUsdcBeforePublic;\n",
    ),
    (
        "    const rfqPrincipal = minBig(candidate.amountIn, U(\"2500\"));\n",
        "    console.log(`V15_STAGE public-revenue revenue=${publicRevenue} edgePpm=${publicEdgePpm}`);\n"
        "    const rfqPrincipal = minBig(candidate.amountIn, U(\"2500\"));\n",
    ),
    (
        "    const rfqAuction = await runSolverAuction({\n",
        "    console.log(`V15_STAGE rfq-selected maker=${selected.order.maker} output=${selected.order.amountOut} expectedFinal=${selected.expectedFinalOut}`);\n"
        "    const rfqAuction = await runSolverAuction({\n",
    ),
    (
        "    const rfqRevenue = (await usdc.balanceOf(treasury.address)) - treasuryUsdcBeforeRfq;\n",
        "    console.log(`V15_STAGE rfq-executed tx=${rfqReceipt.hash}`);\n"
        "    const rfqRevenue = (await usdc.balanceOf(treasury.address)) - treasuryUsdcBeforeRfq;\n",
    ),
    (
        "    const auctionRevenueWei = publicAuction.winningBidWei + rfqAuction.winningBidWei;\n",
        "    console.log(`V15_STAGE rfq-revenue revenue=${rfqRevenue} edgePpm=${rfqEdgePpm}`);\n"
        "    const auctionRevenueWei = publicAuction.winningBidWei + rfqAuction.winningBidWei;\n",
    ),
    (
        "    const totalRevenueUsdc = publicRevenue + rfqRevenue + auctionRevenueUsdc;\n",
        "    console.log(`V15_STAGE gas-accounted gasUsdc=${allActorGasUsdc} auctionRevenueUsdc=${auctionRevenueUsdc}`);\n"
        "    const totalRevenueUsdc = publicRevenue + rfqRevenue + auctionRevenueUsdc;\n",
    ),
    (
        "    const usdcSupply = await usdc.totalSupply();\n",
        "    console.log(`V15_STAGE final net=${netAfterAllActorGasUsdc} aggregateEdgePpm=${aggregateNetEdgePpm}`);\n"
        "    const usdcSupply = await usdc.totalSupply();\n",
    ),
]

for old, new in replacements:
    if old not in text:
        raise SystemExit(f"required V15 stage fragment not found: {old!r}")
    text = text.replace(old, new, 1)

path.write_text(text, encoding="utf-8")
print("inserted V15 stage markers")
