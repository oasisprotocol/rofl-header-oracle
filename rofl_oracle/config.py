#!/usr/bin/env python3
"""Configuration management for ROFL Oracle.

This module provides type-safe configuration dataclasses with validation
for the ROFL Oracle system. Configuration is loaded from environment variables
with sensible defaults where appropriate.
"""

from enum import Enum
import logging
import os
from dataclasses import dataclass
from urllib.parse import urlparse

from web3 import Web3

logger = logging.getLogger(__name__)

class OracleMode(Enum):
    """Oracle operating modes."""
    EVENT_LISTENER = "event_listener"  # Listen for BlockHeaderRequested events
    PUSH = "push"                      # Push latest block headers periodically
    WATCHER = "watcher"                # Watch specific addresses for interactions

@dataclass(frozen=True, slots=True)
class EventListenerModeConfig:
    """Configuration specific to event listener mode."""
    
    polling_interval: int  # seconds between event polls
    lookback_blocks: int   # blocks to look back on startup
    contract_address: str  # contract address to listen to for BlockHeaderRequested events
    
    def __post_init__(self) -> None:
        """Validate event listener configuration."""
        if self.polling_interval <= 0:
            raise ValueError(f"Polling interval must be positive, got {self.polling_interval}")
        if self.polling_interval > 300:
            raise ValueError(f"Polling interval too long (max 300s), got {self.polling_interval}")
        
        if self.lookback_blocks <= 0:
            raise ValueError(f"Lookback blocks must be positive, got {self.lookback_blocks}")
        if self.lookback_blocks > 1000:
            raise ValueError(f"Lookback blocks too high (max 1000), got {self.lookback_blocks}")

        if self.contract_address == "":
            raise ValueError("Contract address for event listener mode cannot be empty")
        

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
    """Configuration specific to push oracle mode."""
    
    push_interval: int  # seconds between block pushes
    batch_size: int = 20  # max blocks to push per iteration
    
    def __post_init__(self) -> None:
        """Validate push oracle configuration."""
        if self.push_interval <= 0:
            raise ValueError(f"Push interval must be positive, got {self.push_interval}")
        if self.push_interval > 300:
            raise ValueError(f"Push interval too long (max 300s), got {self.push_interval}")
        
        if self.batch_size <= 0:
            raise ValueError(f"Batch size must be positive, got {self.batch_size}")
        if self.batch_size > 100:
            raise ValueError(f"Batch size too high (max 100), got {self.batch_size}")


