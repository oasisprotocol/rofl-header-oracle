import { HardhatRuntimeEnvironment } from "hardhat/types";
import fs from "node:fs";
import path from "node:path";

export interface DeploymentInfo {
  address: string;
  network: string;
  chainId: string;
  deployer: string;
  blockNumber: number;
  timestamp: number;
  transactionHash?: string;
  constructorArgs?: any[];
}

export async function saveDeploymentInfo(
  contractName: string,
  contractAddress: string,
  hre: HardhatRuntimeEnvironment,
  ethers: any,
  additionalInfo?: {
    transactionHash?: string;
    constructorArgs?: any[];
  }
): Promise<void> {
  const [deployer] = await ethers.getSigners();
  const network = await ethers.provider.getNetwork();
  const blockNumber = await ethers.provider.getBlockNumber();
  const block = await ethers.provider.getBlock(blockNumber);

  const networkName = hre.globalOptions.network || "hardhat";

  const deploymentInfo: DeploymentInfo = {
    address: contractAddress,
    network: networkName,
    chainId: network.chainId.toString(),
    deployer: deployer.address,
    blockNumber,
    timestamp: block?.timestamp || Math.floor(Date.now() / 1000),
    ...additionalInfo,
  };

  const deploymentsDir = path.join(process.cwd(), "deployments");
  if (!fs.existsSync(deploymentsDir)) {
    fs.mkdirSync(deploymentsDir, { recursive: true });
  }

  const filename = `${contractName}-${networkName}.json`;
  const filepath = path.join(deploymentsDir, filename);

  fs.writeFileSync(filepath, JSON.stringify(deploymentInfo, null, 2));

  console.log(`Deployment info saved to: ${filepath}`);
}