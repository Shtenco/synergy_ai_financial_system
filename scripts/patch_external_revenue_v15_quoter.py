#!/usr/bin/env python3
"""Patch V15 screening to combine V3 Quoter outputs with exact local V2 math."""
from pathlib import Path

path = Path("test/external_revenue_v15_polygon_fork.js")
text = path.read_text(encoding="utf-8")

old_search = '''async function findBackrunCandidate({ qsRouter, uniRouter, shocker, solver, venue, shockerBalance, solverBalance }) {
  const shockFractionsBps = [250n, 500n, 1000n, 2000n, 3000n];
  const tradeFractionsBps = [2n, 5n, 10n, 20n, 50n, 100n];
  let best = null;

  for (const shockBps of shockFractionsBps) {
    const shockAmount = minBig(venue.targetUsdc * shockBps / 10000n, shockerBalance * 95n / 100n);
    if (shockAmount < U("100")) continue;
    const snapshot = await network.provider.send("evm_snapshot", []);
    try {
      const block = await ethers.provider.getBlock("latest");
      await (
        await qsRouter.connect(shocker).swapExactTokensForTokens(
          shockAmount,
          1n,
          [USDC, venue.tokenMid],
          shocker.address,
          BigInt(block.timestamp + 3600)
        )
      ).wait();

      for (const tradeBps of tradeFractionsBps) {
        const amountIn = minBig(venue.targetUsdc * tradeBps / 10000n, solverBalance * 80n / 100n);
        if (amountIn < U("50")) continue;
        try {
          const midOut = await quoteUniV3(uniRouter, solver, venue.tokenMid, venue.fee, amountIn);
          const final = await qsRouter.getAmountsOut(midOut, [venue.tokenMid, USDC]);
          const finalOut = final[1];
          if (finalOut <= amountIn) continue;
          const revenue = finalOut - amountIn;
          const edgePpm = revenue * 1_000_000n / amountIn;
          const record = { shockAmount, amountIn, midOut, finalOut, revenue, edgePpm };
          if (!best || record.revenue > best.revenue) best = record;
        } catch (_) {
          // Unsupported fee/liquidity at this size.
        }
      }
    } finally {
      await network.provider.send("evm_revert", [snapshot]);
    }
  }

  if (!best || best.edgePpm < 1500n) {
    throw new Error(`No robust public backrun candidate; best=${best ? best.edgePpm : 0} ppm`);
  }
  return best;
}
'''

new_search = '''function cpOut(amountIn, reserveIn, reserveOut, feeBps = 30n) {
  if (amountIn <= 0n || reserveIn <= 0n || reserveOut <= 0n) return 0n;
  const amountInWithFee = amountIn * (10000n - feeBps);
  return amountInWithFee * reserveOut / (reserveIn * 10000n + amountInWithFee);
}

async function findBackrunCandidate({ uniQuoter, venue, shockerBalance, solverBalance }) {
  const shockFractionsBps = [1000n, 2500n, 5000n, 10000n, 20000n, 50000n];
  const tradeFractionsBps = [1n, 2n, 5n, 10n, 20n, 50n, 100n, 200n, 500n];
  const reserves = await pairReserves(venue.targetPair, USDC, venue.tokenMid);
  const quotedTrades = [];
  let quoteFailures = 0;

  for (const tradeBps of tradeFractionsBps) {
    const amountIn = minBig(reserves.reserveA * tradeBps / 10000n, solverBalance * 80n / 100n);
    if (amountIn < U("10")) continue;
    try {
      const midOut = await quoteUniV3(uniQuoter, venue.tokenMid, venue.fee, amountIn);
      if (midOut > 0n) quotedTrades.push({ amountIn, midOut, tradeBps });
    } catch (_) {
      quoteFailures += 1;
    }
  }

  let best = null;
  for (const shockBps of shockFractionsBps) {
    const shockAmount = minBig(reserves.reserveA * shockBps / 10000n, shockerBalance * 95n / 100n);
    if (shockAmount < U("100")) continue;
    const victimMidOut = cpOut(shockAmount, reserves.reserveA, reserves.reserveB, 30n);
    if (victimMidOut <= 0n || victimMidOut >= reserves.reserveB) continue;
    const postUsdc = reserves.reserveA + shockAmount;
    const postMid = reserves.reserveB - victimMidOut;

    for (const quoted of quotedTrades) {
      const finalOut = cpOut(quoted.midOut, postMid, postUsdc, 30n);
      if (finalOut <= quoted.amountIn) continue;
      const revenue = finalOut - quoted.amountIn;
      const edgePpm = revenue * 1_000_000n / quoted.amountIn;
      const record = {
        shockAmount,
        amountIn: quoted.amountIn,
        midOut: quoted.midOut,
        finalOut,
        revenue,
        edgePpm,
        shockBps,
        tradeBps: quoted.tradeBps,
        victimMidOut,
        postVictimUsdcReserve: postUsdc,
        postVictimMidReserve: postMid,
        quoterCalls: quotedTrades.length,
        quoterFailures: quoteFailures,
      };
      if (!best || record.revenue > best.revenue) best = record;
    }
  }

  if (!best || best.edgePpm < 1500n) {
    throw new Error(
      `No robust public backrun candidate; best=${best ? best.edgePpm : 0} ppm; `
      + `quotedTrades=${quotedTrades.length}; quoteFailures=${quoteFailures}`
    );
  }
  return best;
}
'''

