#!/usr/bin/env python3
"""Unit tests for BlockSubmitter module."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from web3 import Web3
from web3.types import Wei

from rofl_oracle.block_submitter import BlockSubmitter


@pytest.fixture
def mock_contract_util():
    """Create a mock ContractUtility instance."""
    mock = MagicMock()
    mock.w3 = MagicMock()
    mock.w3.eth.gas_price = Wei(1000000000)  # 1 gwei
    mock.w3.eth.wait_for_transaction_receipt = MagicMock()
    return mock


@pytest.fixture
def mock_rofl_util():
    """Create a mock RoflUtility instance."""
    mock = AsyncMock()
    mock.submit_tx = AsyncMock(return_value=True)
    return mock


@pytest.fixture
def mock_contract():
    """Create a mock contract instance."""
    mock = MagicMock()
    mock.functions.storeBlockHeader = MagicMock()
    mock.functions.setHashes = MagicMock()
    return mock


class TestBlockSubmitter:
    """Test suite for BlockSubmitter class."""

    def test_init_with_rofl_util(self, mock_contract_util, mock_rofl_util):
        """Test initialization with ROFL utility (production mode)."""
        source_chain_id = 1
        contract_address = "0x742d35Cc6634C0532925a3b844Bc9e7595f0bEb7"

        # Mock the get_contract_abi method to return ROFLAdapter ABI
        mock_contract_util.get_contract_abi = MagicMock(
            return_value=[
                {
                    "name": "storeBlockHeader",
                    "type": "function",
                    "inputs": [
                        {"name": "chainId", "type": "uint256"},
                        {"name": "blockNumber", "type": "uint256"},
                        {"name": "blockHash", "type": "bytes32"},
                    ],
                }
            ]
        )
        mock_contract_util.w3.eth.contract = MagicMock()

        submitter = BlockSubmitter(
            contract_util=mock_contract_util,
            rofl_util=mock_rofl_util,
            source_chain_id=source_chain_id,
            contract_address=contract_address,
        )

        assert submitter.contract_util == mock_contract_util
        assert submitter.rofl_util == mock_rofl_util
        assert submitter.source_chain_id == source_chain_id
        assert submitter.contract_address == Web3.to_checksum_address(
            contract_address
        )
        # Verify ROFLAdapter ABI was loaded
        mock_contract_util.get_contract_abi.assert_called_once_with(
            "ROFLAdapter"
        )

    def test_init_without_rofl_util(self, mock_contract_util):
        """Test initialization without ROFL utility (local mode)."""
        source_chain_id = 1
        contract_address = "0x742d35Cc6634C0532925a3b844Bc9e7595f0bEb7"

        # Mock the get_contract_abi method to return MockAdapter ABI
        mock_contract_util.get_contract_abi = MagicMock(
            return_value=[
                {
                    "name": "setHashes",
                    "type": "function",
                    "inputs": [
                        {"name": "domain", "type": "uint256"},
                        {"name": "ids", "type": "uint256[]"},
                        {"name": "hashes", "type": "bytes32[]"},
                    ],
                }
            ]
        )
        mock_contract_util.w3.eth.contract = MagicMock()

        submitter = BlockSubmitter(
            contract_util=mock_contract_util,
            rofl_util=None,
            source_chain_id=source_chain_id,
            contract_address=contract_address,
        )

        assert submitter.contract_util == mock_contract_util
        assert submitter.rofl_util is None
        assert submitter.source_chain_id == source_chain_id
        assert submitter.contract_address == Web3.to_checksum_address(
            contract_address
        )
        # Verify MockAdapter ABI was loaded
        mock_contract_util.get_contract_abi.assert_called_once_with(
            "MockAdapter"
        )

    def test_abi_loading_based_on_mode(
        self, mock_contract_util, mock_rofl_util
    ):
        """Test that correct ABI is loaded based on mode."""
        source_chain_id = 1
        contract_address = "0x742d35Cc6634C0532925a3b844Bc9e7595f0bEb7"

        # Test ROFL mode loads ROFLAdapter
        mock_contract_util.get_contract_abi = MagicMock()
        mock_contract_util.w3.eth.contract = MagicMock()

        BlockSubmitter(
            contract_util=mock_contract_util,
            rofl_util=mock_rofl_util,
            source_chain_id=source_chain_id,
            contract_address=contract_address,
        )
        mock_contract_util.get_contract_abi.assert_called_with("ROFLAdapter")

        # Reset mock
        mock_contract_util.get_contract_abi.reset_mock()

        # Test local mode loads MockAdapter
        BlockSubmitter(
            contract_util=mock_contract_util,
            rofl_util=None,
            source_chain_id=source_chain_id,
            contract_address=contract_address,
        )
        mock_contract_util.get_contract_abi.assert_called_with("MockAdapter")

    @pytest.mark.asyncio
    async def test_submit_block_header_rofl_success(
        self, mock_contract_util, mock_rofl_util, mock_contract
    ):
        """Test successful block header submission via ROFL using oracle key."""
        source_chain_id = 1
        block_number = 12345
        block_hash = (
            "0x1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef"
        )
        tx_hash = b"\x12\x34\x56\x78"

        # Setup mocks for transact (now using oracle key)
        mock_transact = MagicMock()
        mock_transact.transact = MagicMock(return_value=tx_hash)
        mock_contract.functions.storeBlockHeader.return_value = mock_transact

        # Mock successful receipt
        mock_contract_util.w3.eth.wait_for_transaction_receipt.return_value = {
            "status": 1,
            "blockNumber": 12346,
        }

        mock_contract_util.get_contract_abi = MagicMock(return_value=[])
        mock_contract_util.w3.eth.contract = MagicMock(
            return_value=mock_contract
        )

        submitter = BlockSubmitter(
            contract_util=mock_contract_util,
            rofl_util=mock_rofl_util,
            source_chain_id=source_chain_id,
            contract_address="0x742d35Cc6634C0532925a3b844Bc9e7595f0bEb7",
        )

        result = await submitter.submit_block_header(block_number, block_hash)

        assert result is True
        # Now using transact instead of submit_tx
        mock_contract.functions.storeBlockHeader.assert_called_once_with(
            source_chain_id, block_number, block_hash
        )
        mock_transact.transact.assert_called_once_with(
            {"gas": 300000, "gasPrice": Wei(1000000000)}
        )
        # Should NOT call submit_tx since we're using oracle key
        mock_rofl_util.submit_tx.assert_not_called()

    @pytest.mark.asyncio
    async def test_submit_block_header_rofl_failure(
        self, mock_contract_util, mock_rofl_util, mock_contract
    ):
        """Test failed block header submission via ROFL (transaction reverted)."""
        source_chain_id = 1
        block_number = 12345
        block_hash = (
            "0x1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef"
        )
        tx_hash = b"\x12\x34\x56\x78"

        # Setup mocks for transact
        mock_transact = MagicMock()
        mock_transact.transact = MagicMock(return_value=tx_hash)
        mock_contract.functions.storeBlockHeader.return_value = mock_transact

        # Mock failed receipt (status = 0)
        mock_contract_util.w3.eth.wait_for_transaction_receipt.return_value = {
            "status": 0,
            "blockNumber": 12346,
        }

        mock_contract_util.get_contract_abi = MagicMock(return_value=[])
        mock_contract_util.w3.eth.contract = MagicMock(
            return_value=mock_contract
        )

        submitter = BlockSubmitter(
            contract_util=mock_contract_util,
            rofl_util=mock_rofl_util,
            source_chain_id=source_chain_id,
            contract_address="0x742d35Cc6634C0532925a3b844Bc9e7595f0bEb7",
        )

        result = await submitter.submit_block_header(block_number, block_hash)

        assert result is False
        # Should NOT call submit_tx since we're using oracle key
        mock_rofl_util.submit_tx.assert_not_called()

    @pytest.mark.asyncio
    async def test_get_registered_oracle(
        self, mock_contract_util, mock_rofl_util, mock_contract
    ):
        """Test getting the registered oracle address."""
        oracle_address = "0x1234567890123456789012345678901234567890"
        
        # Setup mock for ROFL_ORACLE function call
        mock_contract.functions.ROFL_ORACLE = MagicMock()
        mock_contract.functions.ROFL_ORACLE().call = MagicMock(
            return_value=oracle_address
        )
        
        mock_contract_util.get_contract_abi = MagicMock(return_value=[])
        mock_contract_util.w3.eth.contract = MagicMock(
            return_value=mock_contract
        )
        
        submitter = BlockSubmitter(
            contract_util=mock_contract_util,
            rofl_util=mock_rofl_util,
            source_chain_id=1,
            contract_address="0x742d35Cc6634C0532925a3b844Bc9e7595f0bEb7",
        )
        
        result = await submitter.get_registered_oracle()
        assert result == oracle_address
        
    @pytest.mark.asyncio
    async def test_get_registered_oracle_none(
        self, mock_contract_util, mock_rofl_util, mock_contract
    ):
        """Test getting registered oracle when none is set."""
        # Zero address means no oracle registered
        mock_contract.functions.ROFL_ORACLE = MagicMock()
        mock_contract.functions.ROFL_ORACLE().call = MagicMock(
            return_value="0x0000000000000000000000000000000000000000"
        )
        
        mock_contract_util.get_contract_abi = MagicMock(return_value=[])
        mock_contract_util.w3.eth.contract = MagicMock(
            return_value=mock_contract
        )
        
        submitter = BlockSubmitter(
            contract_util=mock_contract_util,
            rofl_util=mock_rofl_util,
            source_chain_id=1,
            contract_address="0x742d35Cc6634C0532925a3b844Bc9e7595f0bEb7",
        )
        
        result = await submitter.get_registered_oracle()
        assert result is None
        
    @pytest.mark.asyncio
    async def test_register_oracle_success(
        self, mock_contract_util, mock_rofl_util, mock_contract
    ):
        """Test successful oracle registration."""
        oracle_address = "0x1234567890123456789012345678901234567890"
        
        # Setup mocks
        mock_contract_util.w3.eth.default_account = oracle_address
        
        mock_build_tx = MagicMock()
        mock_build_tx.build_transaction = MagicMock(
            return_value={
                "to": "0x742d35Cc6634C0532925a3b844Bc9e7595f0bEb7",
                "data": "0xabcdef",
                "gas": 100000,
                "gasPrice": Wei(1000000000),
                "value": Wei(0),
            }
        )
        mock_contract.functions.setOracle.return_value = mock_build_tx
        
        mock_contract_util.get_contract_abi = MagicMock(return_value=[])
        mock_contract_util.w3.eth.contract = MagicMock(
            return_value=mock_contract
        )
        
        submitter = BlockSubmitter(
            contract_util=mock_contract_util,
            rofl_util=mock_rofl_util,
            source_chain_id=1,
            contract_address="0x742d35Cc6634C0532925a3b844Bc9e7595f0bEb7",
        )
        
        result = await submitter.register_oracle()
        
        assert result is True
        mock_contract.functions.setOracle.assert_called_once_with(oracle_address)
        mock_rofl_util.submit_tx.assert_called_once()
        
    @pytest.mark.asyncio
    async def test_register_oracle_local_mode(
        self, mock_contract_util, mock_contract
    ):
        """Test that oracle registration is skipped in local mode."""
        mock_contract_util.get_contract_abi = MagicMock(return_value=[])
        mock_contract_util.w3.eth.contract = MagicMock(
            return_value=mock_contract
        )
        
        submitter = BlockSubmitter(
            contract_util=mock_contract_util,
            rofl_util=None,  # Local mode
            source_chain_id=1,
            contract_address="0x742d35Cc6634C0532925a3b844Bc9e7595f0bEb7",
        )
        
        result = await submitter.register_oracle()
        
        assert result is True  # Should return True but do nothing
        mock_contract.functions.setOracle.assert_not_called()

    @pytest.mark.asyncio
    async def test_submit_block_header_local_success(
        self, mock_contract_util, mock_contract
    ):
        """Test successful block header submission in local mode."""
        source_chain_id = 1
        block_number = 12345
        block_hash = (
            "0x1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef"
        )
        tx_hash = b"\x12\x34\x56\x78"

        # Setup mocks for MockAdapter
        mock_transact = MagicMock()
        mock_transact.transact = MagicMock(return_value=tx_hash)
        mock_contract.functions.setHashes.return_value = mock_transact

        # Mock successful receipt
        mock_contract_util.w3.eth.wait_for_transaction_receipt.return_value = {
            "status": 1,
            "blockNumber": 12346,
        }

        mock_contract_util.get_contract_abi = MagicMock(return_value=[])
        mock_contract_util.w3.eth.contract = MagicMock(
            return_value=mock_contract
        )

        submitter = BlockSubmitter(
            contract_util=mock_contract_util,
            rofl_util=None,  # Local mode
            source_chain_id=source_chain_id,
            contract_address="0x742d35Cc6634C0532925a3b844Bc9e7595f0bEb7",
        )

        result = await submitter.submit_block_header(block_number, block_hash)

        assert result is True
        # MockAdapter uses setHashes with arrays. We pass a list of hex strings.
        mock_contract.functions.setHashes.assert_called_once_with(
            source_chain_id,  # domain
            [block_number],  # ids array
            [block_hash],  # hashes array (as list of hex strings)
        )
        mock_transact.transact.assert_called_once_with(
            {"gas": 300000, "gasPrice": Wei(1000000000)}
        )
        mock_contract_util.w3.eth.wait_for_transaction_receipt.assert_called_once()

    @pytest.mark.asyncio
    async def test_submit_block_header_local_failure(
        self, mock_contract_util, mock_contract
    ):
        """Test failed block header submission in local mode (transaction reverted)."""
        source_chain_id = 1
        block_number = 12345
        block_hash = (
            "0x1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef"
        )
        tx_hash = b"\x12\x34\x56\x78"

        # Setup mocks for MockAdapter
        mock_transact = MagicMock()
        mock_transact.transact = MagicMock(return_value=tx_hash)
        mock_contract.functions.setHashes.return_value = mock_transact

        # Mock failed receipt (status = 0)
        mock_contract_util.w3.eth.wait_for_transaction_receipt.return_value = {
            "status": 0,
            "blockNumber": 12346,
        }

        mock_contract_util.get_contract_abi = MagicMock(return_value=[])
        mock_contract_util.w3.eth.contract = MagicMock(
            return_value=mock_contract
        )

        submitter = BlockSubmitter(
            contract_util=mock_contract_util,
            rofl_util=None,  # Local mode
            source_chain_id=source_chain_id,
            contract_address="0x742d35Cc6634C0532925a3b844Bc9e7595f0bEb7",
        )

        result = await submitter.submit_block_header(block_number, block_hash)

        assert result is False

    @pytest.mark.asyncio
    async def test_submit_block_header_exception_handling(
        self, mock_contract_util, mock_rofl_util, mock_contract
    ):
        """Test exception handling during submission."""
        source_chain_id = 1
        block_number = 12345
        block_hash = (
            "0x1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef"
        )

        # Setup mock to raise exception
        mock_contract.functions.storeBlockHeader.side_effect = Exception(
            "Test error"
        )

        mock_contract_util.get_contract_abi = MagicMock(return_value=[])
        mock_contract_util.w3.eth.contract = MagicMock(
            return_value=mock_contract
        )

        submitter = BlockSubmitter(
            contract_util=mock_contract_util,
            rofl_util=mock_rofl_util,
            source_chain_id=source_chain_id,
            contract_address="0x742d35Cc6634C0532925a3b844Bc9e7595f0bEb7",
        )

        result = await submitter.submit_block_header(block_number, block_hash)

        assert result is False

    @pytest.mark.asyncio
    async def test_submit_block_header_local_transaction_error(
        self, mock_contract_util, mock_contract
    ):
        """Test exception during local transaction submission."""
        source_chain_id = 1
        block_number = 12345
        block_hash = (
            "0x1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef"
        )

        # Setup mock to raise exception during transact with MockAdapter's setHashes
        mock_transact = MagicMock()
        mock_transact.transact.side_effect = Exception("Transaction failed")
        mock_contract.functions.setHashes.return_value = mock_transact

        mock_contract_util.get_contract_abi = MagicMock(return_value=[])
        mock_contract_util.w3.eth.contract = MagicMock(
            return_value=mock_contract
        )

        submitter = BlockSubmitter(
            contract_util=mock_contract_util,
            rofl_util=None,  # Local mode
            source_chain_id=source_chain_id,
            contract_address="0x742d35Cc6634C0532925a3b844Bc9e7595f0bEb7",
        )

        result = await submitter.submit_block_header(block_number, block_hash)

        assert result is False
