#!/usr/bin/env python3
"""Integration tests for watcher mode."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from web3 import Web3

from rofl_oracle.block_submitter import BlockSubmitter
from rofl_oracle.config import (
    CommonConfig,
    OracleConfig,
    OracleMode,
    PushModeConfig,
    TokenWatcherModeConfig,
    WatcherModeConfig,
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
        target_contract_address="0x742D35Cc6634C0532925A3B844bC9e7595f0bEB7",
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


@pytest.fixture
def mock_watcher_config():
    """Create a mock watcher config for watcher mode."""
    return WatcherModeConfig(
        watch_addresses=[
            "0x742D35Cc6634C0532925A3B844bC9e7595f0bEB7",
            "0x1234567890123456789012345678901234567890",
        ],
        scan_interval=5,
    )


@pytest.fixture
def mock_oracle_config_watcher(mock_common_config, mock_watcher_config):
    """Create a mock oracle config for watcher mode."""
    return OracleConfig(
        common_config=mock_common_config,
        oracle_mode=OracleMode.WATCHER,
        mode_config=mock_watcher_config,
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
        mock_block_submitter.submit_block_headers_batch = AsyncMock(
            return_value=True
        )

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
        oracle.fetch_block_by_number = AsyncMock(return_value=mock_block_data)

        await oracle.push_latest_block_header()

        # Should start from latest block (1000) when no blocks stored
        oracle.fetch_block_by_number.assert_called_once_with(1000)
        mock_block_submitter.submit_block_headers_batch.assert_called_once_with(
            [1000],
            [
                "0x1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef"
            ],
        )

    @pytest.mark.asyncio
    async def test_push_latest_block_header_backfill(self):
        """Test backfilling blocks when oracle is behind."""
        # Mock BlockSubmitter
        mock_block_submitter = MagicMock()
        mock_block_submitter.get_latest_block_number = AsyncMock(
            return_value=995
        )  # 5 blocks behind
        mock_block_submitter.submit_block_headers_batch = AsyncMock(
            return_value=True
        )

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

        oracle.fetch_block_by_number = AsyncMock(side_effect=mock_fetch_block)

        await oracle.push_latest_block_header()

        # Should fetch blocks 996-1000 (5 blocks total) and submit in batch
        assert oracle.fetch_block_by_number.call_count == 5
        mock_block_submitter.submit_block_headers_batch.assert_called_once_with(
            [996, 997, 998, 999, 1000],
            [f"0x{n:064x}" for n in range(996, 1001)],
        )

    @pytest.mark.asyncio
    async def test_push_latest_block_header_up_to_date(self):
        """Test when oracle is already up to date."""
        # Mock BlockSubmitter
        mock_block_submitter = MagicMock()
        mock_block_submitter.get_latest_block_number = AsyncMock(
            return_value=1000
        )  # Up to date
        mock_block_submitter.submit_block_headers_batch = AsyncMock()

        # Mock Web3 source chain
        mock_source_w3 = MagicMock()
        mock_source_w3.eth.block_number = 1000  # Same as stored

        # Create HeaderOracle instance
        oracle = HeaderOracle()
        oracle.block_submitter = mock_block_submitter
        oracle.source_w3 = mock_source_w3
        oracle.fetch_block_by_number = AsyncMock()

        await oracle.push_latest_block_header()

        # Should not fetch or submit any blocks
        oracle.fetch_block_by_number.assert_not_called()
        mock_block_submitter.submit_block_headers_batch.assert_not_called()

    @pytest.mark.asyncio
    async def test_push_latest_block_header_submission_failure(self):
        """Test handling of submission failures."""
        # Mock BlockSubmitter
        mock_block_submitter = MagicMock()
        mock_block_submitter.get_latest_block_number = AsyncMock(
            return_value=995
        )  # 5 blocks behind
        mock_block_submitter.submit_block_headers_batch = AsyncMock(
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
        def mock_fetch_block(block_number):
            return {"hash": f"0x{block_number:064x}", "number": block_number}

        oracle.fetch_block_by_number = AsyncMock(side_effect=mock_fetch_block)

        await oracle.push_latest_block_header()

        # Should attempt batch submission (even though it fails)
        mock_block_submitter.submit_block_headers_batch.assert_called_once_with(
            [996, 997, 998, 999, 1000],
            [f"0x{n:064x}" for n in range(996, 1001)],
        )

    @pytest.mark.asyncio
    async def test_push_latest_block_header_block_fetch_failure(self):
        """Test handling of block fetch failures."""
        # Mock BlockSubmitter
        mock_block_submitter = MagicMock()
        mock_block_submitter.get_latest_block_number = AsyncMock(
            return_value=995
        )  # 5 blocks behind
        mock_block_submitter.submit_block_headers_batch = AsyncMock()

        # Mock Web3 source chain
        mock_source_w3 = MagicMock()
        mock_source_w3.eth.block_number = 1000

        # Create HeaderOracle instance
        oracle = HeaderOracle()
        oracle.block_submitter = mock_block_submitter
        oracle.source_w3 = mock_source_w3

        # Mock fetch_block_by_number to return None (failure)
        oracle.fetch_block_by_number = AsyncMock(return_value=None)

        await oracle.push_latest_block_header()

        # Should not attempt submission since fetch failed
        oracle.fetch_block_by_number.assert_called_once_with(996)
        mock_block_submitter.submit_block_headers_batch.assert_not_called()

    @pytest.mark.asyncio
    async def test_push_latest_block_header_no_block_hash(self):
        """Test handling of blocks without hash."""
        # Mock BlockSubmitter
        mock_block_submitter = MagicMock()
        mock_block_submitter.get_latest_block_number = AsyncMock(
            return_value=995
        )  # 5 blocks behind
        mock_block_submitter.submit_block_headers_batch = AsyncMock()

        # Mock Web3 source chain
        mock_source_w3 = MagicMock()
        mock_source_w3.eth.block_number = 1000

        # Create HeaderOracle instance
        oracle = HeaderOracle()
        oracle.block_submitter = mock_block_submitter
        oracle.source_w3 = mock_source_w3

        # Mock fetch_block_by_number to return block without hash
        mock_block_data = {"number": 996}  # No hash
        oracle.fetch_block_by_number = AsyncMock(return_value=mock_block_data)

        await oracle.push_latest_block_header()

        # Should not attempt submission since block has no hash
        mock_block_submitter.submit_block_headers_batch.assert_not_called()

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
            contract_address="0x742D35Cc6634C0532925A3B844bC9e7595f0bEB7",
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
            contract_address="0x742D35Cc6634C0532925A3B844bC9e7595f0bEB7",
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
            contract_address="0x742D35Cc6634C0532925A3B844bC9e7595f0bEB7",
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
        oracle.block_submitter.submit_block_headers_batch = AsyncMock(
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
        oracle.fetch_block_by_number = AsyncMock(return_value=mock_block_data)

        await oracle.push_latest_block_header()

        # Should convert bytes to hex string with 0x prefix (batch with 996-1000)
        oracle.block_submitter.submit_block_headers_batch.assert_called_once()
        call_args = oracle.block_submitter.submit_block_headers_batch.call_args
        block_numbers, hashes = call_args[0]
        assert block_numbers == [996, 997, 998, 999, 1000]
        for hash_arg in hashes:
            assert (
                hash_arg
                == "0x1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef"
            )


class TestWatcherMode:
    """Test suite for watcher mode functionality."""

    @pytest.mark.asyncio
    async def test_watcher_config_detection(self, mock_oracle_config_watcher):
        """Test that watcher mode is correctly detected from config."""
        assert mock_oracle_config_watcher.oracle_mode == OracleMode.WATCHER
        assert isinstance(
            mock_oracle_config_watcher.mode_config, WatcherModeConfig
        )
        assert len(mock_oracle_config_watcher.mode_config.watch_addresses) == 2

    @pytest.mark.asyncio
    async def test_watcher_config_validation(self):
        """Test watcher config validates addresses."""
        # Valid addresses should work
        config = WatcherModeConfig(
            watch_addresses=["0x742D35Cc6634C0532925A3B844bC9e7595f0bEB7"],
            scan_interval=5,
        )
        assert len(config.watch_addresses) == 1
        assert (
            config.watch_addresses[0]
            == "0x742D35Cc6634C0532925A3B844bC9e7595f0bEB7"
        )

        # Invalid address should raise error
        with pytest.raises(ValueError, match="Invalid watch address"):
            WatcherModeConfig(
                watch_addresses=["invalid-address"],
                scan_interval=5,
            )

        # Empty list should raise error
        with pytest.raises(
            ValueError, match="Watcher mode requires at least one watch address"
        ):
            WatcherModeConfig(
                watch_addresses=[],
                scan_interval=5,
            )

    @pytest.mark.asyncio
    async def test_watcher_initialization(self, mock_oracle_config_watcher):
        """Test that HeaderOracle initializes correctly in watcher mode."""
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

                        oracle = await HeaderOracle.create(
                            mock_oracle_config_watcher
                        )

                        # Verify watcher mode initialization
                        assert oracle.config.oracle_mode == OracleMode.WATCHER
                        assert (
                            oracle.event_listener is None
                        )  # No event listener in watcher mode
                        assert (
                            oracle.block_requester_abi is None
                        )  # No ABI needed
                        assert hasattr(oracle, "watched_addresses")
                        assert len(oracle.watched_addresses) == 2

    @pytest.mark.asyncio
    async def test_is_watched_transaction_from_address(self):
        """Test detecting transactions FROM watched addresses."""
        oracle = HeaderOracle()
        oracle.watched_addresses = {
            "0x742d35cc6634c0532925a3b844bc9e7595f0beb7"
        }

        # Transaction from watched address
        tx = {
            "from": "0x742D35Cc6634C0532925A3B844bC9e7595f0bEB7",
            "to": "0x1111111111111111111111111111111111111111",
        }

        assert oracle._is_watched_transaction(tx) is True

    @pytest.mark.asyncio
    async def test_is_watched_transaction_to_address(self):
        """Test detecting transactions TO watched addresses."""
        oracle = HeaderOracle()
        oracle.watched_addresses = {
            "0x742d35cc6634c0532925a3b844bc9e7595f0beb7"
        }

        # Transaction to watched address
        tx = {
            "from": "0x1111111111111111111111111111111111111111",
            "to": "0x742D35Cc6634C0532925A3B844bC9e7595f0bEB7",
        }

        assert oracle._is_watched_transaction(tx) is True

    @pytest.mark.asyncio
    async def test_is_watched_transaction_not_involved(self):
        """Test transactions not involving watched addresses."""
        oracle = HeaderOracle()
        oracle.watched_addresses = {
            "0x742d35cc6634c0532925a3b844bc9e7595f0beb7"
        }

        # Transaction not involving watched address
        tx = {
            "from": "0x1111111111111111111111111111111111111111",
            "to": "0x2222222222222222222222222222222222222222",
        }

        assert oracle._is_watched_transaction(tx) is False

    @pytest.mark.asyncio
    async def test_check_block_for_interactions_with_hash_list(self):
        """Test checking block when transactions are returned as full objects."""
        oracle = HeaderOracle()
        oracle.watched_addresses = {
            "0x742d35cc6634c0532925a3b844bc9e7595f0beb7"
        }
        oracle.config = MagicMock()
        oracle.config.mode_config = WatcherModeConfig(
            watch_addresses=["0x742d35cc6634c0532925a3b844bc9e7595f0beb7"],
            scan_interval=60,
            batch_size=50,
            lookback_blocks=10,
            enable_internal_tx_detection=False,
        )
        oracle.source_w3 = MagicMock()

        # Mock block with full transaction objects (new code uses full_transactions=True)
        mock_block = {
            "number": 1000,
            "hash": "0xabc123",
            "transactions": [
                {
                    "hash": "0xtxhash1",
                    "from": "0x1111111111111111111111111111111111111111",
                    "to": "0x2222222222222222222222222222222222222222",
                },
                {
                    "hash": "0xtxhash2",
                    "from": "0x742D35Cc6634C0532925A3B844bC9e7595f0bEB7",  # Watched address
                    "to": "0x3333333333333333333333333333333333333333",
                },
            ],
        }
        oracle.source_w3.eth.get_block.return_value = mock_block

        result = await oracle._check_block_for_interactions(1000)

        assert result is True
        oracle.source_w3.eth.get_block.assert_called_once_with(
            1000, full_transactions=True
        )

    @pytest.mark.asyncio
    async def test_check_block_for_interactions_with_full_txs(self):
        """Test checking block when transactions are returned as full objects."""
        oracle = HeaderOracle()
        oracle.watched_addresses = {
            "0x742d35cc6634c0532925a3b844bc9e7595f0beb7"
        }
        oracle.config = MagicMock()
        oracle.config.mode_config = WatcherModeConfig(
            watch_addresses=["0x742d35cc6634c0532925a3b844bc9e7595f0beb7"],
            scan_interval=60,
            batch_size=50,
            lookback_blocks=10,
            enable_internal_tx_detection=False,
        )
        oracle.source_w3 = MagicMock()

        # Mock block with full transaction objects
        mock_block = {
            "number": 1000,
            "hash": "0xabc123",
            "transactions": [
                {
                    "hash": "0xtxhash1",
                    "from": "0x1111111111111111111111111111111111111111",
                    "to": "0x2222222222222222222222222222222222222222",
                },
                {
                    "hash": "0xtxhash2",
                    "from": "0x742D35Cc6634C0532925A3B844bC9e7595f0bEB7",  # Watched
                    "to": "0x3333333333333333333333333333333333333333",
                },
            ],
        }
        oracle.source_w3.eth.get_block.return_value = mock_block

        result = await oracle._check_block_for_interactions(1000)

        assert result is True

    @pytest.mark.asyncio
    async def test_check_block_for_interactions_no_interactions(self):
        """Test checking block with no watched address interactions."""
        oracle = HeaderOracle()
        oracle.watched_addresses = {
            "0x742d35cc6634c0532925a3b844bc9e7595f0beb7"
        }
        oracle.config = MagicMock()
        oracle.config.mode_config = WatcherModeConfig(
            watch_addresses=["0x742d35cc6634c0532925a3b844bc9e7595f0beb7"],
            scan_interval=60,
        )

        # Mock block with no watched address interactions
        block = {
            "number": 1000,
            "hash": "0xabc123",
            "transactions": [
                {
                    "hash": "0xtxhash1",
                    "from": "0x1111111111111111111111111111111111111111",
                    "to": "0x2222222222222222222222222222222222222222",
                }
            ],
        }
        oracle.fetch_block_by_number = AsyncMock(return_value=block)

        result = await oracle._check_block_for_interactions(1000)

        assert result is False

    @pytest.mark.asyncio
    async def test_watch_addresses_for_interactions_first_run(self):
        """Test watching addresses when no blocks have been stored yet."""
        oracle = HeaderOracle()
        oracle.watched_addresses = {
            "0x742d35cc6634c0532925a3b844bc9e7595f0beb7"
        }
        oracle.config = MagicMock()
        oracle.config.mode_config = WatcherModeConfig(
            watch_addresses=["0x742d35cc6634c0532925a3b844bc9e7595f0beb7"],
            scan_interval=60,
            batch_size=50,
            lookback_blocks=10,
        )
        oracle.last_scanned_block = None

        # Mock BlockSubmitter
        mock_block_submitter = MagicMock()
        mock_block_submitter.get_latest_block_number = AsyncMock(
            return_value=None
        )
        mock_block_submitter.submit_block_headers_batch = AsyncMock(
            return_value=True
        )
        oracle.block_submitter = mock_block_submitter

        # Mock Web3
        oracle.source_w3 = MagicMock()
        oracle.source_w3.eth.block_number = 1000

        # Mock check for interactions - only block 995 has interaction
        async def mock_check_block(block_num):
            return block_num == 995

        oracle._check_block_for_interactions = AsyncMock(
            side_effect=mock_check_block
        )

        # Mock fetch block
        def mock_fetch_block(block_num):
            return {"number": block_num, "hash": f"0x{block_num:064x}"}

        oracle.fetch_block_by_number = AsyncMock(side_effect=mock_fetch_block)

        await oracle.watch_addresses_for_interactions()

        # Should scan from block 990 to 1000 (lookback_blocks=10)
        # Should only submit block 995 which has interaction
        oracle._check_block_for_interactions.assert_called()
        mock_block_submitter.submit_block_headers_batch.assert_called_once_with(
            [995], [f"0x{995:064x}"]
        )

    @pytest.mark.asyncio
    async def test_watch_addresses_for_interactions_multiple_interactions(self):
        """Test watching addresses with multiple interactions in range."""
        oracle = HeaderOracle()
        oracle.watched_addresses = {
            "0x742d35cc6634c0532925a3b844bc9e7595f0beb7"
        }
        oracle.config = MagicMock()
        oracle.config.mode_config = WatcherModeConfig(
            watch_addresses=["0x742d35cc6634c0532925a3b844bc9e7595f0beb7"],
            scan_interval=10,
            batch_size=50,
            lookback_blocks=10,
            enable_internal_tx_detection=False,
        )
        oracle.last_scanned_block = None

        # Mock BlockSubmitter
        mock_block_submitter = MagicMock()
        mock_block_submitter.get_latest_block_number = AsyncMock(
            return_value=990
        )
        mock_block_submitter.submit_block_headers_batch = AsyncMock(
            return_value=True
        )
        oracle.block_submitter = mock_block_submitter

        # Mock Web3
        oracle.source_w3 = MagicMock()
        oracle.source_w3.eth.block_number = 1000

        # Mock check for interactions - blocks 992, 995, 998 have interactions
        interaction_blocks = {992, 995, 998}

        async def mock_check_block(block_num):
            return block_num in interaction_blocks

        oracle._check_block_for_interactions = AsyncMock(
            side_effect=mock_check_block
        )

        # Mock fetch block
        def mock_fetch_block(block_num):
            return {"number": block_num, "hash": f"0x{block_num:064x}"}

        oracle.fetch_block_by_number = AsyncMock(side_effect=mock_fetch_block)

        await oracle.watch_addresses_for_interactions()

        # Should submit batch with blocks 992, 995, 998
        mock_block_submitter.submit_block_headers_batch.assert_called_once_with(
            [992, 995, 998], [f"0x{992:064x}", f"0x{995:064x}", f"0x{998:064x}"]
        )

    @pytest.mark.asyncio
    async def test_watch_addresses_for_interactions_up_to_date(self):
        """Test when watcher is already up to date."""
        oracle = HeaderOracle()
        oracle.watched_addresses = {
            "0x742d35cc6634c0532925a3b844bc9e7595f0beb7"
        }
        oracle.config = MagicMock()
        oracle.config.mode_config = WatcherModeConfig(
            watch_addresses=["0x742d35cc6634c0532925a3b844bc9e7595f0beb7"],
            scan_interval=10,
            batch_size=50,
            lookback_blocks=10,
            enable_internal_tx_detection=False,
        )
        oracle.last_scanned_block = 1000  # Already scanned up to latest

        # Mock BlockSubmitter
        mock_block_submitter = MagicMock()
        mock_block_submitter.get_latest_block_number = AsyncMock(
            return_value=1000
        )
        mock_block_submitter.submit_block_headers_batch = AsyncMock()
        oracle.block_submitter = mock_block_submitter

        # Mock Web3
        oracle.source_w3 = MagicMock()
        oracle.source_w3.eth.block_number = 1000

        oracle._check_block_for_interactions = AsyncMock()
        oracle.fetch_block_by_number = AsyncMock()

        await oracle.watch_addresses_for_interactions()

        # Should not check or submit anything
        oracle._check_block_for_interactions.assert_not_called()
        mock_block_submitter.submit_block_headers_batch.assert_not_called()

    @pytest.mark.asyncio
    async def test_watch_addresses_batch_submission_failure(self):
        """Test that watcher completes scan even if batch submission fails."""
        oracle = HeaderOracle()
        oracle.watched_addresses = {
            "0x742d35cc6634c0532925a3b844bc9e7595f0beb7"
        }
        oracle.config = MagicMock()
        oracle.config.mode_config = WatcherModeConfig(
            watch_addresses=["0x742d35cc6634c0532925a3b844bc9e7595f0beb7"],
            scan_interval=10,
            batch_size=50,
            lookback_blocks=10,
            enable_internal_tx_detection=False,
        )
        oracle.last_scanned_block = None

        # Mock BlockSubmitter
        mock_block_submitter = MagicMock()
        mock_block_submitter.get_latest_block_number = AsyncMock(
            return_value=990
        )
        mock_block_submitter.submit_block_headers_batch = AsyncMock(
            return_value=False
        )  # Submission fails
        oracle.block_submitter = mock_block_submitter

        # Mock Web3
        oracle.source_w3 = MagicMock()
        oracle.source_w3.eth.block_number = 1000

        # Mock check for interactions - blocks 992, 995 have interactions
        interaction_blocks = {992, 995}

        async def mock_check_block(block_num):
            return block_num in interaction_blocks

        oracle._check_block_for_interactions = AsyncMock(
            side_effect=mock_check_block
        )

        # Mock fetch block
        def mock_fetch_block(block_num):
            return {"number": block_num, "hash": f"0x{block_num:064x}"}

        oracle.fetch_block_by_number = AsyncMock(side_effect=mock_fetch_block)

        await oracle.watch_addresses_for_interactions()

        # Should attempt to submit both blocks in batch (even though it fails)
        mock_block_submitter.submit_block_headers_batch.assert_called_once_with(
            [992, 995], [f"0x{992:064x}", f"0x{995:064x}"]
        )
        # Scan position should still be updated despite submission failure
        assert oracle.last_scanned_block == 1000

    @pytest.mark.asyncio
    async def test_watcher_run_mode(self, mock_oracle_config_watcher):
        """Test that HeaderOracle.run() uses watcher mode correctly."""
        with patch(
            "rofl_oracle.header_oracle.HeaderOracle._run_watcher_mode"
        ) as mock_run_watcher:
            mock_run_watcher.return_value = None

            oracle = HeaderOracle()
            oracle.config = mock_oracle_config_watcher
            oracle.source_w3 = MagicMock()
            oracle.event_listener = None
            oracle.watched_addresses = set()

            await oracle.run()

            # Should call watcher mode
            mock_run_watcher.assert_called_once()

    @pytest.mark.asyncio
    async def test_internal_transaction_detection_enabled(self):
        """Test internal transaction detection when enabled."""
        oracle = HeaderOracle()
        oracle.watched_addresses = {
            "0x742d35cc6634c0532925a3b844bc9e7595f0beb7"
        }
        oracle.config = MagicMock()
        oracle.config.mode_config = WatcherModeConfig(
            watch_addresses=["0x742d35cc6634c0532925a3b844bc9e7595f0beb7"],
            scan_interval=60,
            enable_internal_tx_detection=True,
        )

        # Mock Web3 with block containing full transaction (no direct interaction)
        mock_block = {
            "number": 1000,
            "hash": "0xabc123",
            "transactions": [
                {
                    "hash": "0xtxhash1",
                    "from": "0x1111111111111111111111111111111111111111",
                    "to": "0x2222222222222222222222222222222222222222",
                }
            ],
        }
        oracle.source_w3 = MagicMock()
        oracle.source_w3.eth.get_block.return_value = mock_block

        # Mock internal transaction detection - finds internal interaction
        oracle._check_internal_transactions = AsyncMock(return_value=True)

        result = await oracle._check_block_for_interactions(1000)

        assert result is True
        oracle._check_internal_transactions.assert_called_once_with("0xtxhash1")

    @pytest.mark.asyncio
    async def test_internal_transaction_detection_disabled(self):
        """Test that internal transaction detection is skipped when disabled."""
        oracle = HeaderOracle()
        oracle.watched_addresses = {
            "0x742d35cc6634c0532925a3b844bc9e7595f0beb7"
        }
        oracle.config = MagicMock()
        oracle.config.mode_config = WatcherModeConfig(
            watch_addresses=["0x742d35cc6634c0532925a3b844bc9e7595f0beb7"],
            scan_interval=60,
            enable_internal_tx_detection=False,
        )

        # Mock block with transaction hash
        block = {
            "number": 1000,
            "hash": "0xabc123",
            "transactions": ["0xtxhash1"],
        }
        oracle.fetch_block_by_number = AsyncMock(return_value=block)

        # Mock get_transaction - no direct interaction
        mock_tx = {
            "from": "0x1111111111111111111111111111111111111111",
            "to": "0x2222222222222222222222222222222222222222",
        }
        oracle.source_w3 = MagicMock()
        oracle.source_w3.eth.get_transaction.return_value = mock_tx

        # Mock internal transaction detection - should not be called
        oracle._check_internal_transactions = AsyncMock(return_value=True)

        result = await oracle._check_block_for_interactions(1000)

        assert result is False
        oracle._check_internal_transactions.assert_not_called()

    @pytest.mark.asyncio
    async def test_check_internal_transactions_success(self):
        """Test successful internal transaction detection."""
        oracle = HeaderOracle()
        oracle.watched_addresses = {
            "0x742d35cc6634c0532925a3b844bc9e7595f0beb7"
        }
        oracle.source_w3 = MagicMock()

        # Mock trace result with internal call to watched address
        trace_result = {
            "result": {
                "type": "CALL",
                "from": "0x1111111111111111111111111111111111111111",
                "to": "0x2222222222222222222222222222222222222222",
                "calls": [
                    {
                        "type": "CALL",
                        "from": "0x2222222222222222222222222222222222222222",
                        "to": "0x742d35cc6634c0532925a3b844bc9e7595f0beb7",
                    }
                ],
            }
        }
        oracle.source_w3.provider.make_request = MagicMock(
            return_value=trace_result
        )

        result = await oracle._check_internal_transactions("0xtxhash")

        assert result is True
        oracle.source_w3.provider.make_request.assert_called_once_with(
            "debug_traceTransaction", ["0xtxhash", {"tracer": "callTracer"}]
        )

    @pytest.mark.asyncio
    async def test_check_internal_transactions_not_found(self):
        """Test internal transaction detection when no watched addresses involved."""
        oracle = HeaderOracle()
        oracle.watched_addresses = {
            "0x742d35cc6634c0532925a3b844bc9e7595f0beb7"
        }
        oracle.source_w3 = MagicMock()

        # Mock trace result with no watched addresses
        trace_result = {
            "result": {
                "type": "CALL",
                "from": "0x1111111111111111111111111111111111111111",
                "to": "0x2222222222222222222222222222222222222222",
                "calls": [
                    {
                        "type": "CALL",
                        "from": "0x2222222222222222222222222222222222222222",
                        "to": "0x3333333333333333333333333333333333333333",
                    }
                ],
            }
        }
        oracle.source_w3.provider.make_request = MagicMock(
            return_value=trace_result
        )

        result = await oracle._check_internal_transactions("0xtxhash")

        assert result is False

    @pytest.mark.asyncio
    async def test_check_internal_transactions_api_not_available(self):
        """Test graceful handling when debug API is not available."""
        oracle = HeaderOracle()
        oracle.watched_addresses = {
            "0x742d35cc6634c0532925a3b844bc9e7595f0beb7"
        }
        oracle.source_w3 = MagicMock()

        # Mock API error (not supported)
        oracle.source_w3.provider.make_request = MagicMock(
            side_effect=Exception("Method not found")
        )

        result = await oracle._check_internal_transactions("0xtxhash")

        # Should return False and not crash
        assert result is False

    @pytest.mark.asyncio
    async def test_check_trace_for_watched_addresses_nested(self):
        """Test recursive trace checking with nested calls."""
        oracle = HeaderOracle()
        oracle.watched_addresses = {
            "0x742d35cc6634c0532925a3b844bc9e7595f0beb7"
        }

        # Deeply nested trace with watched address
        trace = {
            "type": "CALL",
            "from": "0x1111111111111111111111111111111111111111",
            "to": "0x2222222222222222222222222222222222222222",
            "calls": [
                {
                    "type": "CALL",
                    "from": "0x2222222222222222222222222222222222222222",
                    "to": "0x3333333333333333333333333333333333333333",
                    "calls": [
                        {
                            "type": "CALL",
                            "from": "0x3333333333333333333333333333333333333333",
                            "to": "0x742d35cc6634c0532925a3b844bc9e7595f0beb7",
                        }
                    ],
                }
            ],
        }

        result = oracle._check_trace_for_watched_addresses(trace)

        assert result is True

    @pytest.mark.asyncio
    async def test_watcher_run_loop(self):
        """Test the watcher mode loop with interruption."""
        oracle = HeaderOracle()
        oracle.config = MagicMock()
        oracle.config.mode_config = WatcherModeConfig(
            watch_addresses=["0x742D35Cc6634C0532925A3B844bC9e7595f0bEB7"],
            scan_interval=0.1,  # Very short for testing
            batch_size=50,
            lookback_blocks=100,
        )

        # Mock watch_addresses_for_interactions
        oracle.watch_addresses_for_interactions = AsyncMock()

        # Track call count
        call_count = 0

        async def mock_watch():
            nonlocal call_count
            call_count += 1
            if call_count >= 3:  # Stop after 3 calls
                raise KeyboardInterrupt("Test interruption")

        oracle.watch_addresses_for_interactions.side_effect = mock_watch

        # Should not raise the KeyboardInterrupt
        await oracle._run_watcher_mode()

        # Should have been called multiple times
        assert oracle.watch_addresses_for_interactions.call_count >= 3


@pytest.fixture
def mock_token_watcher_config():
    """Create a mock token watcher config for token watcher mode."""
    return TokenWatcherModeConfig(
        token_addresses=[
            "0x742D35Cc6634C0532925A3B844bC9e7595f0bEB7",
            "0x1234567890123456789012345678901234567890",
        ],
        recipient_addresses=[
            "0xabcdef0123456789abcdef0123456789abcdef01",
            "0x9876543210987654321098765432109876543210",
        ],
        scan_interval=10,
    )


@pytest.fixture
def mock_oracle_config_token_watcher(
    mock_common_config, mock_token_watcher_config
):
    """Create a mock oracle config for token watcher mode."""
    return OracleConfig(
        common_config=mock_common_config,
        oracle_mode=OracleMode.TOKEN_WATCHER,
        mode_config=mock_token_watcher_config,
        local_mode=True,
        local_private_key="0x" + "a" * 64,
    )


class TestTokenWatcherMode:
    """Test suite for token watcher mode functionality."""

    @pytest.mark.asyncio
    async def test_token_watcher_config_detection(
        self, mock_oracle_config_token_watcher
    ):
        """Test that token watcher mode is correctly detected from config."""
        assert (
            mock_oracle_config_token_watcher.oracle_mode
            == OracleMode.TOKEN_WATCHER
        )
        assert isinstance(
            mock_oracle_config_token_watcher.mode_config, TokenWatcherModeConfig
        )
        assert (
            len(mock_oracle_config_token_watcher.mode_config.token_addresses)
            == 2
        )
        assert (
            len(
                mock_oracle_config_token_watcher.mode_config.recipient_addresses
            )
            == 2
        )

    @pytest.mark.asyncio
    async def test_token_watcher_config_validation(self):
        """Test token watcher config validates addresses and scan interval."""
        config = TokenWatcherModeConfig(
            token_addresses=["0x742D35Cc6634C0532925A3B844bC9e7595f0bEB7"],
            recipient_addresses=["0xabcdef0123456789abcdef0123456789abcdef01"],
            scan_interval=60,
        )
        assert len(config.token_addresses) == 1
        assert len(config.recipient_addresses) == 1
        assert config.scan_interval == 60

        with pytest.raises(ValueError, match="Invalid token address"):
            TokenWatcherModeConfig(
                token_addresses=["invalid-address"],
                recipient_addresses=[
                    "0xabcdef0123456789abcdef0123456789abcdef01"
                ],
                scan_interval=60,
            )

        with pytest.raises(ValueError, match="Invalid recipient address"):
            TokenWatcherModeConfig(
                token_addresses=["0x742D35Cc6634C0532925A3B844bC9e7595f0bEB7"],
                recipient_addresses=["invalid-address"],
                scan_interval=60,
            )

        with pytest.raises(
            ValueError,
            match="Token watcher mode requires at least one token address",
        ):
            TokenWatcherModeConfig(
                token_addresses=[],
                recipient_addresses=[
                    "0xabcdef0123456789abcdef0123456789abcdef01"
                ],
                scan_interval=60,
            )

        with pytest.raises(
            ValueError,
            match="Token watcher mode requires at least one recipient address",
        ):
            TokenWatcherModeConfig(
                token_addresses=["0x742D35Cc6634C0532925A3B844bC9e7595f0bEB7"],
                recipient_addresses=[],
                scan_interval=60,
            )

    @pytest.mark.asyncio
    async def test_token_watcher_initialization(
        self, mock_oracle_config_token_watcher
    ):
        """Test that HeaderOracle initializes correctly in token watcher mode."""
        with patch("rofl_oracle.header_oracle.Web3") as mock_web3_class:
            mock_source_w3 = MagicMock()
            mock_source_w3.is_connected.return_value = True
            mock_source_w3.eth.chain_id = 1337

            mock_web3_class.return_value = mock_source_w3

            with patch(
                "rofl_oracle.header_oracle.ContractUtility"
            ) as mock_contract_util_class:
                mock_contract_util = MagicMock()
                mock_contract_util.w3.eth.default_account = (
                    "0x1234567890123456789012345678901234567890"
                )
                mock_contract_util_class.return_value = mock_contract_util

                with patch(
                    "rofl_oracle.header_oracle.BlockSubmitter"
                ) as mock_block_submitter_class:
                    mock_block_submitter = MagicMock()
                    mock_block_submitter_class.return_value = (
                        mock_block_submitter
                    )

                    with patch(
                        "rofl_oracle.header_oracle.EventProcessor"
                    ) as mock_event_processor_class:
                        mock_event_processor = MagicMock()
                        mock_event_processor_class.return_value = (
                            mock_event_processor
                        )

                        oracle = await HeaderOracle.create(
                            mock_oracle_config_token_watcher
                        )

                        assert (
                            oracle.config.oracle_mode
                            == OracleMode.TOKEN_WATCHER
                        )
                        assert oracle.event_listener is None
                        assert oracle.block_requester_abi is None

    @pytest.mark.asyncio
    async def test_watch_token_transfers_first_run(self):
        """Test watching for token transfers when no blocks have been scanned yet."""
        oracle = HeaderOracle()
        oracle.config = MagicMock()
        oracle.config.mode_config = TokenWatcherModeConfig(
            token_addresses=["0x742D35Cc6634C0532925A3B844bC9e7595f0bEB7"],
            recipient_addresses=["0xabcdef0123456789abcdef0123456789abcdef01"],
            scan_interval=10,
        )
        oracle.last_scanned_block = None
        oracle.processed_tx_hashes = set()
        oracle.max_tx_cache_size = 1000

        mock_block_submitter = MagicMock()
        mock_block_submitter.submit_block_headers_batch = AsyncMock(
            return_value=True
        )
        oracle.block_submitter = mock_block_submitter

        oracle.source_w3 = MagicMock()
        oracle.source_w3.eth.block_number = 1000

        mock_log = {
            "transactionHash": b"\x12\x34" * 16,
            "blockNumber": 995,
        }
        oracle.source_w3.eth.get_logs.return_value = [mock_log]

        def mock_fetch_block(block_num):
            return {"number": block_num, "hash": f"0x{block_num:064x}"}

        oracle.fetch_block_by_number = AsyncMock(side_effect=mock_fetch_block)

        await oracle.watch_token_transfers()

        assert oracle.last_scanned_block == 1000
        mock_block_submitter.submit_block_headers_batch.assert_called_once_with(
            [995], [f"0x{995:064x}"]
        )

    @pytest.mark.asyncio
    async def test_watch_token_transfers_multiple_transfers(self):
        """Test watching for multiple token transfers in a range."""
        oracle = HeaderOracle()
        oracle.config = MagicMock()
        oracle.config.mode_config = TokenWatcherModeConfig(
            token_addresses=["0x742D35Cc6634C0532925A3B844bC9e7595f0bEB7"],
            recipient_addresses=["0xabcdef0123456789abcdef0123456789abcdef01"],
            scan_interval=10,
        )
        oracle.last_scanned_block = 990
        oracle.processed_tx_hashes = set()
        oracle.max_tx_cache_size = 1000

        mock_block_submitter = MagicMock()
        mock_block_submitter.submit_block_headers_batch = AsyncMock(
            return_value=True
        )
        oracle.block_submitter = mock_block_submitter

        oracle.source_w3 = MagicMock()
        oracle.source_w3.eth.block_number = 1000

        mock_logs = [
            {"transactionHash": b"\x12\x34" * 16, "blockNumber": 992},
            {"transactionHash": b"\x56\x78" * 16, "blockNumber": 995},
            {"transactionHash": b"\x9a\xbc" * 16, "blockNumber": 998},
        ]
        oracle.source_w3.eth.get_logs.return_value = mock_logs

        def mock_fetch_block(block_num):
            return {"number": block_num, "hash": f"0x{block_num:064x}"}

        oracle.fetch_block_by_number = AsyncMock(side_effect=mock_fetch_block)

        await oracle.watch_token_transfers()

        assert oracle.last_scanned_block == 1000
        mock_block_submitter.submit_block_headers_batch.assert_called_once_with(
            [992, 995, 998],
            [f"0x{992:064x}", f"0x{995:064x}", f"0x{998:064x}"],
        )

    @pytest.mark.asyncio
    async def test_watch_token_transfers_no_transfers(self):
        """Test when no token transfers are found."""
        oracle = HeaderOracle()
        oracle.config = MagicMock()
        oracle.config.mode_config = TokenWatcherModeConfig(
            token_addresses=["0x742D35Cc6634C0532925A3B844bC9e7595f0bEB7"],
            recipient_addresses=["0xabcdef0123456789abcdef0123456789abcdef01"],
            scan_interval=10,
        )
        oracle.last_scanned_block = 990
        oracle.processed_tx_hashes = set()
        oracle.max_tx_cache_size = 1000

        mock_block_submitter = MagicMock()
        mock_block_submitter.submit_block_headers_batch = AsyncMock()
        oracle.block_submitter = mock_block_submitter

        oracle.source_w3 = MagicMock()
        oracle.source_w3.eth.block_number = 1000
        oracle.source_w3.eth.get_logs.return_value = []

        oracle.fetch_block_by_number = AsyncMock()

        await oracle.watch_token_transfers()

        assert oracle.last_scanned_block == 1000
        mock_block_submitter.submit_block_headers_batch.assert_not_called()
        oracle.fetch_block_by_number.assert_not_called()

    @pytest.mark.asyncio
    async def test_watch_token_transfers_duplicate_tx_filtering(self):
        """Test that duplicate transactions are filtered out."""
        oracle = HeaderOracle()
        oracle.config = MagicMock()
        oracle.config.mode_config = TokenWatcherModeConfig(
            token_addresses=["0x742D35Cc6634C0532925A3B844bC9e7595f0bEB7"],
            recipient_addresses=["0xabcdef0123456789abcdef0123456789abcdef01"],
            scan_interval=10,
        )
        oracle.last_scanned_block = 990
        oracle.processed_tx_hashes = {"1234" * 16}
        oracle.max_tx_cache_size = 1000

        mock_block_submitter = MagicMock()
        mock_block_submitter.submit_block_headers_batch = AsyncMock(
            return_value=True
        )
        oracle.block_submitter = mock_block_submitter

        oracle.source_w3 = MagicMock()
        oracle.source_w3.eth.block_number = 1000

        mock_logs = [
            {"transactionHash": b"\x12\x34" * 16, "blockNumber": 992},
            {"transactionHash": b"\x56\x78" * 16, "blockNumber": 995},
        ]
        oracle.source_w3.eth.get_logs.return_value = mock_logs

        def mock_fetch_block(block_num):
            return {"number": block_num, "hash": f"0x{block_num:064x}"}

        oracle.fetch_block_by_number = AsyncMock(side_effect=mock_fetch_block)

        await oracle.watch_token_transfers()

        assert oracle.last_scanned_block == 1000
        mock_block_submitter.submit_block_headers_batch.assert_called_once_with(
            [995], [f"0x{995:064x}"]
        )

    @pytest.mark.asyncio
    async def test_watch_token_transfers_up_to_date(self):
        """Test when token watcher is already up to date."""
        oracle = HeaderOracle()
        oracle.config = MagicMock()
        oracle.config.mode_config = TokenWatcherModeConfig(
            token_addresses=["0x742D35Cc6634C0532925A3B844bC9e7595f0bEB7"],
            recipient_addresses=["0xabcdef0123456789abcdef0123456789abcdef01"],
            scan_interval=10,
        )
        oracle.last_scanned_block = 1000
        oracle.processed_tx_hashes = set()

        mock_block_submitter = MagicMock()
        mock_block_submitter.submit_block_headers_batch = AsyncMock()
        oracle.block_submitter = mock_block_submitter

        oracle.source_w3 = MagicMock()
        oracle.source_w3.eth.block_number = 1000

        oracle.source_w3.eth.get_logs = MagicMock()
        oracle.fetch_block_by_number = AsyncMock()

        await oracle.watch_token_transfers()

        oracle.source_w3.eth.get_logs.assert_not_called()
        mock_block_submitter.submit_block_headers_batch.assert_not_called()

    @pytest.mark.asyncio
    async def test_watch_token_transfers_batch_submission_failure(self):
        """Test handling of batch submission failures."""
        oracle = HeaderOracle()
        oracle.config = MagicMock()
        oracle.config.mode_config = TokenWatcherModeConfig(
            token_addresses=["0x742D35Cc6634C0532925A3B844bC9e7595f0bEB7"],
            recipient_addresses=["0xabcdef0123456789abcdef0123456789abcdef01"],
            scan_interval=10,
        )
        oracle.last_scanned_block = 990
        oracle.processed_tx_hashes = set()
        oracle.max_tx_cache_size = 1000

        mock_block_submitter = MagicMock()
        mock_block_submitter.submit_block_headers_batch = AsyncMock(
            return_value=False
        )
        oracle.block_submitter = mock_block_submitter

        oracle.source_w3 = MagicMock()
        oracle.source_w3.eth.block_number = 1000

        mock_log = {"transactionHash": b"\x12\x34" * 16, "blockNumber": 995}
        oracle.source_w3.eth.get_logs.return_value = [mock_log]

        def mock_fetch_block(block_num):
            return {"number": block_num, "hash": f"0x{block_num:064x}"}

        oracle.fetch_block_by_number = AsyncMock(side_effect=mock_fetch_block)

        await oracle.watch_token_transfers()

        assert oracle.last_scanned_block == 1000
        mock_block_submitter.submit_block_headers_batch.assert_called_once_with(
            [995], [f"0x{995:064x}"]
        )

    @pytest.mark.asyncio
    async def test_watch_token_transfers_error_handling(self):
        """Test error handling when get_logs fails."""
        oracle = HeaderOracle()
        oracle.config = MagicMock()
        oracle.config.mode_config = TokenWatcherModeConfig(
            token_addresses=["0x742D35Cc6634C0532925A3B844bC9e7595f0bEB7"],
            recipient_addresses=["0xabcdef0123456789abcdef0123456789abcdef01"],
            scan_interval=10,
        )
        oracle.last_scanned_block = 990
        oracle.processed_tx_hashes = set()

        mock_block_submitter = MagicMock()
        oracle.block_submitter = mock_block_submitter

        oracle.source_w3 = MagicMock()
        oracle.source_w3.eth.block_number = 1000
        oracle.source_w3.eth.get_logs.side_effect = Exception("RPC error")

        await oracle.watch_token_transfers()

        assert oracle.last_scanned_block == 1000

    @pytest.mark.asyncio
    async def test_watch_token_transfers_multiple_tokens_and_recipients(self):
        """Test watching multiple token contracts and recipients."""
        oracle = HeaderOracle()
        oracle.config = MagicMock()
        oracle.config.mode_config = TokenWatcherModeConfig(
            token_addresses=[
                "0x742D35Cc6634C0532925A3B844bC9e7595f0bEB7",
                "0x1234567890123456789012345678901234567890",
            ],
            recipient_addresses=[
                "0xabcdef0123456789abcdef0123456789abcdef01",
                "0x9876543210987654321098765432109876543210",
            ],
            scan_interval=10,
        )
        oracle.last_scanned_block = 990
        oracle.processed_tx_hashes = set()
        oracle.max_tx_cache_size = 1000

        mock_block_submitter = MagicMock()
        mock_block_submitter.submit_block_headers_batch = AsyncMock(
            return_value=True
        )
        oracle.block_submitter = mock_block_submitter

        oracle.source_w3 = MagicMock()
        oracle.source_w3.eth.block_number = 1000

        call_count = 0

        def mock_get_logs(filter_params):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return [
                    {"transactionHash": b"\x12\x34" * 16, "blockNumber": 992}
                ]
            elif call_count == 2:
                return [
                    {"transactionHash": b"\x56\x78" * 16, "blockNumber": 995}
                ]
            else:
                return []

        oracle.source_w3.eth.get_logs.side_effect = mock_get_logs

        def mock_fetch_block(block_num):
            return {"number": block_num, "hash": f"0x{block_num:064x}"}

        oracle.fetch_block_by_number = AsyncMock(side_effect=mock_fetch_block)

        await oracle.watch_token_transfers()

        assert call_count == 4
        assert oracle.last_scanned_block == 1000
        mock_block_submitter.submit_block_headers_batch.assert_called_once()

    @pytest.mark.asyncio
    async def test_watch_token_transfers_tx_cache_overflow(self):
        """Test that transaction cache is trimmed when it exceeds max size."""
        oracle = HeaderOracle()
        oracle.config = MagicMock()
        oracle.config.mode_config = TokenWatcherModeConfig(
            token_addresses=["0x742D35Cc6634C0532925A3B844bC9e7595f0bEB7"],
            recipient_addresses=["0xabcdef0123456789abcdef0123456789abcdef01"],
            scan_interval=10,
        )
        oracle.last_scanned_block = 990
        oracle.processed_tx_hashes = {f"tx{i}" for i in range(100)}
        oracle.max_tx_cache_size = 100

        mock_block_submitter = MagicMock()
        mock_block_submitter.submit_block_headers_batch = AsyncMock(
            return_value=True
        )
        oracle.block_submitter = mock_block_submitter

        oracle.source_w3 = MagicMock()
        oracle.source_w3.eth.block_number = 1000

        mock_log = {"transactionHash": b"\x12\x34" * 16, "blockNumber": 995}
        oracle.source_w3.eth.get_logs.return_value = [mock_log]

        def mock_fetch_block(block_num):
            return {"number": block_num, "hash": f"0x{block_num:064x}"}

        oracle.fetch_block_by_number = AsyncMock(side_effect=mock_fetch_block)

        await oracle.watch_token_transfers()

        assert len(oracle.processed_tx_hashes) <= oracle.max_tx_cache_size

    @pytest.mark.asyncio
    async def test_token_watcher_run_mode(
        self, mock_oracle_config_token_watcher
    ):
        """Test that HeaderOracle.run() uses token watcher mode correctly."""
        with patch(
            "rofl_oracle.header_oracle.HeaderOracle._run_token_watcher_mode"
        ) as mock_run_token_watcher:
            mock_run_token_watcher.return_value = None

            oracle = HeaderOracle()
            oracle.config = mock_oracle_config_token_watcher
            oracle.source_w3 = MagicMock()
            oracle.event_listener = None

            await oracle.run()

            mock_run_token_watcher.assert_called_once()

    @pytest.mark.asyncio
    async def test_token_watcher_run_loop(self):
        """Test the token watcher mode loop with interruption."""
        oracle = HeaderOracle()
        oracle.config = MagicMock()
        oracle.config.mode_config = TokenWatcherModeConfig(
            token_addresses=["0x742D35Cc6634C0532925A3B844bC9e7595f0bEB7"],
            recipient_addresses=["0xabcdef0123456789abcdef0123456789abcdef01"],
            scan_interval=0.1,
        )

        oracle.watch_token_transfers = AsyncMock()

        call_count = 0

        async def mock_watch():
            nonlocal call_count
            call_count += 1
            if call_count >= 3:
                raise KeyboardInterrupt("Test interruption")

        oracle.watch_token_transfers.side_effect = mock_watch

        await oracle._run_token_watcher_mode()

        assert oracle.watch_token_transfers.call_count >= 3

    @pytest.mark.asyncio
    async def test_watch_token_transfers_hex_string_tx_hash(self):
        """Test handling of transaction hash that's already a hex string."""
        oracle = HeaderOracle()
        oracle.config = MagicMock()
        oracle.config.mode_config = TokenWatcherModeConfig(
            token_addresses=["0x742D35Cc6634C0532925A3B844bC9e7595f0bEB7"],
            recipient_addresses=["0xabcdef0123456789abcdef0123456789abcdef01"],
            scan_interval=10,
        )
        oracle.last_scanned_block = 990
        oracle.processed_tx_hashes = set()
        oracle.max_tx_cache_size = 1000

        mock_block_submitter = MagicMock()
        mock_block_submitter.submit_block_headers_batch = AsyncMock(
            return_value=True
        )
        oracle.block_submitter = mock_block_submitter

        oracle.source_w3 = MagicMock()
        oracle.source_w3.eth.block_number = 1000

        mock_log = {
            "transactionHash": "0x" + "1234" * 16,
            "blockNumber": 995,
        }
        oracle.source_w3.eth.get_logs.return_value = [mock_log]

        def mock_fetch_block(block_num):
            return {"number": block_num, "hash": f"0x{block_num:064x}"}

        oracle.fetch_block_by_number = AsyncMock(side_effect=mock_fetch_block)

        await oracle.watch_token_transfers()

        assert "0x" + "1234" * 16 in oracle.processed_tx_hashes
        mock_block_submitter.submit_block_headers_batch.assert_called_once_with(
            [995], [f"0x{995:064x}"]
        )
