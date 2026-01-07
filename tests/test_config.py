#!/usr/bin/env python3
"""Tests for the configuration module."""

import logging
import os
from unittest.mock import patch

import pytest

from rofl_oracle.config import (
    CommonConfig,
    EventListenerModeConfig,
    OracleConfig,
    PushModeConfig,
    WatcherModeConfig,
)


class TestCommonConfig:
    """Tests for CommonConfig."""

    #     source_rpc_url: str           # HTTP(S) RPC endpoint for the source chain
    # source_chain_id: int  # Chain ID for the source chain (optional)
    # target_rpc_url: str           # HTTP(S) RPC endpoint for the target chain
    # request_timeout: int          # HTTP request timeout in seconds
    # retry_count: int              # retry attempts for operations
    # target_contract_address: str  # contract address of ROFL Adapter on target chain

    def test_valid_common_config(self):
        """Test creating a valid source chain configuration."""
        config = CommonConfig(
            source_rpc_url="https://ethereum.publicnode.com",
            source_chain_id=None,
            target_rpc_url="https://sapphire.oasis.io",
            request_timeout=30,
            retry_count=3,
            target_contract_address="0x85BfE05492aFC3D04Ff3B2ca6771ACF6f853d90d",
        )

        assert config.source_rpc_url == "https://ethereum.publicnode.com"
        assert (
            config.target_contract_address
            == "0x85BfE05492aFC3D04Ff3B2ca6771ACF6f853d90d"
        )
        assert config.source_chain_id is None  # Not set until connecting to RPC
        assert config.target_rpc_url == "https://sapphire.oasis.io"
        assert config.request_timeout == 30
        assert config.retry_count == 3

    def test_checksum_address_conversion(self):
        """Test that addresses are converted to checksum format."""
        # Lowercase address should be converted
        config = CommonConfig(
            source_rpc_url="https://test.rpc",
            source_chain_id=None,
            target_rpc_url="https://sapphire.oasis.io",
            request_timeout=30,
            retry_count=3,
            target_contract_address="0x85bfe05492afc3d04ff3b2ca6771acf6f853d90d",  # lowercase
        )

        # Should be converted to checksum format
        assert (
            config.target_contract_address
            == "0x85BfE05492aFC3D04Ff3B2ca6771ACF6f853d90d"
        )

    def test_invalid_rpc_url_scheme(self):
        """Test that invalid RPC URL schemes are rejected."""
        with pytest.raises(ValueError, match="Invalid RPC URL scheme"):
            CommonConfig(
                source_rpc_url="ftp://invalid-scheme",
                source_chain_id=None,
                target_rpc_url="https://sapphire.oasis.io",
                request_timeout=30,
                retry_count=3,
                target_contract_address="0x85bfe05492afc3d04ff3b2ca6771acf6f853d90d",  # lowercase
            )
        with pytest.raises(ValueError, match="Invalid RPC URL scheme"):
            CommonConfig(
                source_rpc_url="https://test.rpc",
                source_chain_id=None,
                target_rpc_url="ftp://invalid-scheme",
                request_timeout=30,
                retry_count=3,
                target_contract_address="0x85bfe05492afc3d04ff3b2ca6771acf6f853d90d",  # lowercase
            )

    def test_missing_rpc_url(self):
        """Test that missing RPC URL raises an error."""
        with pytest.raises(ValueError, match="Source RPC URL is required"):
            CommonConfig(
                source_rpc_url="",
                source_chain_id="None",
                target_rpc_url="https://sapphire.oasis.io",
                request_timeout=30,
                retry_count=3,
                target_contract_address="0x85BfE05492aFC3D04Ff3B2ca6771ACF6f853d90d",
            )

        with pytest.raises(ValueError, match="Target RPC URL is required"):
            CommonConfig(
                source_rpc_url="https://test.rpc",
                source_chain_id=None,
                target_rpc_url="",
                request_timeout=30,
                retry_count=3,
                target_contract_address="0x85BfE05492aFC3D04Ff3B2ca6771ACF6f853d90d",
            )

    def test_invalid_contract_address(self):
        """Test that invalid contract address raises an error."""
        with pytest.raises(
            ValueError, match="Invalid target contract address: invalid-address"
        ):
            CommonConfig(
                source_rpc_url="https://test.rpc",
                source_chain_id=None,
                target_rpc_url="https://sapphire.oasis.io",
                request_timeout=30,
                retry_count=3,
                target_contract_address="invalid-address",
            )

    def test_missing_contract_address(self):
        """Test that missing contract address raises an error."""
        with pytest.raises(
            ValueError,
            match=r"Target contract address is required \(ROFL_ADAPTER_ADDRESS\)",
        ):
            CommonConfig(
                source_rpc_url="https://test.rpc",
                source_chain_id=None,
                target_rpc_url="https://sapphire.oasis.io",
                request_timeout=30,
                retry_count=3,
                target_contract_address=None,
            )

    def test_websocket_rpc_url(self):
        """Test that WebSocket URLs are accepted."""
        config = CommonConfig(
            source_rpc_url="wss://ethereum.publicnode.com",
            source_chain_id=None,
            target_rpc_url="https://sapphire.oasis.io",
            request_timeout=30,
            retry_count=3,
            target_contract_address="0x85BfE05492aFC3D04Ff3B2ca6771ACF6f853d90d",
        )

        assert config.source_rpc_url == "wss://ethereum.publicnode.com"