@dataclass(frozen=True, slots=True)
class WatcherModeConfig:
    """Configuration specific to watcher mode."""
    
    watch_addresses: list[str]  # Addresses to watch in watcher mode
    scan_interval: int          # seconds between scanning for interactions
    batch_size: int = 50        # max blocks to scan per iteration
    lookback_blocks: int = 100  # blocks to look back on first run
    
    
    def __post_init__(self) -> None:
        """Validate watcher configuration."""
        if self.scan_interval <= 0:
            raise ValueError(f"Scan interval must be positive, got {self.scan_interval}")
        if self.scan_interval > 300:
            raise ValueError(f"Scan interval too long (max 300s), got {self.scan_interval}")
        
        if self.batch_size <= 0:
            raise ValueError(f"Batch size must be positive, got {self.batch_size}")
        if self.batch_size > 200:
            raise ValueError(f"Batch size too high (max 200), got {self.batch_size}")
        
        if self.lookback_blocks <= 0:
            raise ValueError(f"Lookback blocks must be positive, got {self.lookback_blocks}")
        if self.lookback_blocks > 1000:
            raise ValueError(f"Lookback blocks too high (max 1000), got {self.lookback_blocks}")
        
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
class CommonConfig:
    """Configuration common to all oracle modes."""
    
    source_rpc_url: str           # HTTP(S) RPC endpoint for the source chain
    source_chain_id: int  # Chain ID for the source chain (optional)
    target_rpc_url: str           # HTTP(S) RPC endpoint for the target chain
    request_timeout: int          # HTTP request timeout in seconds
    retry_count: int              # retry attempts for operations
    target_contract_address: str  # contract address of ROFL Adapter on target chain
    
    
    def __post_init__(self) -> None:
        """Validate common configuration."""
        if self.request_timeout <= 0:
            raise ValueError(f"Request timeout must be positive, got {self.request_timeout}")
        if self.request_timeout > 120:
            raise ValueError(f"Request timeout too long (max 120s), got {self.request_timeout}")
        
        if self.retry_count < 0:
            raise ValueError(f"Retry count must be non-negative, got {self.retry_count}")
        if self.retry_count > 10:
            raise ValueError(f"Retry count too high (max 10), got {self.retry_count}")
        
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

    Attributes:
        common_config: Common configuration shared across all modes
        oracle_mode: The operating mode of the oracle
        mode_config: Mode-specific configuration (EventListenerModeConfig, PushModeConfig, or WatcherModeConfig)
        local_mode: Whether running in local mode (for testing)
        local_private_key: Private key for local mode (optional)
    """

    common_config: CommonConfig
    oracle_mode: OracleMode
    mode_config: EventListenerModeConfig | PushModeConfig | WatcherModeConfig
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
        if self.oracle_mode == OracleMode.EVENT_LISTENER and not isinstance(self.mode_config, EventListenerModeConfig):
            raise ValueError("Event listener mode requires EventListenerModeConfig")
        elif self.oracle_mode == OracleMode.PUSH and not isinstance(self.mode_config, PushModeConfig):
            raise ValueError("Push oracle mode requires PushModeConfig")
        elif self.oracle_mode == OracleMode.WATCHER and not isinstance(self.mode_config, WatcherModeConfig):
            raise ValueError("Watcher mode requires WatcherModeConfig")

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
            "TARGET_RPC_URL", 
            "https://testnet.sapphire.oasis.io"
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
        else:
            raise ValueError(
                f"Invalid ORACLE_MODE: {mode_str}. "
                "Must be one of: event_listener, push, watcher"
            )
        
        # Load mode-specific configuration
        mode_config: EventListenerModeConfig | PushModeConfig | WatcherModeConfig
        
        if oracle_mode == OracleMode.EVENT_LISTENER:
            mode_config = EventListenerModeConfig(
                polling_interval=int(os.environ.get("POLLING_INTERVAL", "12")),
                lookback_blocks=int(os.environ.get("LOOKBACK_BLOCKS", "100")),
                contract_address=os.environ.get("SOURCE_CONTRACT_ADDRESS", "")
            )
        elif oracle_mode == OracleMode.PUSH:
            mode_config = PushModeConfig(
                push_interval=int(os.environ.get("PUSH_INTERVAL", "60")),
                batch_size=int(os.environ.get("PUSH_BATCH_SIZE", "20")),
            )
        else:  # OracleMode.WATCHER
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
                raise ValueError("WATCH_ADDRESSES cannot be empty for watcher mode")
            
            mode_config = WatcherModeConfig(
                scan_interval=int(os.environ.get("SCAN_INTERVAL", "60")),
                batch_size=int(os.environ.get("WATCHER_BATCH_SIZE", "50")),
                lookback_blocks=int(os.environ.get("LOOKBACK_BLOCKS", "100")),
                watch_addresses=watch_addresses,
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
        logger.info(f"  Target Contract: {self.common_config.target_contract_address}")
        logger.info(f"  Request Timeout: {self.common_config.request_timeout} seconds")
        logger.info(f"  Retry Count: {self.common_config.retry_count}")

        if self.oracle_mode == OracleMode.EVENT_LISTENER:
            assert isinstance(self.mode_config, EventListenerModeConfig)
            logger.info("Event Listener Settings:")
            logger.info(f"  Contract Address: {self.mode_config.contract_address}")
            logger.info(f"  Polling Interval: {self.mode_config.polling_interval} seconds")
            logger.info(f"  Lookback Blocks: {self.mode_config.lookback_blocks}")
            
        elif self.oracle_mode == OracleMode.PUSH:
            assert isinstance(self.mode_config, PushModeConfig)
            logger.info("Push Oracle Settings:")
            logger.info(f"  Push Interval: {self.mode_config.push_interval} seconds")
            logger.info(f"  Batch Size: {self.mode_config.batch_size}")
            
        elif self.oracle_mode == OracleMode.WATCHER:
            assert isinstance(self.mode_config, WatcherModeConfig)
            logger.info("Watcher Settings:")
            logger.info(f"  Scan Interval: {self.mode_config.scan_interval} seconds")
            logger.info(f"  Batch Size: {self.mode_config.batch_size}")
            logger.info(f"  Lookback Blocks: {self.mode_config.lookback_blocks}")
            logger.info(f"  Watching {len(self.mode_config.watch_addresses)} address(es):")
            for addr in self.mode_config.watch_addresses:
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
