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
const localForkUrl = process.env.LOCAL_FORK_URL || "http://127.0.0.1:8545";
const anvilMnemonic = "test test test test test test test test test test test junk";

module.exports = {
  solidity: {
    version: "0.8.26",
    settings: {
      optimizer: { enabled: true, runs: 500 },
      viaIR: true,
      evmVersion: "cancun"
    }
  },
  networks: {
    hardhat: {
      chainId: 31337,
      hardfork: "cancun",
      chains: {
        137: {
          hardforkHistory: {
            cancun: 0
          }
        }
      },
      forking: forkUrl ? { url: forkUrl, blockNumber } : undefined,
      accounts: { count: 20, accountsBalance: "100000000000000000000000" }
    },
    polygonFork: {
      chainId: 137,
      url: localForkUrl,
      accounts: {
        mnemonic: anvilMnemonic,
        count: 20
      }
    },
    polygon: {
      chainId: 137,
      url: forkUrl || "http://127.0.0.1:8545",
      accounts: process.env.OWNER_PRIVATE_KEY ? [process.env.OWNER_PRIVATE_KEY] : []
    }
  },
  mocha: { timeout: 240000 }
};
