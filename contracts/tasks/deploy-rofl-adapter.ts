import { task } from "hardhat/config";
import { HardhatRuntimeEnvironment } from "hardhat/types";
import { bech32 } from "bech32";
import { saveDeploymentInfo } from "../utils/save-deployment.js";

/**
 * Decode a ROFL app ID from bech32 format to bytes21
 */
function decodeRoflAppId(roflAppId: string): Uint8Array {
  const decoded = bech32.decode(roflAppId);
  if (decoded.prefix !== "rofl") {
    throw new Error(`Malformed ROFL app identifier: ${roflAppId}. Expected 'rofl' prefix.`);
  }

  const rawAppId = new Uint8Array(bech32.fromWords(decoded.words));

  if (rawAppId.length !== 21) {
    throw new Error(`ROFL app ID must be exactly 21 bytes, got ${rawAppId.length}`);
  }

  return rawAppId;
}

export const deployRoflAdapter = task("deploy:rofl-adapter", "Deploy the ROFLAdapter contract")
  .addOption({
    name: "roflAppId",
    description: "ROFL app ID in bech32 format (e.g., rofl1qrct2u3sap98mx462lzwy7za86ajgaaxkvs79x88)",
    // defaultValue: "rofl1qz5h592w87uyftlrht388g3rkf58s5z7n53w5xh0", // mainnet
    defaultValue: "rofl1qrct2u3sap98mx462lzwy7za86ajgaaxkvs79x88", // testnet
  })
  .addFlag({
    name: "verify",
    description: "Verify contract on block explorer",
  })
  .setAction(async () => ({
    default: async (taskArgs: any, hre: HardhatRuntimeEnvironment) => {
      const { ethers } = await hre.network.connect();
      const networkName = hre.globalOptions.network || "hardhat";

      if (!taskArgs.roflAppId) {
        throw new Error("ROFL app ID is required. Use --rofl-app-id <bech32-id>");
      }

      console.log("Deploying ROFLAdapter (multi-chain)...");
      console.log("Network:", networkName);
      console.log("ROFL App ID:", taskArgs.roflAppId);

      // Decode the bech32 ROFL app ID to bytes21
      const rawAppId = decodeRoflAppId(taskArgs.roflAppId);
      const bytes21AppId = "0x" + Buffer.from(rawAppId).toString("hex");
      console.log("ROFL App ID (bytes21):", bytes21AppId);

      const [deployer] = await ethers.getSigners();
      console.log("Deploying with account:", deployer.address);

      const balance = await ethers.provider.getBalance(deployer.address);
      console.log("Account balance:", ethers.formatEther(balance), "ETH");

      const ROFLAdapter = await ethers.getContractFactory("ROFLAdapter");
      const constructorArgs = [rawAppId] as const;

      const roflAdapter = await ROFLAdapter.deploy(...constructorArgs);

      await roflAdapter.waitForDeployment();
      const contractAddress = await roflAdapter.getAddress();

      console.log("ROFLAdapter deployed to:", contractAddress);
      console.log("Transaction hash:", roflAdapter.deploymentTransaction()?.hash);

      console.log("Waiting for block confirmations...");
      await roflAdapter.deploymentTransaction()?.wait(2);

      if (taskArgs.verify && networkName !== "localhost" && networkName !== "hardhat") {
        console.log("\nVerifying contract...");
        try {
          // Hardhat 3 verify task (attempts Etherscan, Blockscout)
          await hre.run("verify", {
            address: contractAddress,
            constructorArgs: `${bytes21AppId}`,
          });
          console.log("Contract verified successfully!");
        } catch (error: any) {
          if (error.message?.includes("Already Verified") || error.message?.includes("already verified")) {
            console.log("Contract is already verified!");
          } else {
            console.error("Verification failed:", error.message || error);
            console.log("\nFor Oasis Sapphire, verify manually via Sourcify:");
            console.log(`  npx @sourcify/cli verify ${contractAddress} --chain-id 23295`);
            console.log("\nOr use Hardhat:");
            console.log(`  bun hardhat verify --network ${networkName} ${contractAddress} "${bytes21AppId}"`);
          }
        }
      } else if (taskArgs.verify) {
        console.log("Skipping verification on local network");
      }

      console.log("\n=== Deployment Summary ===");
      console.log("Network:", networkName);
      console.log("Contract Address:", contractAddress);
      console.log("ROFL App ID (bech32):", taskArgs.roflAppId);
      console.log("ROFL App ID (bytes21):", bytes21AppId);
      console.log("Deployer:", deployer.address);
      console.log("Block Number:", await ethers.provider.getBlockNumber());
      console.log("==========================");
      console.log("\nNote: This adapter must be deployed on Oasis Sapphire to use ROFL functionality.");
      console.log("After deployment, the ROFL oracle will automatically:");
      console.log("  1. Call setReporter() to authorize the reporter address");
      console.log("  2. Call addSupportedChain() to register each source chain\n");

      await saveDeploymentInfo(
        "ROFLAdapter",
        contractAddress,
        hre,
        ethers,
        {
          transactionHash: roflAdapter.deploymentTransaction()?.hash,
          constructorArgs: [bytes21AppId],
        }
      );

      return contractAddress;
    }
  }))
  .build();
