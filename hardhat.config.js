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

const publicForkUrl = process.env.POLYGON_RPC_URL || "";
const privatePolygonUrl = process.env.PRIVATE_POLYGON_RPC_URL || "";
const blockNumber = process.env.FORK_BLOCK_NUMBER
  ? Number(process.env.FORK_BLOCK_NUMBER)
  : undefined;

module.exports = {
  solidity: {
    version: "0.8.26",
    settings: {
      optimizer: { enabled: true, runs: 500 },
      viaIR: true,
      evmVersion: "paris",
      metadata: { bytecodeHash: "none" }
    }
  },
  networks: {
    hardhat: {
      chainId: 31337,
      forking: publicForkUrl ? { url: publicForkUrl, blockNumber } : undefined,
      accounts: { count: 20, accountsBalance: "100000000000000000000000" }
    },
    polygon: {
      chainId: 137,
      // Mainnet execution must use PRIVATE_POLYGON_RPC_URL. POLYGON_RPC_URL remains
      // a public/read-only fallback for pinned local forks and dry diagnostics.
      url: privatePolygonUrl || publicForkUrl || "http://127.0.0.1:8545",
      accounts: process.env.OWNER_PRIVATE_KEY ? [process.env.OWNER_PRIVATE_KEY] : []
    }
  },
  mocha: { timeout: 600000 }
};
