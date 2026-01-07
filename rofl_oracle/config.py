#!/usr/bin/env python3
"""Configuration management for ROFL Oracle.

This module provides type-safe configuration dataclasses with validation
for the ROFL Oracle system. Configuration is loaded from environment variables
with sensible defaults where appropriate.
"""

import logging
import os
from dataclasses import dataclass
from enum import Enum
from urllib.parse import urlparse

from web3 import Web3

logger = logging.getLogger(__name__)


class OracleMode(Enum):
    """Oracle operating modes."""

    EVENT_LISTENER = "event_listener"
    PUSH = "push"
    WATCHER = "watcher"
    TOKEN_WATCHER = "token_watcher"


@dataclass(frozen=True, slots=True)
class EventListenerModeConfig:
    """Configuration specific to event listener mode.

    This mode listens for BlockHeaderRequested events from a source chain contract
    and submits the requested block headers to the target chain.

    :cvar polling_interval: Seconds between event polling checks (env: POLLING_INTERVAL)
    :cvar lookback_blocks: Number of blocks to look back on startup (env: LOOKBACK_BLOCKS)
    :cvar contract_address: Address of BlockHeaderRequester contract (env: SOURCE_CONTRACT_ADDRESS)
    """

    polling_interval: int
    lookback_blocks: int
    contract_address: str

    def __post_init__(self) -> None:
        """Validate event listener configuration."""
        if self.polling_interval <= 0:
            raise ValueError(
                f"Polling interval must be positive, got {self.polling_interval}"
            )
        if self.polling_interval > 300:
            raise ValueError(
                f"Polling interval too long (max 300s), got {self.polling_interval}"
            )

        if self.lookback_blocks <= 0:
            raise ValueError(
                f"Lookback blocks must be positive, got {self.lookback_blocks}"
            )
        if self.lookback_blocks > 1000:
            raise ValueError(
                f"Lookback blocks too high (max 1000), got {self.lookback_blocks}"
            )

        if self.contract_address == "":
            raise ValueError(
                "Contract address for event listener mode cannot be empty"
            )

        # Validate and checksum contract address (only if provided)
        if self.contract_address is not None:
            if not self.contract_address:
                raise ValueError(
                    "Source contract address cannot be empty string (SOURCE_CONTRACT_ADDRESS). "
                    "Use None for push oracle or watcher mode."
                )

            if not Web3.is_address(self.contract_address):
                raise ValueError(
                    f"Invalid source contract address: {self.contract_address}"
                )

            # Convert to checksum address
            checksummed = Web3.to_checksum_address(self.contract_address)
            if checksummed != self.contract_address:
                # Use object.__setattr__ since dataclass is frozen
                object.__setattr__(self, "contract_address", checksummed)


@dataclass(frozen=True, slots=True)
class PushModeConfig:
    """Configuration specific to push oracle mode.

    This mode continuously pushes the latest block headers from the source chain
    to the target chain without requiring explicit requests.

    :cvar push_interval: Seconds between block pushes (env: PUSH_INTERVAL)
    :cvar batch_size: Maximum blocks to push per iteration (env: PUSH_BATCH_SIZE)
    """

    push_interval: int
    batch_size: int = 20

    def __post_init__(self) -> None:
        """Validate push oracle configuration."""
        if self.push_interval <= 0:
            raise ValueError(
                f"Push interval must be positive, got {self.push_interval}"
            )
        if self.push_interval > 300:
            raise ValueError(
                f"Push interval too long (max 300s), got {self.push_interval}"
            )

        if self.batch_size <= 0:
            raise ValueError(
                f"Batch size must be positive, got {self.batch_size}"
            )
        if self.batch_size > 100:
            raise ValueError(
                f"Batch size too high (max 100), got {self.batch_size}"
            )


