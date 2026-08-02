#!/usr/bin/env python3
"""Create an importable copy of the V9/V10 Polygon pool reader.

The original scanner remains executable. V13 imports the discovery, historical
pool-state, graph and exact-quote helpers without duplicating the RPC code.
"""
from pathlib import Path

SOURCE = Path("scripts/scan_polygon_50_pool_100_blocks.js")
TARGET = Path("scripts/_polygon_scanner_lib_v13.js")

text = SOURCE.read_text(encoding="utf-8")
needle = '''main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
'''
replacement = '''module.exports = {
  ethers,
  provider,
  TOKENS,
  retry,
  mapLimit,
  rawToNumber,
  numberToRaw,
  cpAmountOut,
  cpAmountIn,
  poolKey,
  discoverPools,
  readPoolState,
  deriveTokenPrices,
  rankPools,
  buildEdges,
  screeningRouteQuote,
  exactRouteQuote,
  routeLabel,
};

if (require.main === module) {
  main().catch((error) => {
    console.error(error);
    process.exitCode = 1;
  });
}
'''
if needle not in text:
    raise SystemExit("scanner main tail not found")
TARGET.write_text(text.replace(needle, replacement), encoding="utf-8")