replacements = [
    (
        'const UNI_V3_ROUTER = "0xE592427A0AEce92De3Edee1F18E0157C05861564";\n',
        'const UNI_V3_ROUTER = "0xE592427A0AEce92De3Edee1F18E0157C05861564";\n'
        'const UNI_V3_QUOTER = "0xb27308f9F90D607463bb33eA1BeBb41C27CE5AB6";\n',
    ),
    (
        'const V3_ROUTER_ABI = [\n'
        '  "function exactInputSingle((address tokenIn,address tokenOut,uint24 fee,address recipient,uint256 deadline,uint256 amountIn,uint256 amountOutMinimum,uint160 sqrtPriceLimitX96) params) payable returns(uint256 amountOut)"\n'
        '];\n',
        'const V3_ROUTER_ABI = [\n'
        '  "function exactInputSingle((address tokenIn,address tokenOut,uint24 fee,address recipient,uint256 deadline,uint256 amountIn,uint256 amountOutMinimum,uint160 sqrtPriceLimitX96) params) payable returns(uint256 amountOut)"\n'
        '];\n'
        'const V3_QUOTER_ABI = [\n'
        '  "function quoteExactInputSingle(address,address,uint24,uint256,uint160) returns(uint256 amountOut)"\n'
        '];\n',
    ),
    (
        'async function selectRealMultiDexVenue(qsFactory, uniFactory) {',
        'async function selectRealMultiDexVenue(qsFactory, uniFactory, uniQuoter) {',
    ),
    (
        '    if (targetUsdc === 0n || targetMid === 0n) continue;',
        '    if (targetUsdc < U("10000") || targetMid === 0n) continue;',
    ),
    (
        '      if (sourceUsdc === 0n || sourceMid === 0n) continue;\n'
        '      candidates.push({',
        '      if (sourceUsdc === 0n || sourceMid === 0n) continue;\n'
        '      try {\n'
        '        const probe = await quoteUniV3(uniQuoter, tokenMid, fee, U("10"));\n'
        '        if (probe <= 0n) continue;\n'
        '      } catch (_) {\n'
        '        continue;\n'
        '      }\n'
        '      candidates.push({',
    ),
    (
        '  candidates.sort((a, b) => (a.targetUsdc > b.targetUsdc ? -1 : a.targetUsdc < b.targetUsdc ? 1 : 0));',
        '  candidates.sort((a, b) => (a.targetUsdc < b.targetUsdc ? -1 : a.targetUsdc > b.targetUsdc ? 1 : 0));',
    ),
    (
        'async function quoteUniV3(router, signer, tokenMid, fee, amountIn) {\n'
        '  const block = await ethers.provider.getBlock("latest");\n'
        '  const params = {\n'
        '    tokenIn: USDC,\n'
        '    tokenOut: tokenMid,\n'
        '    fee,\n'
        '    recipient: signer.address,\n'
        '    deadline: BigInt(block.timestamp + 3600),\n'
        '    amountIn,\n'
        '    amountOutMinimum: 0n,\n'
        '    sqrtPriceLimitX96: 0n\n'
        '  };\n'
        '  return router.connect(signer).exactInputSingle.staticCall(params);\n'
        '}\n',
        'async function quoteUniV3(quoter, tokenMid, fee, amountIn) {\n'
        '  return quoter.quoteExactInputSingle.staticCall(USDC, tokenMid, fee, amountIn, 0);\n'
        '}\n',
    ),
    (old_search, new_search),
    (
        'for (const address of [WPOL, USDC, QS_V2_FACTORY, QS_V2_ROUTER, UNI_V3_FACTORY, UNI_V3_ROUTER]) {',
        'for (const address of [WPOL, USDC, QS_V2_FACTORY, QS_V2_ROUTER, UNI_V3_FACTORY, UNI_V3_ROUTER, UNI_V3_QUOTER]) {',
    ),
    (
        '    const uniRouter = new ethers.Contract(UNI_V3_ROUTER, V3_ROUTER_ABI, coordinator);\n\n'
        '    const venue = await selectRealMultiDexVenue(qsFactory, uniFactory);',
        '    const uniRouter = new ethers.Contract(UNI_V3_ROUTER, V3_ROUTER_ABI, coordinator);\n'
        '    const uniQuoter = new ethers.Contract(UNI_V3_QUOTER, V3_QUOTER_ABI, coordinator);\n\n'
        '    const venue = await selectRealMultiDexVenue(qsFactory, uniFactory, uniQuoter);',
    ),
    (
        '    const shockFunding = minBig(venue.targetUsdc * 35n / 100n, usdcDonor.balance * 35n / 100n);\n'
        '    const solverFunding = minBig(venue.targetUsdc * 3n / 100n, usdcDonor.balance * 8n / 100n);',
        '    const shockFunding = minBig(venue.targetUsdc * 6n, usdcDonor.balance * 60n / 100n);\n'
        '    const solverFunding = minBig(venue.targetUsdc * 10n / 100n, usdcDonor.balance * 10n / 100n);',
    ),
    (
        '    const candidate = await findBackrunCandidate({\n'
        '      qsRouter,\n'
        '      uniRouter,\n'
        '      shocker,\n'
        '      solver: solver3,\n'
        '      venue,',
        '    const candidate = await findBackrunCandidate({\n'
        '      uniQuoter,\n'
        '      venue,',
    ),
]

for old, new in replacements:
    if old not in text:
        raise SystemExit(f"required V15 source fragment not found: {old[:140]!r}")
    text = text.replace(old, new, 1)

path.write_text(text, encoding="utf-8")
print("patched V15 screening with one-shot V3 quotes and exact local V2 math")
