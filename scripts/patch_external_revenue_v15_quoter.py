#!/usr/bin/env python3
"""Patch the V15 fork test to use the deployed Uniswap V3 Quoter for screening."""
from pathlib import Path

path = Path("test/external_revenue_v15_polygon_fork.js")
text = path.read_text(encoding="utf-8")

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
    (
        'async function findBackrunCandidate({ qsRouter, uniRouter, shocker, solver, venue, shockerBalance, solverBalance }) {',
        'async function findBackrunCandidate({ qsRouter, uniQuoter, shocker, venue, shockerBalance, solverBalance }) {',
    ),
    (
        '          const midOut = await quoteUniV3(uniRouter, solver, venue.tokenMid, venue.fee, amountIn);',
        '          const midOut = await quoteUniV3(uniQuoter, venue.tokenMid, venue.fee, amountIn);',
    ),
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
        '      uniRouter,\n'
        '      shocker,\n'
        '      solver: solver3,',
        '      uniQuoter,\n'
        '      shocker,',
    ),
]

for old, new in replacements:
    if old not in text:
        raise SystemExit(f"required V15 source fragment not found: {old[:100]!r}")
    text = text.replace(old, new, 1)

path.write_text(text, encoding="utf-8")
print("patched V15 screening to use Uniswap V3 Quoter")
