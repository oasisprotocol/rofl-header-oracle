import { task } from "hardhat/config";
import { HardhatRuntimeEnvironment } from "hardhat/types";
import { saveDeploymentInfo } from "../utils/save-deployment.js";

export const deployBlockHeaderRequester = task("deploy:block-header-requester", "Deploy the BlockHeaderRequester contract")
  .addFlag({
    name: "verify",
    description: "Verify contract on Etherscan",
  })
  .setAction(async () => ({
    default: async (taskArgs: any, hre: HardhatRuntimeEnvironment) => {
      const { ethers } = await hre.network.connect();

      const networkName = hre.globalOptions.network || "hardhat";

      console.log("Deploying BlockHeaderRequester contract...");
      console.log("Network:", networkName);

      const [deployer] = await ethers.getSigners();
      console.log("Deploying with account:", deployer.address);

      const balance = await ethers.provider.getBalance(deployer.address);
      console.log("Account balance:", ethers.formatEther(balance), "ETH");

      const BlockHeaderRequester = await ethers.getContractFactory("BlockHeaderRequester");
      const blockHeaderRequester = await BlockHeaderRequester.deploy();

      await blockHeaderRequester.waitForDeployment();
      const contractAddress = await blockHeaderRequester.getAddress();

      console.log("BlockHeaderRequester deployed to:", contractAddress);
      console.log("Transaction hash:", blockHeaderRequester.deploymentTransaction()?.hash);

      console.log("Waiting for block confirmations...");
      await blockHeaderRequester.deploymentTransaction()?.wait(2);

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
      console.log("Block Number:", await ethers.provider.getBlockNumber());
      console.log("==========================\n");

      await saveDeploymentInfo(
        "BlockHeaderRequester",
        contractAddress,
        hre,
        ethers,
        {
          transactionHash: blockHeaderRequester.deploymentTransaction()?.hash,
          constructorArgs: [],
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