class TestWatcherModeConfig:
    """Tests for WatcherModeConfig."""

    # watch_addresses: list[str]  # Addresses to watch in watcher mode
    # scan_interval: int          # seconds between scanning for interactions
    # batch_size: int = 50        # max blocks to scan per iteration
    # lookback_blocks: int = 100  # blocks to look back on first run

    def test_valid_watcher_config(self):
        """Test creating a valid watcher configuration."""
        config = WatcherModeConfig(
            watch_addresses=["0x85BfE05492aFC3D04Ff3B2ca6771ACF6f853d90d"],
            scan_interval=60,
            batch_size=50,
            lookback_blocks=100,
        )

        assert len(config.watch_addresses) == 1
        assert (
            config.watch_addresses[0]
            == "0x85BfE05492aFC3D04Ff3B2ca6771ACF6f853d90d"
        )
        assert config.scan_interval == 60
        assert config.batch_size == 50
        assert config.lookback_blocks == 100

    def test_multiple_watch_addresses(self):
        """Test watcher config with multiple addresses."""
        addresses = [
            "0x85BfE05492aFC3D04Ff3B2ca6771ACF6f853d90d",
            "0x742d35Cc6634C0532925a3b844Bc9e7595f0bEb0",
        ]
        config = WatcherModeConfig(
            watch_addresses=addresses,
            scan_interval=30,
        )

        assert len(config.watch_addresses) == 2
        assert (
            config.watch_addresses[0]
            == "0x85BfE05492aFC3D04Ff3B2ca6771ACF6f853d90d"
        )
        assert (
            config.watch_addresses[1]
            == "0x742D35CC6634c0532925A3b844BC9E7595F0BEb0"
        )

    def test_checksum_watch_addresses(self):
        """Test that watch addresses are converted to checksum format."""
        # Lowercase addresses should be converted
        config = WatcherModeConfig(
            watch_addresses=[
                "0x85bfe05492afc3d04ff3b2ca6771acf6f853d90d",  # lowercase
                "0x742d35cc6634c0532925a3b844bc9e7595f0beb0",  # lowercase
            ],
            scan_interval=60,
        )

        # Should be converted to checksum format
        assert (
            config.watch_addresses[0]
            == "0x85BfE05492aFC3D04Ff3B2ca6771ACF6f853d90d"
        )
        assert (
            config.watch_addresses[1]
            == "0x742D35CC6634c0532925A3b844BC9E7595F0BEb0"
        )

    def test_default_batch_size(self):
        """Test default batch size."""
        config = WatcherModeConfig(
            watch_addresses=["0x85BfE05492aFC3D04Ff3B2ca6771ACF6f853d90d"],
            scan_interval=60,
        )

        assert config.batch_size == 50  # Default value

    def test_default_lookback_blocks(self):
        """Test default lookback blocks."""
        config = WatcherModeConfig(
            watch_addresses=["0x85BfE05492aFC3D04Ff3B2ca6771ACF6f853d90d"],
            scan_interval=60,
        )

        assert config.lookback_blocks == 100  # Default value

    def test_empty_watch_addresses(self):
        """Test that empty watch addresses list raises an error."""
        with pytest.raises(
            ValueError, match="Watcher mode requires at least one watch address"
        ):
            WatcherModeConfig(
                watch_addresses=[],
                scan_interval=60,
            )

    def test_none_watch_addresses(self):
        """Test that None watch addresses raises an error."""
        with pytest.raises(
            ValueError, match="Watcher mode requires at least one watch address"
        ):
            WatcherModeConfig(
                watch_addresses=None,
                scan_interval=60,
            )

    def test_invalid_watch_address(self):
        """Test that invalid watch address raises an error."""
        with pytest.raises(ValueError, match="Invalid watch address"):
            WatcherModeConfig(
                watch_addresses=["invalid-address"],
                scan_interval=60,
            )

    def test_scan_interval_validation_zero(self):
        """Test that zero scan interval raises an error."""
        with pytest.raises(ValueError, match="Scan interval must be positive"):
            WatcherModeConfig(
                watch_addresses=["0x85BfE05492aFC3D04Ff3B2ca6771ACF6f853d90d"],
                scan_interval=0,
            )

    def test_scan_interval_validation_negative(self):
        """Test that negative scan interval raises an error."""
        with pytest.raises(ValueError, match="Scan interval must be positive"):
            WatcherModeConfig(
                watch_addresses=["0x85BfE05492aFC3D04Ff3B2ca6771ACF6f853d90d"],
                scan_interval=-1,
            )

    def test_scan_interval_validation_too_long(self):
        """Test that scan interval over 300 seconds raises an error."""
        with pytest.raises(ValueError, match="Scan interval too long"):
            WatcherModeConfig(
                watch_addresses=["0x85BfE05492aFC3D04Ff3B2ca6771ACF6f853d90d"],
                scan_interval=301,
            )

    def test_batch_size_validation_zero(self):
        """Test that zero batch size raises an error."""
        with pytest.raises(ValueError, match="Batch size must be positive"):
            WatcherModeConfig(
                watch_addresses=["0x85BfE05492aFC3D04Ff3B2ca6771ACF6f853d90d"],
                scan_interval=60,
                batch_size=0,
            )

    def test_batch_size_validation_negative(self):
        """Test that negative batch size raises an error."""
        with pytest.raises(ValueError, match="Batch size must be positive"):
            WatcherModeConfig(
                watch_addresses=["0x85BfE05492aFC3D04Ff3B2ca6771ACF6f853d90d"],
                scan_interval=60,
                batch_size=-1,
            )

    def test_batch_size_validation_too_high(self):
        """Test that batch size over 200 raises an error."""
        with pytest.raises(ValueError, match="Batch size too high"):
            WatcherModeConfig(
                watch_addresses=["0x85BfE05492aFC3D04Ff3B2ca6771ACF6f853d90d"],
                scan_interval=60,
                batch_size=201,
            )

    def test_lookback_blocks_validation_zero(self):
        """Test that zero lookback blocks raises an error."""
        with pytest.raises(
            ValueError, match="Lookback blocks must be positive"
        ):
            WatcherModeConfig(
                watch_addresses=["0x85BfE05492aFC3D04Ff3B2ca6771ACF6f853d90d"],
                scan_interval=60,
                lookback_blocks=0,
            )

    def test_lookback_blocks_validation_negative(self):
        """Test that negative lookback blocks raises an error."""
        with pytest.raises(
            ValueError, match="Lookback blocks must be positive"
        ):
            WatcherModeConfig(
                watch_addresses=["0x85BfE05492aFC3D04Ff3B2ca6771ACF6f853d90d"],
                scan_interval=60,
                lookback_blocks=-1,
            )

    def test_lookback_blocks_validation_too_high(self):
        """Test that lookback blocks over 1000 raises an error."""
        with pytest.raises(ValueError, match="Lookback blocks too high"):
            WatcherModeConfig(
                watch_addresses=["0x85BfE05492aFC3D04Ff3B2ca6771ACF6f853d90d"],
                scan_interval=60,
                lookback_blocks=1001,
            )

    def test_immutability(self):
        """Test that watcher configuration is immutable."""
        config = WatcherModeConfig(
            watch_addresses=["0x85BfE05492aFC3D04Ff3B2ca6771ACF6f853d90d"],
            scan_interval=60,
        )

        # Cannot modify attributes
        with pytest.raises(AttributeError):
            config.scan_interval = 120

        with pytest.raises(AttributeError):
            config.batch_size = 100

    def test_default_heartbeat_interval(self):
        """Test default heartbeat interval."""
        config = WatcherModeConfig(
            watch_addresses=["0x85BfE05492aFC3D04Ff3B2ca6771ACF6f853d90d"],
            scan_interval=60,
        )

        assert config.heartbeat_interval_seconds == 3600  # Default value

    def test_custom_heartbeat_interval(self):
        """Test custom heartbeat interval values."""
        config = WatcherModeConfig(
            watch_addresses=["0x85BfE05492aFC3D04Ff3B2ca6771ACF6f853d90d"],
            scan_interval=60,
            heartbeat_interval_seconds=7200,
        )

        assert config.heartbeat_interval_seconds == 7200

    def test_heartbeat_interval_validation_zero(self):
        """Test that zero heartbeat interval raises an error."""
        with pytest.raises(
            ValueError, match="Heartbeat interval must be positive"
        ):
            WatcherModeConfig(
                watch_addresses=["0x85BfE05492aFC3D04Ff3B2ca6771ACF6f853d90d"],
                scan_interval=60,
                heartbeat_interval_seconds=0,
            )

    def test_heartbeat_interval_validation_negative(self):
        """Test that negative heartbeat interval raises an error."""
        with pytest.raises(
            ValueError, match="Heartbeat interval must be positive"
        ):
            WatcherModeConfig(
                watch_addresses=["0x85BfE05492aFC3D04Ff3B2ca6771ACF6f853d90d"],
                scan_interval=60,
                heartbeat_interval_seconds=-1,
            )

    def test_heartbeat_interval_validation_too_high(self):
        """Test that heartbeat interval over 86400 raises an error."""
        with pytest.raises(ValueError, match="Heartbeat interval too high"):
            WatcherModeConfig(
                watch_addresses=["0x85BfE05492aFC3D04Ff3B2ca6771ACF6f853d90d"],
                scan_interval=60,
                heartbeat_interval_seconds=86401,
            )

    def test_heartbeat_interval_at_max(self):
        """Test that heartbeat interval at exactly 86400 is valid."""
        config = WatcherModeConfig(
            watch_addresses=["0x85BfE05492aFC3D04Ff3B2ca6771ACF6f853d90d"],
            scan_interval=60,
            heartbeat_interval_seconds=86400,
        )

        assert config.heartbeat_interval_seconds == 86400


