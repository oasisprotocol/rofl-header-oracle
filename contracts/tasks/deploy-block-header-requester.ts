import { task } from "hardhat/config";
import { HardhatRuntimeEnvironment } from "hardhat/types";
import { saveDeploymentInfo } from "../utils/save-deployment.js";

// CreateX is deployed at the same address on all supported chains
const CREATEX_ADDRESS = "0xba5Ed099633D3B313e4D5F7bdc1305d3c28ba5Ed";

// Minimal ABI for CreateX deployCreate2
const CREATEX_ABI = [
  "function deployCreate2(bytes32 salt, bytes initCode) external payable returns (address)",
  "event ContractCreation(address indexed newContract, bytes32 indexed salt)",
];

export const deployBlockHeaderRequester = task("deploy:block-header-requester", "Deploy the BlockHeaderRequester contract using CreateX")
  .addFlag({
    name: "verify",
    description: "Verify contract on Etherscan",
  })
  .addOption({
    name: "salt",
    description: "Custom salt for CREATE2 (32 bytes hex).",
    defaultValue: "0x0000000000000000000000000000000000000000000000000000000000000000",
  })
  .setAction(async () => ({
    default: async (taskArgs: any, hre: HardhatRuntimeEnvironment) => {
      const { ethers } = await hre.network.connect();

      const networkName = hre.globalOptions.network || "hardhat";

      console.log("BlockHeaderRequester CreateX Deployment");
      console.log("Network:", networkName);

      const [deployer] = await ethers.getSigners();
      console.log("Deployer:", deployer.address);

      // Check CreateX exists on this network
      const createXCode = await ethers.provider.getCode(CREATEX_ADDRESS);
      if (createXCode === "0x") {
        throw new Error(`CreateX not deployed on ${networkName}. Address: ${CREATEX_ADDRESS}`);
      }

      const createX = new ethers.Contract(CREATEX_ADDRESS, CREATEX_ABI, deployer);

      // Get the contract bytecode (initCode)
      const BlockHeaderRequester = await ethers.getContractFactory("BlockHeaderRequester");
      const initCode = BlockHeaderRequester.bytecode;

      const salt = taskArgs.salt;
      console.log("Salt:", salt);

      const balance = await ethers.provider.getBalance(deployer.address);
      console.log("Account balance:", ethers.formatEther(balance), "ETH");

      console.log("\nDeploying via CreateX...");

      const tx = await createX["deployCreate2(bytes32,bytes)"](salt, initCode);

      console.log("Transaction hash:", tx.hash);
      console.log("Waiting for confirmation...");

      const receipt = await tx.wait(2);

      // Extract deployed address from ContractCreation event
      const creationEvent = receipt?.logs
        .map((log: any) => {
          try {
            return createX.interface.parseLog(log);
          } catch {
            return null;
          }
        })
        .find((parsed: any) => parsed?.name === "ContractCreation");

      if (!creationEvent?.args?.newContract) {
        throw new Error("ContractCreation event not found in receipt");
      }

      const contractAddress = creationEvent.args.newContract;

      // Verify deployment succeeded
      const deployedCode = await ethers.provider.getCode(contractAddress);
      if (deployedCode === "0x") {
        throw new Error(`Deployment failed - no code at ${contractAddress}`);
      }

      console.log("\n✅ BlockHeaderRequester deployed to:", contractAddress);

      if (taskArgs.verify && networkName !== "localhost" && networkName !== "hardhat") {
        console.log("\nVerifying contract on Etherscan...");
        try {
          await hre.run("verify:verify", {
            address: contractAddress,
            constructorArguments: [],
          });
          console.log("Contract verified successfully!");
        } catch (error: any) {
          if (error.message.includes("Already Verified")) {
            console.log("Contract is already verified!");
          } else {
            console.error("Error verifying contract:", error);
          }
        }
      } else if (taskArgs.verify) {
        console.log("Skipping verification on local network");
      }

      console.log("\n=== Deployment Summary ===");
      console.log("Network:", networkName);
      console.log("Contract Address:", contractAddress);
      console.log("Deployer:", deployer.address);
      console.log("Salt:", salt);
      console.log("CreateX:", CREATEX_ADDRESS);
      console.log("Block Number:", receipt?.blockNumber);
      console.log("==========================\n");

      await saveDeploymentInfo(
        "BlockHeaderRequester",
        contractAddress,
        hre,
        ethers,
        {
          transactionHash: tx.hash,
          constructorArgs: [],
          salt,
          createX: CREATEX_ADDRESS,
        }
      );

      return contractAddress;
    }
  }))
  .build();

