# Block Header Oracle Contracts

This project contains the BlockHeaderRequester contract for requesting block headers
through the Oasis ROFL (Runtime OFf-chain Logic) oracle system.

## Setup

1. Copy `.env.example` to `.env` and fill in your values:

```bash
cp .env.example .env
```

2. Install dependencies:

```bash
bun install
```

## Deployment

To deploy the BlockHeaderRequester contract:

```bash
# Deploy to Sepolia testnet
bun hardhat deploy:block-header-requester --network sepolia

# Deploy to local Hardhat network (for testing)
bun hardhat deploy:block-header-requester

# Deploy with verification on Etherscan
bun hardhat deploy:block-header-requester --network sepolia --verify
```

## Available Tasks

- **Deploy contract**:
  `bun hardhat deploy:block-header-requester [--verify] [--network <network>]`
- **Request block header**:
  `bun hardhat request:block-header --contract <address> [--chainid <id>]
  [--blocknumber <num>] [--context <data>] [--network <network>]`
- **Check block status**:
  `bun hardhat check:block-requested --contract <address> [--chainid <id>]
  [--blocknumber <num>] [--network <network>]`

## Contract Structure

- `contracts/BlockHeaderRequester.sol` - Main contract for requesting block headers
- `contracts/hashi/adapters/Oasis/ROFLAdapter.sol` - Reference
  implementation of the
  ROFL adapter for Oasis (for reference only)

## Note on ROFL Adapter

The `ROFLAdapter.sol` contract in `contracts/hashi/adapters/Oasis/` is
  included here for
reference only. This adapter is part of the Hashi cross-chain oracle aggregator framework
and available in Hashi repository fork at <https://github.com/rube-de/hashi>.

## Configuration

This project uses Hardhat 3 with the following configuration:

- Solidity 0.8.28
- Ethers.js v6 for blockchain interactions
- Support for Sepolia testnet

Environment variables needed:

- `SEPOLIA_RPC_URL` - RPC endpoint for Sepolia testnet
- `SEPOLIA_PRIVATE_KEY` - Private key for the deployer account