class TestPushModeConfig:
    """Tests for PushModeConfig."""

    # push_interval: int  # seconds between block pushes
    # batch_size: int = 20  # max blocks to push per iteration

    def test_valid_push_oracle_config(self):
        """Test creating a valid push oracle configuration."""
        config = PushModeConfig(
            push_interval=60,
            batch_size=20,
        )

        assert config.push_interval == 60
        assert config.batch_size == 20

    def test_default_batch_size(self):
        """Test default batch size."""
        config = PushModeConfig(
            push_interval=60,
        )

        assert config.batch_size == 20  # Default value

    def test_custom_batch_size(self):
        """Test custom batch size."""
        config = PushModeConfig(
            push_interval=30,
            batch_size=50,
        )

        assert config.push_interval == 30
        assert config.batch_size == 50

    def test_push_interval_validation_zero(self):
        """Test that zero push interval raises an error."""
        with pytest.raises(ValueError, match="Push interval must be positive"):
            PushModeConfig(
                push_interval=0,
            )

    def test_push_interval_validation_negative(self):
        """Test that negative push interval raises an error."""
        with pytest.raises(ValueError, match="Push interval must be positive"):
            PushModeConfig(
                push_interval=-1,
            )

    def test_push_interval_validation_too_long(self):
        """Test that push interval over 300 seconds raises an error."""
        with pytest.raises(ValueError, match="Push interval too long"):
            PushModeConfig(
                push_interval=301,
            )

    def test_push_interval_at_max(self):
        """Test that push interval at exactly 300 seconds is valid."""
        config = PushModeConfig(
            push_interval=300,
        )

        assert config.push_interval == 300

    def test_batch_size_validation_zero(self):
        """Test that zero batch size raises an error."""
        with pytest.raises(ValueError, match="Batch size must be positive"):
            PushModeConfig(
                push_interval=60,
                batch_size=0,
            )

    def test_batch_size_validation_negative(self):
        """Test that negative batch size raises an error."""
        with pytest.raises(ValueError, match="Batch size must be positive"):
            PushModeConfig(
                push_interval=60,
                batch_size=-1,
            )

    def test_batch_size_validation_too_high(self):
        """Test that batch size over 100 raises an error."""
        with pytest.raises(ValueError, match="Batch size too high"):
            PushModeConfig(
                push_interval=60,
                batch_size=101,
            )

    def test_batch_size_at_max(self):
        """Test that batch size at exactly 100 is valid."""
        config = PushModeConfig(
            push_interval=60,
            batch_size=100,
        )

        assert config.batch_size == 100

    def test_minimum_valid_values(self):
        """Test configuration with minimum valid values."""
        config = PushModeConfig(
            push_interval=1,
            batch_size=1,
        )

        assert config.push_interval == 1
        assert config.batch_size == 1

    def test_maximum_valid_values(self):
        """Test configuration with maximum valid values."""
        config = PushModeConfig(
            push_interval=300,
            batch_size=100,
        )

        assert config.push_interval == 300
        assert config.batch_size == 100

    def test_immutability(self):
        """Test that push oracle configuration is immutable."""
        config = PushModeConfig(
            push_interval=60,
            batch_size=20,
        )

        # Cannot modify attributes
        with pytest.raises(AttributeError):
            config.push_interval = 120

        with pytest.raises(AttributeError):
            config.batch_size = 50