export const requestBlockHeader = task("request:block-header", "Request a block header using the deployed contract")
  .addOption({
    name: "contract",
    description: "The BlockHeaderRequester contract address",
    defaultValue: "",
  })
  .addOption({
    name: "chainid",
    description: "The chain ID to request from (defaults to current network)",
    defaultValue: "",
  })
  .addOption({
    name: "blocknumber",
    description: "The block number to request (defaults to latest)",
    defaultValue: "",
  })
  .addOption({
    name: "context",
    description: "Optional context data (32 bytes)",
    defaultValue: "0x0000000000000000000000000000000000000000000000000000000000000000",
  })
  .setAction(async () => ({
    default: async (taskArgs: any, hre: HardhatRuntimeEnvironment) => {
      const { ethers } = await hre.network.connect();

      if (!taskArgs.contract) {
        throw new Error("Contract address is required. Use --contract <address>");
      }

      let chainId: bigint;
      if (taskArgs.chainid !== undefined && taskArgs.chainid !== "") {
        chainId = BigInt(taskArgs.chainid);
        console.log(`Using provided chain ID: ${chainId}`);
      } else {
        const network = await ethers.provider.getNetwork();
        chainId = network.chainId;
        console.log(`Using current network chain ID: ${chainId}`);
      }

      let blockNumber: bigint;
      if (taskArgs.blocknumber !== undefined && taskArgs.blocknumber !== "") {
        blockNumber = BigInt(taskArgs.blocknumber);
        console.log(`Using provided block number: ${blockNumber}`);
      } else {
        const latestBlockNumber = await ethers.provider.getBlockNumber();
        blockNumber = BigInt(latestBlockNumber);
        console.log(`Using latest block number: ${blockNumber}`);
      }

      console.log("\n=== Requesting Block Header ===");
      console.log("Contract:", taskArgs.contract);
      console.log("Chain ID:", chainId.toString());
      console.log("Block Number:", blockNumber.toString());
      console.log("Context:", taskArgs.context);

      const blockHeaderRequester = await ethers.getContractAt(
        "BlockHeaderRequester",
        taskArgs.contract
      );

      const isRequested = await blockHeaderRequester.isBlockRequested(
        chainId,
        blockNumber
      );

      if (isRequested) {
        console.log("⚠️  Block has already been requested!");
        return;
      }

      const tx = await blockHeaderRequester.requestBlockHeader(
        chainId,
        blockNumber,
        taskArgs.context
      );

      console.log("Transaction sent:", tx.hash);
      console.log("Waiting for confirmation...");

      const receipt = await tx.wait();
      console.log("Transaction confirmed in block:", receipt?.blockNumber);

      const event = receipt?.logs
        .map((log: any) => {
          try {
            return blockHeaderRequester.interface.parseLog(log);
          } catch {
            return null;
          }
        })
        .find((parsedLog: any) => parsedLog?.name === "BlockHeaderRequested");

      if (event) {
        console.log("\n✅ Block header requested successfully!");
        console.log("Event details:");
        console.log("  Chain ID:", event.args.chainId.toString());
        console.log("  Block Number:", event.args.blockNumber.toString());
        console.log("  Requester:", event.args.requester);
        console.log("  Context:", event.args.context);
      }
    }
  }))
  .build();

export const checkBlockRequested = task("check:block-requested", "Check if a block header was already requested")
  .addOption({
    name: "contract",
    description: "The BlockHeaderRequester contract address",
    defaultValue: "",
  })
  .addOption({
    name: "chainid",
    description: "The chain ID (defaults to current network)",
    defaultValue: "",
  })
  .addOption({
    name: "blocknumber",
    description: "The block number",
    defaultValue: "9027784",
  })
  .setAction(async () => ({
    default: async (taskArgs: any, hre: HardhatRuntimeEnvironment) => {
      const { ethers } = await hre.network.connect();

      if (!taskArgs.contract) {
        throw new Error("Contract address is required. Use --contract <address>");
      }

      let chainId: bigint;
      if (taskArgs.chainid !== undefined && taskArgs.chainid !== "") {
        chainId = BigInt(taskArgs.chainid);
      } else {
        const network = await ethers.provider.getNetwork();
        chainId = network.chainId;
        console.log(`Using current network chain ID: ${chainId}`);
      }

      let blockNumber: bigint = BigInt(taskArgs.blocknumber);

      const blockHeaderRequester = await ethers.getContractAt(
        "BlockHeaderRequester",
        taskArgs.contract
      );

      const isRequested = await blockHeaderRequester.isBlockRequested(
        chainId,
        blockNumber
      );

      const requestId = await blockHeaderRequester.getRequestId(
        chainId,
        blockNumber
      );

      console.log("\n=== Block Request Status ===");
      console.log("Chain ID:", chainId.toString());
      console.log("Block Number:", blockNumber.toString());
      console.log("Request ID:", requestId);
      console.log("Status:", isRequested ? "✅ Already Requested" : "❌ Not Requested");
      console.log("===========================\n");
    }
  }))
  .build();
