const { ethers, network } = require("hardhat");

const ADDRESSES = {
  SYNA: "0xaeB98101e29E791A2482C2A5B55F444F6C9E44a4",
  SYNR: "0xe3e6944BcE4A92648B37f6F578600b0D0288E935",
  SYNA_WPOL: "0xDC0B1C37F37243f70C41453F101Db1bE6DC78341",
  SYNR_WPOL: "0xf1dD54F9c999f17020228c8938033Cb2D913f2FB",
  WPOL: "0x0d500B1d8E8eF31E21C99d1Db9A6444d3ADf1270",
  ROUTER: "0xa5E0829CaCEd8fFDD4De3c43696c57F7D7A678ff",
  FACTORY: "0x5757371414417b8C6CAad45bAeF941aBc7d3Ab32",
};

async function main() {
  if (!process.env.POLYGON_RPC_URL || process.env.FORK_BLOCK_NUMBER !== "60000000") {
    throw new Error("set archival POLYGON_RPC_URL and FORK_BLOCK_NUMBER=60000000");
  }
  for (const [name, address] of Object.entries(ADDRESSES)) {
    const code = await ethers.provider.getCode(address);
    if (code === "0x") throw new Error(`${name} has no code at fork block`);
  }
  const pairAbi = ["function token0() view returns(address)", "function token1() view returns(address)",
    "function getReserves() view returns(uint112,uint112,uint32)"];
  for (const pairAddress of [ADDRESSES.SYNA_WPOL, ADDRESSES.SYNR_WPOL]) {
    const pair = new ethers.Contract(pairAddress, pairAbi, ethers.provider);
    const [token0, token1, reserves] = await Promise.all([pair.token0(), pair.token1(), pair.getReserves()]);
    if (reserves[0] === 0n || reserves[1] === 0n) throw new Error(`empty pair ${pairAddress}`);
    if (token0.toLowerCase() !== ADDRESSES.WPOL.toLowerCase() && token1.toLowerCase() !== ADDRESSES.WPOL.toLowerCase()) {
      throw new Error(`WPOL missing from pair ${pairAddress}`);
    }
    console.log(JSON.stringify({ pair: pairAddress, token0, token1,
      reserve0: reserves[0].toString(), reserve1: reserves[1].toString() }));
  }
  console.log(`fork preflight passed at ${await ethers.provider.getBlockNumber()} on ${network.name}`);
}

main().catch((error) => { console.error(error); process.exitCode = 1; });