@dataclass(frozen=True, slots=True)
class WatcherModeConfig:
    """Configuration specific to watcher mode.

    This mode watches specific addresses for interactions and pushes block headers
    only when those addresses have on-chain activity.

    :cvar watch_addresses: List of addresses to monitor (env: WATCH_ADDRESSES, comma-separated)
    :cvar scan_interval: Seconds between scanning for interactions (env: SCAN_INTERVAL)
    :cvar batch_size: Maximum blocks to scan per iteration (env: WATCHER_BATCH_SIZE)
    :cvar lookback_blocks: Number of blocks to look back on startup (env: LOOKBACK_BLOCKS)
    :cvar enable_internal_tx_detection: Enable internal transaction detection (env: ENABLE_INTERNAL_TX_DETECTION)
    :cvar heartbeat_interval_seconds: Seconds between heartbeat submissions when no activity (env: HEARTBEAT_INTERVAL_SECONDS)
    """

    watch_addresses: list[str]
    scan_interval: int
    batch_size: int = 50
    lookback_blocks: int = 100
    enable_internal_tx_detection: bool = False
    heartbeat_interval_seconds: int = 3600

    def __post_init__(self) -> None:
        """Validate watcher configuration."""
        if self.scan_interval <= 0:
            raise ValueError(
                f"Scan interval must be positive, got {self.scan_interval}"
            )
        if self.scan_interval > 300:
            raise ValueError(
                f"Scan interval too long (max 300s), got {self.scan_interval}"
            )

        if self.batch_size <= 0:
            raise ValueError(
                f"Batch size must be positive, got {self.batch_size}"
            )
        if self.batch_size > 200:
            raise ValueError(
                f"Batch size too high (max 200), got {self.batch_size}"
            )

        if self.lookback_blocks <= 0:
            raise ValueError(
                f"Lookback blocks must be positive, got {self.lookback_blocks}"
            )
        if self.lookback_blocks > 1000:
            raise ValueError(
                f"Lookback blocks too high (max 1000), got {self.lookback_blocks}"
            )

        if self.heartbeat_interval_seconds <= 0:
            raise ValueError(
                f"Heartbeat interval must be positive, got {self.heartbeat_interval_seconds}"
            )
        if self.heartbeat_interval_seconds > 86400:
            raise ValueError(
                f"Heartbeat interval too high (max 86400s/24h), got {self.heartbeat_interval_seconds}"
            )

        if self.watch_addresses is None or len(self.watch_addresses) == 0:
            raise ValueError("Watcher mode requires at least one watch address")

        # Validate watch addresses if provided
        if self.watch_addresses is not None:
            if not isinstance(self.watch_addresses, list):
                raise ValueError("Watch addresses must be a list")

            if len(self.watch_addresses) == 0:
                raise ValueError("Watch addresses list cannot be empty")

            # Checksum all watch addresses
            checksummed_addresses = []
            for addr in self.watch_addresses:
                if not Web3.is_address(addr):
                    raise ValueError(f"Invalid watch address: {addr}")
                checksummed_addresses.append(Web3.to_checksum_address(addr))

            object.__setattr__(self, "watch_addresses", checksummed_addresses)


@dataclass(frozen=True, slots=True)
class TokenWatcherModeConfig:
    """Configuration specific to token watcher mode.

    This mode watches for ERC20 token transfers to specific recipient addresses
    and pushes block headers when such transfers are detected.

    :cvar token_addresses: List of ERC20 token contract addresses to monitor (env: TOKEN_ADDRESSES, comma-separated)
    :cvar recipient_addresses: List of recipient addresses to watch for (env: RECIPIENT_ADDRESSES, comma-separated)
    :cvar scan_interval: Seconds between scanning for token transfers (env: SCAN_INTERVAL)
    :cvar max_blocks_per_scan: Maximum number of blocks to scan per iteration (env: MAX_BLOCKS_PER_SCAN, default: 10)
    """

    token_addresses: list[str]
    recipient_addresses: list[str]
    scan_interval: int
    max_blocks_per_scan: int = 10

    def __post_init__(self) -> None:
        """Validate token watcher configuration."""
        if self.scan_interval <= 0:
            raise ValueError(
                f"Scan interval must be positive, got {self.scan_interval}"
            )
        if self.scan_interval > 300:
            raise ValueError(
                f"Scan interval too long (max 300s), got {self.scan_interval}"
            )

        if self.max_blocks_per_scan <= 0:
            raise ValueError(
                f"Max blocks per scan must be positive, got {self.max_blocks_per_scan}"
            )
        if self.max_blocks_per_scan > 10000:
            raise ValueError(
                f"Max blocks per scan too high (max 10000), got {self.max_blocks_per_scan}"
            )

        if not self.token_addresses or len(self.token_addresses) == 0:
            raise ValueError(
                "Token watcher mode requires at least one token address"
            )

        if not self.recipient_addresses or len(self.recipient_addresses) == 0:
            raise ValueError(
                "Token watcher mode requires at least one recipient address"
            )

        # Validate and checksum token addresses
        checksummed_tokens = []
        for addr in self.token_addresses:
            if not Web3.is_address(addr):
                raise ValueError(f"Invalid token address: {addr}")
            checksummed_tokens.append(Web3.to_checksum_address(addr))
        object.__setattr__(self, "token_addresses", checksummed_tokens)

        # Validate and checksum recipient addresses
        checksummed_recipients = []
        for addr in self.recipient_addresses:
            if not Web3.is_address(addr):
                raise ValueError(f"Invalid recipient address: {addr}")
            checksummed_recipients.append(Web3.to_checksum_address(addr))
        object.__setattr__(self, "recipient_addresses", checksummed_recipients)


