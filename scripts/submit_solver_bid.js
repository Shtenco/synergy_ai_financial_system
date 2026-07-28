const { ethers } = require("ethers");

const ABI = ["function bid(bytes32 solutionHash) payable"];

async function main() {
  const { POLYGON_RPC_URL: rpc, AUCTION_ADDRESS: address, SOLVER_PRIVATE_KEY: key,
    ROUTE_DATA: routeData, BID_POL: bidPol } = process.env;
  if (!rpc || !address || !key || !routeData || !bidPol) {
    throw new Error("set POLYGON_RPC_URL, AUCTION_ADDRESS, SOLVER_PRIVATE_KEY, ROUTE_DATA, BID_POL");
  }
  const provider = new ethers.JsonRpcProvider(rpc, 137);
  const wallet = new ethers.Wallet(key, provider);
  const auction = new ethers.Contract(address, ABI, wallet);
  const solutionHash = ethers.keccak256(routeData);
  const transaction = await auction.bid(solutionHash, { value: ethers.parseEther(bidPol) });
  console.log(JSON.stringify({ transactionHash: transaction.hash, solutionHash }));
  await transaction.wait();
}

main().catch((error) => { console.error(error); process.exitCode = 1; });
