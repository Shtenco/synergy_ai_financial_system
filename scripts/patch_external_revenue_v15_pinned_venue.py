#!/usr/bin/env python3
"""Pin the real V15 venue and USDC donor already discovered on block 91,266,308."""
from pathlib import Path

path = Path("test/external_revenue_v15_polygon_fork.js")
text = path.read_text(encoding="utf-8")

old_venue = '''    console.log("V15_STAGE venue-discovery-start");
    const venue = await selectRealMultiDexVenue(qsFactory, uniFactory, uniQuoter);
    console.log(`V15_STAGE venue-selected mid=${venue.tokenMid} fee=${venue.fee} v3=${venue.sourcePool} v2=${venue.targetPair} v2Usdc=${venue.targetUsdc}`);
'''
new_venue = '''    console.log("V15_STAGE venue-pinned-real-fork-state");
    const venue = {
      tokenMid: WPOL,
      fee: 100,
      targetPair: "0x6e7a5FAFcec6BB1e78bAE2A1F0B612012BF14827",
      sourcePool: "0x0a6c4588b7D8Bd22cF120283B1FFf953420c45F3",
      targetUsdc: await usdc.balanceOf("0x6e7a5FAFcec6BB1e78bAE2A1F0B612012BF14827"),
      targetMid: await wpol.balanceOf("0x6e7a5FAFcec6BB1e78bAE2A1F0B612012BF14827"),
      sourceUsdc: await usdc.balanceOf("0x0a6c4588b7D8Bd22cF120283B1FFf953420c45F3"),
      sourceMid: await wpol.balanceOf("0x0a6c4588b7D8Bd22cF120283B1FFf953420c45F3")
    };
    assert.notEqual(await ethers.provider.getCode(venue.targetPair), "0x");
    assert.notEqual(await ethers.provider.getCode(venue.sourcePool), "0x");
    assert.ok(venue.targetUsdc > 0n && venue.targetMid > 0n);
    assert.ok(venue.sourceUsdc > 0n && venue.sourceMid > 0n);
    const discoveredV2 = await qsFactory.getPair(USDC, WPOL);
    const discoveredV3 = await uniFactory.getPool(USDC, WPOL, 100);
    assert.equal(discoveredV2.toLowerCase(), venue.targetPair.toLowerCase());
    assert.equal(discoveredV3.toLowerCase(), venue.sourcePool.toLowerCase());
    console.log(`V15_STAGE venue-confirmed mid=${venue.tokenMid} fee=${venue.fee} v3=${venue.sourcePool} v2=${venue.targetPair} v2Usdc=${venue.targetUsdc}`);
'''

old_donor = '''    const usdcDonor = await findV2Donor(
      qsFactory,
      USDC,
      [USDT, DAI, WETH, WPOL],
      [venue.targetPair],
      U("10000")
    );
'''
new_donor = '''    const usdcDonor = {
      pair: "0x853Ee4b2A13f8a742d64C8F088bE7bA2131f670d",
      balance: await usdc.balanceOf("0x853Ee4b2A13f8a742d64C8F088bE7bA2131f670d"),
      other: WETH
    };
    assert.notEqual(await ethers.provider.getCode(usdcDonor.pair), "0x");
    assert.ok(usdcDonor.balance >= U("10000"));
'''

for old, new in ((old_venue, new_venue), (old_donor, new_donor)):
    if old not in text:
        raise SystemExit(f"required generated V15 fragment not found: {old[:160]!r}")
    text = text.replace(old, new, 1)

path.write_text(text, encoding="utf-8")
print("pinned and re-verified the real V15 USDC/WPOL fork venue and USDC donor")
