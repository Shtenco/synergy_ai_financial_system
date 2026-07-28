const { ethers } = require("hardhat");

async function main() {
  const treasury = process.env.TREASURY_ADDRESS;
  const coordinator = process.env.COORDINATOR_ADDRESS;
  if (!treasury || !coordinator) throw new Error("set TREASURY_ADDRESS and COORDINATOR_ADDRESS");
  const factory = await ethers.getContractFactory("OrderflowAuction");
  const auction = await factory.deploy(treasury, coordinator);
  await auction.waitForDeployment();
  const network = await ethers.provider.getNetwork();
  console.log(JSON.stringify({
    chainId: network.chainId.toString(),
    auctionAddress: await auction.getAddress(),
    treasury,
    coordinator,
    deploymentTransaction: auction.deploymentTransaction().hash,
  }, null, 2));
}

main().catch((error) => { console.error(error); process.exitCode = 1; });
