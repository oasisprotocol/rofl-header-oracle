import type { HardhatUserConfig } from "hardhat/config";
import { config as loadEnv } from "dotenv";
loadEnv();

import hardhatToolboxMochaEthersPlugin from "@nomicfoundation/hardhat-toolbox-mocha-ethers";
import hardhatEthersPlugin from "@nomicfoundation/hardhat-ethers";
import { configVariable } from "hardhat/config";

// Import tasks
import {
  deployBlockHeaderRequester,
  requestBlockHeader,
  checkBlockRequested,
  deployRoflAdapter,
} from "./tasks/index.js";

const config: HardhatUserConfig = {
  plugins: [hardhatToolboxMochaEthersPlugin, hardhatEthersPlugin],
  tasks: [
    deployBlockHeaderRequester,
    requestBlockHeader,
    checkBlockRequested,
    deployRoflAdapter,
  ],
  solidity: {
    profiles: {
      default: {
        version: "0.8.24",
      },
      production: {
        version: "0.8.24",
        settings: {
          optimizer: {
            enabled: true,
            runs: 200,
          },
        },
      },
    },
  },
  networks: {
    hardhatMainnet: {
      type: "edr-simulated",
      chainType: "l1",
    },
    hardhatOp: {
      type: "edr-simulated",
      chainType: "op",
    },
    sepolia: {
      type: "http",
      chainType: "l1",
      url: configVariable("SEPOLIA_RPC_URL"),
      accounts: [configVariable("SEPOLIA_PRIVATE_KEY")],
    },
    sapphireTestnet: {
      type: "http",
      chainType: "l1",
      url: configVariable("SAPPHIRE_TESTNET_RPC_URL"),
      accounts: [configVariable("SAPPHIRE_PRIVATE_KEY")],
    },
    sapphireMainnet: {
      type: "http",
      chainType: "l1",
      url: configVariable("SAPPHIRE_MAINNET_RPC_URL"),
      accounts: [configVariable("SAPPHIRE_PRIVATE_KEY")],
    },
    base: {
      type: "http",
      chainType: "l1",
      url: configVariable("BASE_RPC_URL"),
      accounts: [configVariable("BASE_PRIVATE_KEY")],
    },
  },
};

export default config;
