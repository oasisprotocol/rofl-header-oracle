#!/usr/bin/env python3
"""Integration tests for push oracle mode."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from web3 import Web3

from rofl_oracle.block_submitter import BlockSubmitter
from rofl_oracle.config import (
    CommonConfig,
    OracleConfig,
    OracleMode,
    PushModeConfig,
)
from rofl_oracle.header_oracle import HeaderOracle


@pytest.fixture
def source_rpc_url():
    """Source chain RPC URL for testing."""
    return "http://localhost:8545"


@pytest.fixture
def target_rpc_url():
    """Target chain RPC URL for testing."""
    return "http://localhost:8546"


@pytest.fixture
def web3_instance(source_rpc_url):
    """Create a Web3 instance for testing."""
    return Web3(Web3.HTTPProvider(source_rpc_url))


@pytest.fixture
def mock_common_config():
    """Create a mock common config."""
    return CommonConfig(
        source_rpc_url="http://localhost:8545",
        source_chain_id=1337,
        target_rpc_url="http://localhost:8546",
        request_timeout=5,
        retry_count=2,
        target_contract_address="0x742d35Cc6634C0532925a3b844Bc9e7595f0bEb7",
    )


@pytest.fixture
def mock_push_oracle_config():
    """Create a mock push oracle config with short intervals for testing."""
    return PushModeConfig(
        push_interval=2,  # Short interval for testing
        batch_size=20,
    )


@pytest.fixture
def mock_oracle_config(mock_common_config, mock_push_oracle_config):
    """Create a mock oracle config for push oracle mode."""
    return OracleConfig(
        common_config=mock_common_config,
        oracle_mode=OracleMode.PUSH,
        mode_config=mock_push_oracle_config,
        local_mode=True,
        local_private_key="0x" + "a" * 64,
    )


class TestPushOracleMode:
    """Test suite for push oracle mode functionality."""

    @pytest.mark.asyncio
    async def test_push_oracle_config_detection(self, mock_oracle_config):
        """Test that push oracle mode is correctly detected from config."""
        assert mock_oracle_config.oracle_mode == OracleMode.PUSH
        assert isinstance(mock_oracle_config.mode_config, PushModeConfig)

    @pytest.mark.asyncio
    async def test_push_oracle_initialization(self, mock_oracle_config):
        """Test that HeaderOracle initializes correctly in push oracle mode."""
        with patch("rofl_oracle.header_oracle.Web3") as mock_web3_class:
            # Mock Web3 instances
            mock_source_w3 = MagicMock()
            mock_source_w3.is_connected.return_value = True
            mock_source_w3.eth.chain_id = 1337

            mock_web3_class.return_value = mock_source_w3

            # Mock ContractUtility
            with patch(
                "rofl_oracle.header_oracle.ContractUtility"
            ) as mock_contract_util_class:
                mock_contract_util = MagicMock()
                mock_contract_util.w3.eth.default_account = (
                    "0x1234567890123456789012345678901234567890"
                )
                mock_contract_util_class.return_value = mock_contract_util

                # Mock BlockSubmitter
                with patch(
                    "rofl_oracle.header_oracle.BlockSubmitter"
                ) as mock_block_submitter_class:
                    mock_block_submitter = MagicMock()
                    mock_block_submitter_class.return_value = (
                        mock_block_submitter
                    )

                    # Mock EventProcessor
                    with patch(
                        "rofl_oracle.header_oracle.EventProcessor"
                    ) as mock_event_processor_class:
                        mock_event_processor = MagicMock()
                        mock_event_processor_class.return_value = (
                            mock_event_processor
                        )

                        oracle = await HeaderOracle.create(mock_oracle_config)

                        # Verify push oracle mode initialization
                        assert oracle.config.oracle_mode == OracleMode.PUSH
                        assert (
                            oracle.event_listener is None
                        )  # No event listener in push mode
                        assert (
                            oracle.block_requester_abi is None
                        )  # No ABI needed

    @pytest.mark.asyncio
    async def test_push_latest_block_header_first_run(self):
        """Test pushing block header when no blocks have been stored yet."""
        # Mock BlockSubmitter
        mock_block_submitter = MagicMock()
        mock_block_submitter.get_latest_block_number = AsyncMock(
            return_value=None
        )  # No blocks stored
        mock_block_submitter.submit_block_header = AsyncMock(return_value=True)

        # Mock Web3 source chain
        mock_source_w3 = MagicMock()
        mock_source_w3.eth.block_number = 1000  # Current latest block

        # Create HeaderOracle instance
        oracle = HeaderOracle()
        oracle.block_submitter = mock_block_submitter
        oracle.source_w3 = mock_source_w3

        # Mock fetch_block_by_number
        mock_block_data = {
            "hash": "0x1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef",
            "number": 1000,
        }
        oracle.fetch_block_by_number = MagicMock(return_value=mock_block_data)

        await oracle.push_latest_block_header()

        # Should start from latest block (1000) when no blocks stored
        oracle.fetch_block_by_number.assert_called_once_with(1000)
        mock_block_submitter.submit_block_header.assert_called_once_with(
            1000,
            "0x1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef",
        )

    @pytest.mark.asyncio
    async def test_push_latest_block_header_backfill(self):
        """Test backfilling blocks when oracle is behind."""
        # Mock BlockSubmitter
        mock_block_submitter = MagicMock()
        mock_block_submitter.get_latest_block_number = AsyncMock(
            return_value=995
        )  # 5 blocks behind
        mock_block_submitter.submit_block_header = AsyncMock(return_value=True)

        # Mock Web3 source chain
        mock_source_w3 = MagicMock()
        mock_source_w3.eth.block_number = 1000  # Current latest block

        # Create HeaderOracle instance
        oracle = HeaderOracle()
        oracle.block_submitter = mock_block_submitter
        oracle.source_w3 = mock_source_w3

        # Mock fetch_block_by_number to return different blocks
        def mock_fetch_block(block_number):
            return {"hash": f"0x{block_number:064x}", "number": block_number}

        oracle.fetch_block_by_number = MagicMock(side_effect=mock_fetch_block)

        await oracle.push_latest_block_header()

        # Should push blocks 996-1000 (5 blocks total)
        assert oracle.fetch_block_by_number.call_count == 5
        assert mock_block_submitter.submit_block_header.call_count == 5

        for block_num in range(996, 1001):
            oracle.fetch_block_by_number.assert_any_call(block_num)
            mock_block_submitter.submit_block_header.assert_any_call(
                block_num, f"0x{block_num:064x}"
            )

    @pytest.mark.asyncio
    async def test_push_latest_block_header_up_to_date(self):
        """Test when oracle is already up to date."""
        # Mock BlockSubmitter
        mock_block_submitter = MagicMock()
        mock_block_submitter.get_latest_block_number = AsyncMock(
            return_value=1000
        )  # Up to date
        mock_block_submitter.submit_block_header = AsyncMock()

        # Mock Web3 source chain
        mock_source_w3 = MagicMock()
        mock_source_w3.eth.block_number = 1000  # Same as stored

        # Create HeaderOracle instance
        oracle = HeaderOracle()
        oracle.block_submitter = mock_block_submitter
        oracle.source_w3 = mock_source_w3
        oracle.fetch_block_by_number = MagicMock()

        await oracle.push_latest_block_header()

        # Should not fetch or submit any blocks
        oracle.fetch_block_by_number.assert_not_called()
        mock_block_submitter.submit_block_header.assert_not_called()

    @pytest.mark.asyncio
    async def test_push_latest_block_header_submission_failure(self):
        """Test handling of submission failures."""
        # Mock BlockSubmitter
        mock_block_submitter = MagicMock()
        mock_block_submitter.get_latest_block_number = AsyncMock(
            return_value=995
        )  # 5 blocks behind
        mock_block_submitter.submit_block_header = AsyncMock(
            return_value=False
        )  # Fail

        # Mock Web3 source chain
        mock_source_w3 = MagicMock()
        mock_source_w3.eth.block_number = 1000

        # Create HeaderOracle instance
        oracle = HeaderOracle()
        oracle.block_submitter = mock_block_submitter
        oracle.source_w3 = mock_source_w3

        # Mock fetch_block_by_number
        mock_block_data = {
            "hash": "0x1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef",
            "number": 996,
        }
        oracle.fetch_block_by_number = MagicMock(return_value=mock_block_data)

        await oracle.push_latest_block_header()

        # Should attempt submission but fail
        mock_block_submitter.submit_block_header.assert_called_once_with(
            996,
            "0x1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef",
        )

    @pytest.mark.asyncio
    async def test_push_latest_block_header_block_fetch_failure(self):
        """Test handling of block fetch failures."""
        # Mock BlockSubmitter
        mock_block_submitter = MagicMock()
        mock_block_submitter.get_latest_block_number = AsyncMock(
            return_value=995
        )  # 5 blocks behind
        mock_block_submitter.submit_block_header = AsyncMock()

        # Mock Web3 source chain
        mock_source_w3 = MagicMock()
        mock_source_w3.eth.block_number = 1000

        # Create HeaderOracle instance
        oracle = HeaderOracle()
        oracle.block_submitter = mock_block_submitter
        oracle.source_w3 = mock_source_w3

        # Mock fetch_block_by_number to return None (failure)
        oracle.fetch_block_by_number = MagicMock(return_value=None)

        await oracle.push_latest_block_header()

        # Should not attempt submission
        oracle.fetch_block_by_number.assert_called_once_with(996)
        mock_block_submitter.submit_block_header.assert_not_called()

    @pytest.mark.asyncio
    async def test_push_latest_block_header_no_block_hash(self):
        """Test handling of blocks without hash."""
        # Mock BlockSubmitter
        mock_block_submitter = MagicMock()
        mock_block_submitter.get_latest_block_number = AsyncMock(
            return_value=995
        )  # 5 blocks behind
        mock_block_submitter.submit_block_header = AsyncMock()

        # Mock Web3 source chain
        mock_source_w3 = MagicMock()
        mock_source_w3.eth.block_number = 1000

        # Create HeaderOracle instance
        oracle = HeaderOracle()
        oracle.block_submitter = mock_block_submitter
        oracle.source_w3 = mock_source_w3

        # Mock fetch_block_by_number to return block without hash
        mock_block_data = {"number": 996}  # No hash
        oracle.fetch_block_by_number = MagicMock(return_value=mock_block_data)

        await oracle.push_latest_block_header()

        # Should not attempt submission
        mock_block_submitter.submit_block_header.assert_not_called()

    @pytest.mark.asyncio
    async def test_block_submitter_get_latest_block_number(self):
        """Test BlockSubmitter.get_latest_block_number method."""
        # Mock contract utility
        mock_contract_util = MagicMock()

        # Mock contract
        mock_contract = MagicMock()
        mock_contract.functions.lastStoredBlock.return_value.call.return_value = 1000

        mock_contract_util.get_contract_abi.return_value = []
        mock_contract_util.w3.eth.contract.return_value = mock_contract

        submitter = BlockSubmitter(
            contract_util=mock_contract_util,
            rofl_util=None,
            source_chain_id=1337,
            contract_address="0x742d35Cc6634C0532925a3b844Bc9e7595f0bEb7",
        )

        result = await submitter.get_latest_block_number()  # Add await

        assert result == 1000
        mock_contract.functions.lastStoredBlock.assert_called_once_with(1337)

    @pytest.mark.asyncio
    async def test_block_submitter_get_latest_block_number_none(self):
        """Test BlockSubmitter.get_latest_block_number when no blocks stored."""
        # Mock contract utility
        mock_contract_util = MagicMock()

        # Mock contract
        mock_contract = MagicMock()
        mock_contract.functions.lastStoredBlock.return_value.call.return_value = 0

        mock_contract_util.get_contract_abi.return_value = []
        mock_contract_util.w3.eth.contract.return_value = mock_contract

        submitter = BlockSubmitter(
            contract_util=mock_contract_util,
            rofl_util=None,
            source_chain_id=1337,
            contract_address="0x742d35Cc6634C0532925a3b844Bc9e7595f0bEb7",
        )

        result = await submitter.get_latest_block_number()

        assert result is None  # Returns None when lastStoredBlock is 0

    @pytest.mark.asyncio
    async def test_block_submitter_get_latest_block_number_error(self):
        """Test BlockSubmitter.get_latest_block_number error handling."""
        # Mock contract utility
        mock_contract_util = MagicMock()

        # Mock contract to raise exception
        mock_contract = MagicMock()
        mock_contract.functions.lastStoredBlock.return_value.call.side_effect = Exception(
            "Contract error"
        )

        mock_contract_util.get_contract_abi.return_value = []
        mock_contract_util.w3.eth.contract.return_value = mock_contract

        submitter = BlockSubmitter(
            contract_util=mock_contract_util,
            rofl_util=None,
            source_chain_id=1337,
            contract_address="0x742d35Cc6634C0532925a3b844Bc9e7595f0bEb7",
        )

        result = await submitter.get_latest_block_number()

        assert result is None  # Returns None on error

    @pytest.mark.asyncio
    async def test_push_oracle_run_mode(self, mock_oracle_config):
        """Test that HeaderOracle.run() uses push mode correctly."""
        with patch(
            "rofl_oracle.header_oracle.HeaderOracle._run_push_mode"
        ) as mock_run_push:
            mock_run_push.return_value = None

            oracle = HeaderOracle()
            oracle.config = mock_oracle_config
            oracle.source_w3 = MagicMock()
            oracle.event_listener = None

            await oracle.run()

            # Should call push mode, not event listener mode
            mock_run_push.assert_called_once()

    @pytest.mark.asyncio
    async def test_push_oracle_run_push_mode_loop(self):
        """Test the push mode loop with interruption."""
        from rofl_oracle.config import PushModeConfig

        oracle = HeaderOracle()
        oracle.config = MagicMock()
        oracle.config.mode_config = PushModeConfig(
            push_interval=0.1,  # Very short for testing
            batch_size=20,
        )

        # Mock push_latest_block_header
        oracle.push_latest_block_header = AsyncMock()

        # Track call count
        call_count = 0

        async def mock_push():
            nonlocal call_count
            call_count += 1
            if call_count >= 3:  # Stop after 3 calls
                raise KeyboardInterrupt("Test interruption")

        oracle.push_latest_block_header.side_effect = mock_push

        # Should not raise the KeyboardInterrupt
        await oracle._run_push_mode()

        # Should have been called multiple times
        assert oracle.push_latest_block_header.call_count >= 3

    @pytest.mark.asyncio
    async def test_hex_conversion_for_bytes_hash(self):
        """Test proper hex conversion for bytes block hash."""
        oracle = HeaderOracle()
        oracle.block_submitter = MagicMock()
        oracle.block_submitter.get_latest_block_number = AsyncMock(
            return_value=995
        )
        oracle.block_submitter.submit_block_header = AsyncMock(
            return_value=True
        )

        oracle.source_w3 = MagicMock()
        oracle.source_w3.eth.block_number = 1000

        # Mock block with bytes hash
        mock_block_data = {
            "hash": bytes.fromhex(
                "1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef"
            ),
            "number": 996,
        }
        oracle.fetch_block_by_number = MagicMock(return_value=mock_block_data)

        await oracle.push_latest_block_header()

        # Should convert bytes to hex string with 0x prefix (backfill pushes 996-1000)
        assert oracle.block_submitter.submit_block_header.call_count == 5
        for call in oracle.block_submitter.submit_block_header.call_args_list:
            _, hash_arg = call[0]
            assert (
                hash_arg
                == "0x1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef"
            )