@dataclass(frozen=True, slots=True)
class CommonConfig:
    """Configuration common to all oracle modes.

    These settings apply regardless of which operating mode the oracle is in.

    :cvar source_rpc_url: HTTP(S) RPC endpoint for the source chain (env: SOURCE_RPC_URL)
    :cvar source_chain_id: Chain ID for the source chain (auto-detected from RPC)
    :cvar target_rpc_url: HTTP(S) RPC endpoint for the target chain (env: TARGET_RPC_URL)
    :cvar request_timeout: HTTP request timeout in seconds (env: REQUEST_TIMEOUT)
    :cvar retry_count: Number of retry attempts for operations (env: RETRY_COUNT)
    :cvar target_contract_address: Address of ROFLAdapter on target chain (env: ROFL_ADAPTER_ADDRESS)
    """

    source_rpc_url: str
    source_chain_id: int
    target_rpc_url: str
    request_timeout: int
    retry_count: int
    target_contract_address: str

    def __post_init__(self) -> None:
        """Validate common configuration."""
        if self.request_timeout <= 0:
            raise ValueError(
                f"Request timeout must be positive, got {self.request_timeout}"
            )
        if self.request_timeout > 120:
            raise ValueError(
                f"Request timeout too long (max 120s), got {self.request_timeout}"
            )

        if self.retry_count < 0:
            raise ValueError(
                f"Retry count must be non-negative, got {self.retry_count}"
            )
        if self.retry_count > 10:
            raise ValueError(
                f"Retry count too high (max 10), got {self.retry_count}"
            )

        if not self.source_rpc_url:
            raise ValueError("Source RPC URL is required (SOURCE_RPC_URL)")

        # Validate RPC URL
        if not self.source_rpc_url:
            raise ValueError("Source RPC URL is required (SOURCE_RPC_URL)")

        parsed = urlparse(self.source_rpc_url)
        if parsed.scheme not in ("http", "https", "ws", "wss"):
            raise ValueError(
                f"Invalid RPC URL scheme: {parsed.scheme}. "
                "Expected http, https, ws, or wss"
            )

        if not self.target_rpc_url:
            raise ValueError("Target RPC URL is required (TARGET_RPC_URL)")

            # Validate RPC URL
        if not self.target_rpc_url:
            raise ValueError("Target RPC URL is required (TARGET_RPC_URL)")

        parsed = urlparse(self.target_rpc_url)
        if parsed.scheme not in ("http", "https", "ws", "wss"):
            raise ValueError(
                f"Invalid RPC URL scheme: {parsed.scheme}. "
                "Must be http, https, ws, or wss"
            )

        # Validate and checksum contract address
        if not self.target_contract_address:
            raise ValueError(
                "Target contract address is required (ROFL_ADAPTER_ADDRESS)"
            )

        if not Web3.is_address(self.target_contract_address):
            raise ValueError(
                f"Invalid target contract address: {self.target_contract_address}"
            )

        # Convert to checksum address
        checksummed = Web3.to_checksum_address(self.target_contract_address)
        if checksummed != self.target_contract_address:
            object.__setattr__(self, "target_contract_address", checksummed)


