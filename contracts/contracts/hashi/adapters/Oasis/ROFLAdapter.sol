// SPDX-License-Identifier: LGPL-3.0-only
pragma solidity ^0.8.20;

import {Subcall} from "@oasisprotocol/sapphire-contracts/contracts/Subcall.sol";
import {BlockHashAdapter} from "../BlockHashAdapter.sol";

/**
 * @title ROFLAdapter
 * @notice Adapter for Oasis ROFL
 */
contract ROFLAdapter is BlockHashAdapter {
    string public constant PROVIDER = "oasis";

    bytes21 public immutable roflAppID;
    address public ROFL_REPORTER;
    uint256 public immutable SOURCE_CHAIN_ID;

    mapping(uint256 chainId => uint256 lastBlockNumber) public lastStoredBlock;

    error UnauthorizedROFLReporter();

    constructor(bytes21 _roflAppID, uint256 _sourceChainId) {
        roflAppID = _roflAppID;
        SOURCE_CHAIN_ID = _sourceChainId;
    }

    /**
     * @notice Stores a block header for a given chain and block number
     * @dev Only callable by the authorized ROFL application through Subcall authorization
     * @param chainId The chain ID where the block exists
     * @param blockNumber The block number to store the hash for
     * @param blockHash The block hash to store
     */
    function storeBlockHeader(
        uint256 chainId,
        uint256 blockNumber,
        bytes32 blockHash
    ) external {
        // Verify that the caller is authorized reporter address
        if (msg.sender != ROFL_REPORTER) {
            revert UnauthorizedROFLReporter();
        }

        lastStoredBlock[chainId] = blockNumber;

        _storeHash(chainId, blockNumber, blockHash);
    }

    /**
     * @notice Stores multiple block headers for a given chain
     * @dev Only callable by the authorized ROFL application through Subcall authorization,
     *      and assumes block numbers are in ascending order
     * @param chainId The chain ID where the blocks exist
     * @param blockNumbers The block numbers to store the hashes for
     * @param blockHashes The block hashes to store
     */
    function storeBlockheaders(
        uint256 chainId,
        uint256[] calldata blockNumbers,
        bytes32[] calldata blockHashes
    ) external {
        // Verify that the caller is authorized reporter address
        if (msg.sender != ROFL_REPORTER) {
            revert UnauthorizedROFLReporter();
        }

        uint256 len = blockNumbers.length;
        require(len == blockHashes.length, "Mismatched input lengths");

        if (lastStoredBlock[chainId] < blockNumbers[len - 1]) {
            lastStoredBlock[chainId] = blockNumbers[len - 1];
        }

        _storeHashes(chainId, blockNumbers, blockHashes);
    }

    function setReporter(address reporter) external {
        Subcall.roflEnsureAuthorizedOrigin(roflAppID);
        ROFL_REPORTER = reporter;
    }
}