class TestEventListenerModeConfig:
    """Tests for EventListenerModeConfig."""

    # polling_interval: int  # seconds between event polls
    # lookback_blocks: int   # blocks to look back on startup
    # contract_address: str  # contract address to listen to for BlockHeaderRequested events

    def test_valid_event_listener_config(self):
        """Test creating a valid event listener configuration."""
        config = EventListenerModeConfig(
            polling_interval=12,
            lookback_blocks=100,
            contract_address="0x85BfE05492aFC3D04Ff3B2ca6771ACF6f853d90d",
        )

        assert config.polling_interval == 12
        assert config.lookback_blocks == 100
        assert (
            config.contract_address
            == "0x85BfE05492aFC3D04Ff3B2ca6771ACF6f853d90d"
        )

    def test_checksum_contract_address(self):
        """Test that contract address is converted to checksum format."""
        # Lowercase address should be converted
        config = EventListenerModeConfig(
            polling_interval=12,
            lookback_blocks=100,
            contract_address="0x85bfe05492afc3d04ff3b2ca6771acf6f853d90d",  # lowercase
        )

        # Should be converted to checksum format
        assert (
            config.contract_address
            == "0x85BfE05492aFC3D04Ff3B2ca6771ACF6f853d90d"
        )

    def test_empty_contract_address(self):
        """Test that empty contract address raises an error."""
        with pytest.raises(
            ValueError,
            match="Contract address for event listener mode cannot be empty",
        ):
            EventListenerModeConfig(
                polling_interval=12,
                lookback_blocks=100,
                contract_address="",
            )

    def test_invalid_contract_address(self):
        """Test that invalid contract address raises an error."""
        with pytest.raises(ValueError, match="Invalid source contract address"):
            EventListenerModeConfig(
                polling_interval=12,
                lookback_blocks=100,
                contract_address="invalid-address",
            )

    def test_polling_interval_validation_zero(self):
        """Test that zero polling interval raises an error."""
        with pytest.raises(
            ValueError, match="Polling interval must be positive"
        ):
            EventListenerModeConfig(
                polling_interval=0,
                lookback_blocks=100,
                contract_address="0x85BfE05492aFC3D04Ff3B2ca6771ACF6f853d90d",
            )

    def test_polling_interval_validation_negative(self):
        """Test that negative polling interval raises an error."""
        with pytest.raises(
            ValueError, match="Polling interval must be positive"
        ):
            EventListenerModeConfig(
                polling_interval=-1,
                lookback_blocks=100,
                contract_address="0x85BfE05492aFC3D04Ff3B2ca6771ACF6f853d90d",
            )

    def test_polling_interval_validation_too_long(self):
        """Test that polling interval over 300 seconds raises an error."""
        with pytest.raises(ValueError, match="Polling interval too long"):
            EventListenerModeConfig(
                polling_interval=301,
                lookback_blocks=100,
                contract_address="0x85BfE05492aFC3D04Ff3B2ca6771ACF6f853d90d",
            )

    def test_polling_interval_at_max(self):
        """Test that polling interval at exactly 300 seconds is valid."""
        config = EventListenerModeConfig(
            polling_interval=300,
            lookback_blocks=100,
            contract_address="0x85BfE05492aFC3D04Ff3B2ca6771ACF6f853d90d",
        )

        assert config.polling_interval == 300

    def test_lookback_blocks_validation_zero(self):
        """Test that zero lookback blocks raises an error."""
        with pytest.raises(
            ValueError, match="Lookback blocks must be positive"
        ):
            EventListenerModeConfig(
                polling_interval=12,
                lookback_blocks=0,
                contract_address="0x85BfE05492aFC3D04Ff3B2ca6771ACF6f853d90d",
            )

    def test_lookback_blocks_validation_negative(self):
        """Test that negative lookback blocks raises an error."""
        with pytest.raises(
            ValueError, match="Lookback blocks must be positive"
        ):
            EventListenerModeConfig(
                polling_interval=12,
                lookback_blocks=-1,
                contract_address="0x85BfE05492aFC3D04Ff3B2ca6771ACF6f853d90d",
            )

    def test_lookback_blocks_validation_too_high(self):
        """Test that lookback blocks over 1000 raises an error."""
        with pytest.raises(ValueError, match="Lookback blocks too high"):
            EventListenerModeConfig(
                polling_interval=12,
                lookback_blocks=1001,
                contract_address="0x85BfE05492aFC3D04Ff3B2ca6771ACF6f853d90d",
            )

    def test_lookback_blocks_at_max(self):
        """Test that lookback blocks at exactly 1000 is valid."""
        config = EventListenerModeConfig(
            polling_interval=12,
            lookback_blocks=1000,
            contract_address="0x85BfE05492aFC3D04Ff3B2ca6771ACF6f853d90d",
        )

        assert config.lookback_blocks == 1000

    def test_minimum_valid_values(self):
        """Test configuration with minimum valid values."""
        config = EventListenerModeConfig(
            polling_interval=1,
            lookback_blocks=1,
            contract_address="0x85BfE05492aFC3D04Ff3B2ca6771ACF6f853d90d",
        )

        assert config.polling_interval == 1
        assert config.lookback_blocks == 1

    def test_maximum_valid_values(self):
        """Test configuration with maximum valid values."""
        config = EventListenerModeConfig(
            polling_interval=300,
            lookback_blocks=1000,
            contract_address="0x85BfE05492aFC3D04Ff3B2ca6771ACF6f853d90d",
        )

        assert config.polling_interval == 300
        assert config.lookback_blocks == 1000

    def test_immutability(self):
        """Test that event listener configuration is immutable."""
        config = EventListenerModeConfig(
            polling_interval=12,
            lookback_blocks=100,
            contract_address="0x85BfE05492aFC3D04Ff3B2ca6771ACF6f853d90d",
        )

        # Cannot modify attributes
        with pytest.raises(AttributeError):
            config.polling_interval = 24

        with pytest.raises(AttributeError):
            config.lookback_blocks = 200

        with pytest.raises(AttributeError):
            config.contract_address = (
                "0x742d35Cc6634C0532925a3b844Bc9e7595f0bEb0"
            )


