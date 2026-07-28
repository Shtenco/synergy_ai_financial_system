const { ethers } = require("ethers");

const ABI = [
  "event AuctionAnnounced(uint256 indexed epoch,address indexed settlement,address indexed loanToken,uint256 maxNotional,uint256 minProfit,uint256 closeBlock,bytes32 venuesHash,string metadataURI)",
  "event BidPlaced(uint256 indexed epoch,address indexed solver,uint256 amount,bytes32 solutionHash)",
  "event Settled(uint256 indexed epoch,address indexed solver,uint256 revenue,bytes32 solutionHash)",
];

async function main() {
  const rpc = process.env.POLYGON_RPC_URL;
  const address = process.env.AUCTION_ADDRESS;
  if (!rpc || !address) throw new Error("set POLYGON_RPC_URL and AUCTION_ADDRESS");
  const provider = new ethers.JsonRpcProvider(rpc, 137);
  const auction = new ethers.Contract(address, ABI, provider);
  const latest = await provider.getBlockNumber();
  const events = await auction.queryFilter(auction.filters.AuctionAnnounced(), Math.max(0, latest - 5_000), latest);
  for (const event of events) print(event);
  auction.on("AuctionAnnounced", (...args) => print(args.at(-1)));
  console.error(`watching Polygon auction ${address} from block ${latest}`);
}

function print(event) {
  const a = event.args;
  process.stdout.write(`${JSON.stringify({
    chainId: 137,
    auction: event.address,
    blockNumber: event.blockNumber,
    transactionHash: event.transactionHash,
    epoch: a.epoch.toString(),
    settlement: a.settlement,
    loanToken: a.loanToken,
    maxNotional: a.maxNotional.toString(),
    minProfit: a.minProfit.toString(),
    closeBlock: a.closeBlock.toString(),
    venuesHash: a.venuesHash,
    metadataURI: a.metadataURI,
  })}\n`);
}

main().catch((error) => { console.error(error); process.exitCode = 1; });
