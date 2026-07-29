const { subtask } = require("hardhat/config");
const { TASK_COMPILE_SOLIDITY_GET_SOLC_BUILD } = require("hardhat/builtin-tasks/task-names");

subtask(TASK_COMPILE_SOLIDITY_GET_SOLC_BUILD).setAction(async ({ solcVersion }) => ({
  compilerPath: require.resolve("solc/soljson.js"),
  isSolcJs: true,
  version: solcVersion,
  longVersion: require("solc").version(),
}));

require("@nomicfoundation/hardhat-ethers");
require("dotenv").config();

const forkUrl = process.env.POLYGON_RPC_URL || "";
const blockNumber = process.env.FORK_BLOCK_NUMBER
  ? Number(process.env.FORK_BLOCK_NUMBER)
  : undefined;

module.exports = {
  solidity: {
    version: "0.8.26",
    settings: {
      optimizer: { enabled: true, runs: 500 },
      viaIR: true,
      evmVersion: "paris"
    }
  },
  networks: {
    hardhat: {
      chainId: 31337,
      hardfork: "shanghai",
      // Hardhat/EDR doesn't ship a Polygon PoS activation history.
      // The pinned fork state is executed under Shanghai; Cancun caused
      // ExcessBlobGasNotSet because Polygon block headers don't expose
      // Ethereum blob-gas fields.
      chains: {
        137: {
          hardforkHistory: {
            shanghai: 0
          }
        }
      },
      forking: forkUrl ? { url: forkUrl, blockNumber } : undefined,
      accounts: { count: 20, accountsBalance: "100000000000000000000000" }
    },
    polygon: {
      chainId: 137,
      url: forkUrl || "http://127.0.0.1:8545",
      accounts: process.env.OWNER_PRIVATE_KEY ? [process.env.OWNER_PRIVATE_KEY] : []
    }
  },
  mocha: { timeout: 120000 }
};