class TestOracleConfig:
    """Tests for OracleConfig."""

    def test_valid_event_listener_config(self):
        """Test creating a valid oracle configuration in event listener mode."""
        from rofl_oracle.config import OracleMode

        common = CommonConfig(
            source_rpc_url="https://test.rpc",
            source_chain_id=None,
            target_rpc_url="https://testnet.sapphire.oasis.io",
            request_timeout=30,
            retry_count=3,
            target_contract_address="0x85BfE05492aFC3D04Ff3B2ca6771ACF6f853d90d",
        )
        event_listener = EventListenerModeConfig(
            polling_interval=12,
            lookback_blocks=100,
            contract_address="0x85BfE05492aFC3D04Ff3B2ca6771ACF6f853d90d",
        )

        config = OracleConfig(
            common_config=common,
            oracle_mode=OracleMode.EVENT_LISTENER,
            mode_config=event_listener,
        )

        assert config.common_config == common
        assert config.oracle_mode == OracleMode.EVENT_LISTENER
        assert isinstance(config.mode_config, EventListenerModeConfig)
        assert config.mode_config.polling_interval == 12
        assert config.local_mode is False
        assert config.local_private_key is None

    def test_valid_push_oracle_config(self):
        """Test creating a valid oracle configuration in push mode."""
        from rofl_oracle.config import OracleMode

        common = CommonConfig(
            source_rpc_url="https://test.rpc",
            source_chain_id=None,
            target_rpc_url="https://testnet.sapphire.oasis.io",
            request_timeout=30,
            retry_count=3,
            target_contract_address="0x85BfE05492aFC3D04Ff3B2ca6771ACF6f853d90d",
        )
        push = PushModeConfig(
            push_interval=60,
            batch_size=20,
        )

        config = OracleConfig(
            common_config=common,
            oracle_mode=OracleMode.PUSH,
            mode_config=push,
        )

        assert config.common_config == common
        assert config.oracle_mode == OracleMode.PUSH
        assert isinstance(config.mode_config, PushModeConfig)
        assert config.mode_config.push_interval == 60
        assert config.local_mode is False

    def test_valid_watcher_config(self):
        """Test creating a valid oracle configuration in watcher mode."""
        from rofl_oracle.config import OracleMode

        common = CommonConfig(
            source_rpc_url="https://test.rpc",
            source_chain_id=None,
            target_rpc_url="https://testnet.sapphire.oasis.io",
            request_timeout=30,
            retry_count=3,
            target_contract_address="0x85BfE05492aFC3D04Ff3B2ca6771ACF6f853d90d",
        )
        watcher = WatcherModeConfig(
            watch_addresses=["0x85BfE05492aFC3D04Ff3B2ca6771ACF6f853d90d"],
            scan_interval=60,
        )

        config = OracleConfig(
            common_config=common,
            oracle_mode=OracleMode.WATCHER,
            mode_config=watcher,
        )

        assert config.common_config == common
        assert config.oracle_mode == OracleMode.WATCHER
        assert isinstance(config.mode_config, WatcherModeConfig)
        assert config.mode_config.scan_interval == 60

    def test_mode_config_mismatch_event_listener(self):
        """Test that event listener mode requires EventListenerModeConfig."""
        from rofl_oracle.config import OracleMode

        common = CommonConfig(
            source_rpc_url="https://test.rpc",
            source_chain_id=None,
            target_rpc_url="https://testnet.sapphire.oasis.io",
            request_timeout=30,
            retry_count=3,
            target_contract_address="0x85BfE05492aFC3D04Ff3B2ca6771ACF6f853d90d",
        )
        push = PushModeConfig(push_interval=60)

        with pytest.raises(
            ValueError,
            match="Event listener mode requires EventListenerModeConfig",
        ):
            OracleConfig(
                common_config=common,
                oracle_mode=OracleMode.EVENT_LISTENER,
                mode_config=push,  # Wrong config type
            )

    def test_mode_config_mismatch_push(self):
        """Test that push mode requires PushModeConfig."""
        from rofl_oracle.config import OracleMode

        common = CommonConfig(
            source_rpc_url="https://test.rpc",
            source_chain_id=None,
            target_rpc_url="https://testnet.sapphire.oasis.io",
            request_timeout=30,
            retry_count=3,
            target_contract_address="0x85BfE05492aFC3D04Ff3B2ca6771ACF6f853d90d",
        )
        watcher = WatcherModeConfig(
            watch_addresses=["0x85BfE05492aFC3D04Ff3B2ca6771ACF6f853d90d"],
            scan_interval=60,
        )

        with pytest.raises(
            ValueError, match="Push oracle mode requires PushModeConfig"
        ):
            OracleConfig(
                common_config=common,
                oracle_mode=OracleMode.PUSH,
                mode_config=watcher,  # Wrong config type
            )

    def test_mode_config_mismatch_watcher(self):
        """Test that watcher mode requires WatcherModeConfig."""
        from rofl_oracle.config import OracleMode

        common = CommonConfig(
            source_rpc_url="https://test.rpc",
            source_chain_id=None,
            target_rpc_url="https://testnet.sapphire.oasis.io",
            request_timeout=30,
            retry_count=3,
            target_contract_address="0x85BfE05492aFC3D04Ff3B2ca6771ACF6f853d90d",
        )
        event_listener = EventListenerModeConfig(
            polling_interval=12,
            lookback_blocks=100,
            contract_address="0x85BfE05492aFC3D04Ff3B2ca6771ACF6f853d90d",
        )

        with pytest.raises(
            ValueError, match="Watcher mode requires WatcherModeConfig"
        ):
            OracleConfig(
                common_config=common,
                oracle_mode=OracleMode.WATCHER,
                mode_config=event_listener,  # Wrong config type
            )

    def test_local_mode_requires_private_key(self):
        """Test that local mode requires a private key."""
        from rofl_oracle.config import OracleMode

        common = CommonConfig(
            source_rpc_url="https://test.rpc",
            source_chain_id=None,
            target_rpc_url="https://testnet.sapphire.oasis.io",
            request_timeout=30,
            retry_count=3,
            target_contract_address="0x85BfE05492aFC3D04Ff3B2ca6771ACF6f853d90d",
        )
        push = PushModeConfig(push_interval=60)

        with pytest.raises(
            ValueError, match="Local mode requires LOCAL_PRIVATE_KEY"
        ):
            OracleConfig(
                common_config=common,
                oracle_mode=OracleMode.PUSH,
                mode_config=push,
                local_mode=True,
                local_private_key=None,
            )

    def test_valid_private_key(self):
        """Test valid private key format."""
        from rofl_oracle.config import OracleMode

        common = CommonConfig(
            source_rpc_url="https://test.rpc",
            source_chain_id=None,
            target_rpc_url="https://testnet.sapphire.oasis.io",
            request_timeout=30,
            retry_count=3,
            target_contract_address="0x85BfE05492aFC3D04Ff3B2ca6771ACF6f853d90d",
        )
        push = PushModeConfig(push_interval=60)

        # Valid key with 0x prefix
        config = OracleConfig(
            common_config=common,
            oracle_mode=OracleMode.PUSH,
            mode_config=push,
            local_mode=True,
            local_private_key="0x" + "a" * 64,
        )
        assert config.local_private_key == "0x" + "a" * 64

        # Valid key without prefix
        config = OracleConfig(
            common_config=common,
            oracle_mode=OracleMode.PUSH,
            mode_config=push,
            local_mode=True,
            local_private_key="b" * 64,
        )
        assert config.local_private_key == "b" * 64

    def test_invalid_private_key_length(self):
        """Test invalid private key length."""
        from rofl_oracle.config import OracleMode

        common = CommonConfig(
            source_rpc_url="https://test.rpc",
            source_chain_id=None,
            target_rpc_url="https://testnet.sapphire.oasis.io",
            request_timeout=30,
            retry_count=3,
            target_contract_address="0x85BfE05492aFC3D04Ff3B2ca6771ACF6f853d90d",
        )
        push = PushModeConfig(push_interval=60)

        with pytest.raises(ValueError, match="Invalid private key length"):
            OracleConfig(
                common_config=common,
                oracle_mode=OracleMode.PUSH,
                mode_config=push,
                local_mode=True,
                local_private_key="0x" + "a" * 63,  # Too short
            )

    def test_invalid_private_key_format(self):
        """Test invalid private key format."""
        from rofl_oracle.config import OracleMode

        common = CommonConfig(
            source_rpc_url="https://test.rpc",
            source_chain_id=None,
            target_rpc_url="https://testnet.sapphire.oasis.io",
            request_timeout=30,
            retry_count=3,
            target_contract_address="0x85BfE05492aFC3D04Ff3B2ca6771ACF6f853d90d",
        )
        push = PushModeConfig(push_interval=60)

        with pytest.raises(ValueError, match="Invalid private key format"):
            OracleConfig(
                common_config=common,
                oracle_mode=OracleMode.PUSH,
                mode_config=push,
                local_mode=True,
                local_private_key="0x" + "g" * 64,  # Invalid hex
            )

    @patch.dict(
        os.environ,
        {
            "SOURCE_RPC_URL": "https://test.rpc",
            "SOURCE_CONTRACT_ADDRESS": "0x85BfE05492aFC3D04Ff3B2ca6771ACF6f853d90d",
            "ROFL_ADAPTER_ADDRESS": "0x742d35Cc6634C0532925a3b844Bc9e7595f0bEb0",
            "TARGET_RPC_URL": "https://testnet.sapphire.oasis.io",
            "ORACLE_MODE": "event_listener",
            "POLLING_INTERVAL": "20",
            "LOOKBACK_BLOCKS": "50",
            "REQUEST_TIMEOUT": "30",
            "RETRY_COUNT": "3",
        },
    )
    def test_from_env_event_listener(self):
        """Test loading event listener configuration from environment variables."""
        from rofl_oracle.config import OracleMode

        config = OracleConfig.from_env()

        assert config.common_config.source_rpc_url == "https://test.rpc"
        assert (
            config.common_config.target_rpc_url
            == "https://testnet.sapphire.oasis.io"
        )
        assert (
            config.common_config.target_contract_address
            == "0x742D35CC6634c0532925A3b844BC9E7595F0BEb0"
        )
        assert config.common_config.request_timeout == 30
        assert config.common_config.retry_count == 3

        assert config.oracle_mode == OracleMode.EVENT_LISTENER
        assert isinstance(config.mode_config, EventListenerModeConfig)
        assert config.mode_config.polling_interval == 20
        assert config.mode_config.lookback_blocks == 50
        assert (
            config.mode_config.contract_address
            == "0x85BfE05492aFC3D04Ff3B2ca6771ACF6f853d90d"
        )
        assert config.local_mode is False

    @patch.dict(
        os.environ,
        {
            "SOURCE_RPC_URL": "https://test.rpc",
            "ROFL_ADAPTER_ADDRESS": "0x742d35Cc6634C0532925a3b844Bc9e7595f0bEb0",
            "TARGET_RPC_URL": "https://testnet.sapphire.oasis.io",
            "ORACLE_MODE": "push",
            "PUSH_INTERVAL": "120",
            "PUSH_BATCH_SIZE": "30",
            "REQUEST_TIMEOUT": "30",
            "RETRY_COUNT": "3",
        },
    )
    def test_from_env_push_oracle(self):
        """Test loading push oracle configuration from environment variables."""
        from rofl_oracle.config import OracleMode

        config = OracleConfig.from_env()

        assert config.common_config.source_rpc_url == "https://test.rpc"
        assert config.oracle_mode == OracleMode.PUSH
        assert isinstance(config.mode_config, PushModeConfig)
        assert config.mode_config.push_interval == 120
        assert config.mode_config.batch_size == 30

    @patch.dict(
        os.environ,
        {
            "SOURCE_RPC_URL": "https://test.rpc",
            "ROFL_ADAPTER_ADDRESS": "0x742d35Cc6634C0532925a3b844Bc9e7595f0bEb0",
            "TARGET_RPC_URL": "https://testnet.sapphire.oasis.io",
            "ORACLE_MODE": "watcher",
            "WATCH_ADDRESSES": "0x85BfE05492aFC3D04Ff3B2ca6771ACF6f853d90d,0x742d35Cc6634C0532925a3b844Bc9e7595f0bEb0",
            "SCAN_INTERVAL": "90",
            "WATCHER_BATCH_SIZE": "75",
            "LOOKBACK_BLOCKS": "200",
            "REQUEST_TIMEOUT": "30",
            "RETRY_COUNT": "3",
        },
    )
    def test_from_env_watcher(self):
        """Test loading watcher configuration from environment variables."""
        from rofl_oracle.config import OracleMode

        config = OracleConfig.from_env()

        assert config.oracle_mode == OracleMode.WATCHER
        assert isinstance(config.mode_config, WatcherModeConfig)
        assert len(config.mode_config.watch_addresses) == 2
        assert (
            config.mode_config.watch_addresses[0]
            == "0x85BfE05492aFC3D04Ff3B2ca6771ACF6f853d90d"
        )
        assert (
            config.mode_config.watch_addresses[1]
            == "0x742D35CC6634c0532925A3b844BC9E7595F0BEb0"
        )
        assert config.mode_config.scan_interval == 90
        assert config.mode_config.batch_size == 75
        assert config.mode_config.lookback_blocks == 200

    @patch.dict(
        os.environ,
        {
            "SOURCE_RPC_URL": "https://test.rpc",
            "ROFL_ADAPTER_ADDRESS": "0x742d35Cc6634C0532925a3b844Bc9e7595f0bEb0",
            "ORACLE_MODE": "push",
            "LOCAL_PRIVATE_KEY": "0x" + "a" * 64,
        },
    )
    def test_from_env_local_mode(self):
        """Test loading configuration for local mode."""
        config = OracleConfig.from_env(local_mode=True)

        assert config.local_mode is True
        assert config.local_private_key == "0x" + "a" * 64

    @patch.dict(os.environ, {}, clear=True)
    def test_from_env_missing_required(self):
        """Test that missing required environment variables raise errors."""
        with pytest.raises(
            ValueError, match="Target contract address is required"
        ):
            OracleConfig.from_env()

    @patch.dict(
        os.environ,
        {
            "ROFL_ADAPTER_ADDRESS": "0x85BfE05492aFC3D04Ff3B2ca6771ACF6f853d90d",
            "ORACLE_MODE": "event_listener",
            "SOURCE_RPC_URL": "https://test.rpc",
            "TARGET_RPC_URL": "https://testnet.sapphire.oasis.io",
        },
        clear=True,
    )
    def test_from_env_missing_source_contract_for_event_listener(self):
        """Test that event listener mode requires source contract address."""
        with pytest.raises(
            ValueError,
            match="Contract address for event listener mode cannot be empty",
        ):
            OracleConfig.from_env()

    @patch.dict(
        os.environ,
        {
            "ROFL_ADAPTER_ADDRESS": "0x85BfE05492aFC3D04Ff3B2ca6771ACF6f853d90d",
            "ORACLE_MODE": "watcher",
            "SOURCE_RPC_URL": "https://test.rpc",
            "TARGET_RPC_URL": "https://testnet.sapphire.oasis.io",
        },
        clear=True,
    )
    def test_from_env_missing_watch_addresses_for_watcher(self):
        """Test that watcher mode requires watch addresses."""
        with pytest.raises(
            ValueError, match="WATCH_ADDRESSES is required for watcher mode"
        ):
            OracleConfig.from_env()

    def test_with_chain_id(self):
        """Test updating configuration with chain ID."""
        from rofl_oracle.config import OracleMode

        common = CommonConfig(
            source_rpc_url="https://test.rpc",
            source_chain_id=None,
            target_rpc_url="https://testnet.sapphire.oasis.io",
            request_timeout=30,
            retry_count=3,
            target_contract_address="0x85BfE05492aFC3D04Ff3B2ca6771ACF6f853d90d",
        )
        push = PushModeConfig(push_interval=60)
        config = OracleConfig(
            common_config=common,
            oracle_mode=OracleMode.PUSH,
            mode_config=push,
        )

        # Initially no chain ID
        assert config.common_config.source_chain_id is None

        # Update with chain ID
        new_config = config.with_chain_id(1)

        # New config has chain ID
        assert new_config.common_config.source_chain_id == 1
        # Other fields unchanged
        assert (
            new_config.common_config.source_rpc_url
            == config.common_config.source_rpc_url
        )
        assert (
            new_config.common_config.target_rpc_url
            == config.common_config.target_rpc_url
        )
        assert new_config.oracle_mode == config.oracle_mode

    def test_log_config_event_listener(self, caplog):
        """Test configuration logging for event listener mode."""
        from rofl_oracle.config import OracleMode

        common = CommonConfig(
            source_rpc_url="https://test.rpc",
            source_chain_id=1,
            target_rpc_url="https://testnet.sapphire.oasis.io",
            request_timeout=30,
            retry_count=3,
            target_contract_address="0x85BfE05492aFC3D04Ff3B2ca6771ACF6f853d90d",
        )
        event_listener = EventListenerModeConfig(
            polling_interval=15,
            lookback_blocks=100,
            contract_address="0x742d35Cc6634C0532925a3b844Bc9e7595f0bEb0",
        )

        config = OracleConfig(
            common_config=common,
            oracle_mode=OracleMode.EVENT_LISTENER,
            mode_config=event_listener,
            local_mode=True,
            local_private_key="0x" + "a" * 64,
        )

        with caplog.at_level(logging.INFO):
            config.log_config()

        log_text = caplog.text
        assert "ROFL Oracle Configuration" in log_text
        assert "EVENT LISTENER" in log_text
        assert "https://test.rpc" in log_text
        assert "https://testnet.sapphire.oasis.io" in log_text
        assert "0x742D35CC6634c0532925A3b844BC9E7595F0BEb0" in log_text
        assert "15 seconds" in log_text
        assert "Mode: LOCAL" in log_text
        assert "Local Key: [CONFIGURED]" in log_text

    def test_immutability(self):
        """Test that configuration is immutable."""
        from rofl_oracle.config import OracleMode

        common = CommonConfig(
            source_rpc_url="https://test.rpc",
            source_chain_id=None,
            target_rpc_url="https://testnet.sapphire.oasis.io",
            request_timeout=30,
            retry_count=3,
            target_contract_address="0x85BfE05492aFC3D04Ff3B2ca6771ACF6f853d90d",
        )
        push = PushModeConfig(push_interval=60)
        config = OracleConfig(
            common_config=common,
            oracle_mode=OracleMode.PUSH,
            mode_config=push,
        )

        # Cannot modify attributes
        with pytest.raises(AttributeError):
            config.oracle_mode = OracleMode.WATCHER

        with pytest.raises(AttributeError):
            config.common_config.source_rpc_url = "https://new.rpc"

        with pytest.raises(AttributeError):
            config.mode_config.push_interval = 120