@dataclass(frozen=True, slots=True)
class OracleConfig:
    """Main configuration for the ROFL Oracle.

    :cvar common_config: Common configuration shared across all modes
    :cvar oracle_mode: The operating mode of the oracle
    :cvar mode_config: Mode-specific configuration (EventListenerModeConfig, PushModeConfig, WatcherModeConfig, or TokenWatcherModeConfig)
    :cvar local_mode: Whether running in local mode (for testing)
    :cvar local_private_key: Private key for local mode (optional)
    """

    common_config: CommonConfig
    oracle_mode: OracleMode
    mode_config: (
        EventListenerModeConfig
        | PushModeConfig
        | WatcherModeConfig
        | TokenWatcherModeConfig
    )
    local_mode: bool = False
    local_private_key: str | None = None

    def __post_init__(self) -> None:
        """Validate oracle configuration."""
        # Validate local mode configuration
        if self.local_mode and not self.local_private_key:
            raise ValueError(
                "Local mode requires LOCAL_PRIVATE_KEY environment variable"
            )

        if self.local_private_key:
            # Basic private key validation (should be 64 hex chars, optionally with 0x prefix)
            key = self.local_private_key
            if key.startswith("0x"):
                key = key[2:]

            if len(key) != 64:
                raise ValueError(
                    f"Invalid private key length. Expected 64 hex characters, got {len(key)}"
                )

            try:
                int(key, 16)
            except ValueError:
                raise ValueError(
                    "Invalid private key format. Must be hexadecimal"
                ) from None

        # Validate mode-specific config matches oracle_mode
        if self.oracle_mode == OracleMode.EVENT_LISTENER and not isinstance(
            self.mode_config, EventListenerModeConfig
        ):
            raise ValueError(
                "Event listener mode requires EventListenerModeConfig"
            )
        elif self.oracle_mode == OracleMode.PUSH and not isinstance(
            self.mode_config, PushModeConfig
        ):
            raise ValueError("Push oracle mode requires PushModeConfig")
        elif self.oracle_mode == OracleMode.WATCHER and not isinstance(
            self.mode_config, WatcherModeConfig
        ):
            raise ValueError("Watcher mode requires WatcherModeConfig")
        elif self.oracle_mode == OracleMode.TOKEN_WATCHER and not isinstance(
            self.mode_config, TokenWatcherModeConfig
        ):
            raise ValueError(
                "Token watcher mode requires TokenWatcherModeConfig"
            )

    @classmethod
    def from_env(cls, local_mode: bool = False) -> "OracleConfig":
        """Load configuration from environment variables.

        Args:
            local_mode: Whether to run in local mode (for testing)

        Returns:
            OracleConfig instance with loaded values

        Raises:
            ValueError: If required environment variables are missing or invalid
        """
        # Load common configuration
        source_rpc_url = os.environ.get(
            "SOURCE_RPC_URL",
            "https://ethereum.publicnode.com",  # Default public RPC
        )

        target_rpc_url = os.environ.get(
            "TARGET_RPC_URL", "https://testnet.sapphire.oasis.io"
        )

        target_contract_address = os.environ.get("ROFL_ADAPTER_ADDRESS", "")

        request_timeout = int(os.environ.get("REQUEST_TIMEOUT", "30"))
        retry_count = int(os.environ.get("RETRY_COUNT", "3"))

        common_config = CommonConfig(
            source_rpc_url=source_rpc_url,
            source_chain_id=None,
            target_rpc_url=target_rpc_url,
            request_timeout=request_timeout,
            retry_count=retry_count,
            target_contract_address=target_contract_address,
        )

        # Determine oracle mode from environment
        mode_str = os.environ.get("ORACLE_MODE", "event_listener").lower()

        # Parse mode string to enum
        oracle_mode: OracleMode
        if mode_str == "event_listener":
            oracle_mode = OracleMode.EVENT_LISTENER
        elif mode_str == "push":
            oracle_mode = OracleMode.PUSH
        elif mode_str == "watcher":
            oracle_mode = OracleMode.WATCHER
        elif mode_str == "token_watcher":
            oracle_mode = OracleMode.TOKEN_WATCHER
        else:
            raise ValueError(
                f"Invalid ORACLE_MODE: {mode_str}. "
                "Must be one of: event_listener, push, watcher, token_watcher"
            )

        # Load mode-specific configuration
        mode_config: (
            EventListenerModeConfig
            | PushModeConfig
            | WatcherModeConfig
            | TokenWatcherModeConfig
        )

        if oracle_mode == OracleMode.EVENT_LISTENER:
            mode_config = EventListenerModeConfig(
                polling_interval=int(os.environ.get("POLLING_INTERVAL", "12")),
                lookback_blocks=int(os.environ.get("LOOKBACK_BLOCKS", "100")),
                contract_address=os.environ.get("SOURCE_CONTRACT_ADDRESS", ""),
            )
        elif oracle_mode == OracleMode.PUSH:
            mode_config = PushModeConfig(
                push_interval=int(os.environ.get("PUSH_INTERVAL", "60")),
                batch_size=int(os.environ.get("PUSH_BATCH_SIZE", "20")),
            )
        elif oracle_mode == OracleMode.WATCHER:
            watch_addresses_str = os.environ.get("WATCH_ADDRESSES", "")
            if not watch_addresses_str:
                raise ValueError(
                    "WATCH_ADDRESSES is required for watcher mode. "
                    "Provide comma-separated addresses."
                )

            # Parse comma-separated addresses
            watch_addresses = [
                addr.strip()
                for addr in watch_addresses_str.split(",")
                if addr.strip()
            ]

            if len(watch_addresses) == 0:
                raise ValueError(
                    "WATCH_ADDRESSES cannot be empty for watcher mode"
                )

            mode_config = WatcherModeConfig(
                scan_interval=int(os.environ.get("SCAN_INTERVAL", "60")),
                batch_size=int(os.environ.get("WATCHER_BATCH_SIZE", "50")),
                lookback_blocks=int(os.environ.get("LOOKBACK_BLOCKS", "100")),
                watch_addresses=watch_addresses,
                enable_internal_tx_detection=os.environ.get(
                    "ENABLE_INTERNAL_TX_DETECTION", "false"
                ).lower()
                in ("true", "1", "yes"),
                heartbeat_interval_seconds=int(
                    os.environ.get("HEARTBEAT_INTERVAL_SECONDS", "3600")
                ),
            )
        else:  # OracleMode.TOKEN_WATCHER
            token_addresses_str = os.environ.get("TOKEN_ADDRESSES", "")
            if not token_addresses_str:
                raise ValueError(
                    "TOKEN_ADDRESSES is required for token watcher mode. "
                    "Provide comma-separated token contract addresses (e.g., USDC, USDT)."
                )

            recipient_addresses_str = os.environ.get("RECIPIENT_ADDRESSES", "")
            if not recipient_addresses_str:
                raise ValueError(
                    "RECIPIENT_ADDRESSES is required for token watcher mode. "
                    "Provide comma-separated recipient addresses to watch."
                )

            # Parse comma-separated token addresses
            token_addresses = [
                addr.strip()
                for addr in token_addresses_str.split(",")
                if addr.strip()
            ]

            if len(token_addresses) == 0:
                raise ValueError("TOKEN_ADDRESSES cannot be empty")

            # Parse comma-separated recipient addresses
            recipient_addresses = [
                addr.strip()
                for addr in recipient_addresses_str.split(",")
                if addr.strip()
            ]

            if len(recipient_addresses) == 0:
                raise ValueError("RECIPIENT_ADDRESSES cannot be empty")

            mode_config = TokenWatcherModeConfig(
                token_addresses=token_addresses,
                recipient_addresses=recipient_addresses,
                scan_interval=int(os.environ.get("SCAN_INTERVAL", "5")),
            )

        # Load oracle-level config
        local_private_key = (
            os.environ.get("LOCAL_PRIVATE_KEY") if local_mode else None
        )

        return cls(
            common_config=common_config,
            oracle_mode=oracle_mode,
            mode_config=mode_config,
            local_mode=local_mode,
            local_private_key=local_private_key,
        )

    def log_config(self) -> None:
        """Log the configuration in a readable format for debugging."""
        logger.info("=" * 60)
        logger.info("ROFL Oracle Configuration")
        logger.info("=" * 60)

        logger.info("Oracle Mode:")
        logger.info(f"  {self.oracle_mode.value.upper().replace('_', ' ')}")

        logger.info("Common Configuration:")
        logger.info(f"  Source RPC URL: {self.common_config.source_rpc_url}")
        logger.info(f"  Target RPC URL: {self.common_config.target_rpc_url}")
        logger.info(
            f"  Target Contract: {self.common_config.target_contract_address}"
        )
        logger.info(
            f"  Request Timeout: {self.common_config.request_timeout} seconds"
        )
        logger.info(f"  Retry Count: {self.common_config.retry_count}")

        if self.oracle_mode == OracleMode.EVENT_LISTENER:
            assert isinstance(self.mode_config, EventListenerModeConfig)
            logger.info("Event Listener Settings:")
            logger.info(
                f"  Contract Address: {self.mode_config.contract_address}"
            )
            logger.info(
                f"  Polling Interval: {self.mode_config.polling_interval} seconds"
            )
            logger.info(
                f"  Lookback Blocks: {self.mode_config.lookback_blocks}"
            )

        elif self.oracle_mode == OracleMode.PUSH:
            assert isinstance(self.mode_config, PushModeConfig)
            logger.info("Push Oracle Settings:")
            logger.info(
                f"  Push Interval: {self.mode_config.push_interval} seconds"
            )
            logger.info(f"  Batch Size: {self.mode_config.batch_size}")

        elif self.oracle_mode == OracleMode.WATCHER:
            assert isinstance(self.mode_config, WatcherModeConfig)
            logger.info("Watcher Settings:")
            logger.info(
                f"  Scan Interval: {self.mode_config.scan_interval} seconds"
            )
            logger.info(f"  Batch Size: {self.mode_config.batch_size}")
            logger.info(
                f"  Lookback Blocks: {self.mode_config.lookback_blocks}"
            )
            logger.info(
                f"  Heartbeat Interval: {self.mode_config.heartbeat_interval_seconds} seconds"
            )
            logger.info(
                f"  Internal TX Detection: {'ENABLED' if self.mode_config.enable_internal_tx_detection else 'DISABLED'}"
            )
            logger.info(
                f"  Watching {len(self.mode_config.watch_addresses)} address(es):"
            )
            for addr in self.mode_config.watch_addresses:
                logger.info(f"    - {addr}")

        elif self.oracle_mode == OracleMode.TOKEN_WATCHER:
            assert isinstance(self.mode_config, TokenWatcherModeConfig)
            logger.info("Token Watcher Settings:")
            logger.info(
                f"  Scan Interval: {self.mode_config.scan_interval} seconds"
            )
            logger.info(
                "  Mode: Real-time (scans all new blocks since last check)"
            )
            logger.info(
                f"  Watching {len(self.mode_config.token_addresses)} token(s):"
            )
            for addr in self.mode_config.token_addresses:
                logger.info(f"    - {addr}")
            logger.info(
                f"  Monitoring {len(self.mode_config.recipient_addresses)} recipient(s):"
            )
            for addr in self.mode_config.recipient_addresses:
                logger.info(f"    - {addr}")

        logger.info("Oracle Settings:")
        logger.info(f"  Mode: {'LOCAL' if self.local_mode else 'PRODUCTION'}")

        if self.local_mode:
            logger.info("  Local Key: [CONFIGURED]")

        logger.info("=" * 60)

    def with_chain_id(self, chain_id: int) -> "OracleConfig":
        """Create a new config with the chain ID set.

        Since the config is frozen, we need to create a new instance
        to update the chain ID after connecting to the RPC.

        Args:
            chain_id: The chain ID from the connected RPC

        Returns:
            New OracleConfig instance with chain_id set
        """
        updated_common_config = CommonConfig(
            source_rpc_url=self.common_config.source_rpc_url,
            source_chain_id=chain_id,
            target_rpc_url=self.common_config.target_rpc_url,
            request_timeout=self.common_config.request_timeout,
            retry_count=self.common_config.retry_count,
            target_contract_address=self.common_config.target_contract_address,
        )

        return OracleConfig(
            common_config=updated_common_config,
            oracle_mode=self.oracle_mode,
            mode_config=self.mode_config,
            local_mode=self.local_mode,
            local_private_key=self.local_private_key,
        )
