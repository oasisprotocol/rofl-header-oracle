#!/usr/bin/env python3
"""Configuration management for ROFL Oracle.

This module provides type-safe configuration dataclasses with validation
for the ROFL Oracle system. Configuration is loaded from environment variables
with sensible defaults where appropriate.
"""

import logging
import os
from dataclasses import dataclass
from urllib.parse import urlparse

from web3 import Web3

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class SourceChainConfig:
    """Configuration for the source blockchain.

    Attributes:
        rpc_url: HTTP(S) RPC endpoint for the source chain
        contract_address: Checksummed address of BlockHeaderRequester contract
        chain_id: Chain ID (fetched from RPC, not configured)
    """

    rpc_url: str
    contract_address: str
    chain_id: int | None = None  # Set after connecting to RPC

    def __post_init__(self) -> None:
        """Validate source chain configuration."""
        # Validate RPC URL
        if not self.rpc_url:
            raise ValueError("Source RPC URL is required (SOURCE_RPC_URL)")

        parsed = urlparse(self.rpc_url)
        if parsed.scheme not in ("http", "https", "ws", "wss"):
            raise ValueError(
                f"Invalid RPC URL scheme: {parsed.scheme}. "
                "Expected http, https, ws, or wss"
            )

        # Validate and checksum contract address
        if not self.contract_address:
            raise ValueError(
                "Source contract address is required (SOURCE_CONTRACT_ADDRESS)"
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
class TargetChainConfig:
    """Configuration for the target Sapphire chain.

    Attributes:
        rpc_url: HTTP(S) RPC endpoint for the target chain
        contract_address: Checksummed address of ROFLAdapter contract
    """

    rpc_url: str
    contract_address: str

    def __post_init__(self) -> None:
        """Validate target chain configuration."""
        # Validate RPC URL
        if not self.rpc_url:
            raise ValueError("Target RPC URL is required (TARGET_RPC_URL)")

        parsed = urlparse(self.rpc_url)
        if parsed.scheme not in ("http", "https", "ws", "wss"):
            raise ValueError(
                f"Invalid RPC URL scheme: {parsed.scheme}. "
                "Must be http, https, ws, or wss"
            )

        # Validate and checksum contract address
        if not self.contract_address:
            raise ValueError(
                "Target contract address is required (CONTRACT_ADDRESS)"
            )

        if not Web3.is_address(self.contract_address):
            raise ValueError(
                f"Invalid target contract address: {self.contract_address}"
            )

        # Convert to checksum address
        checksummed = Web3.to_checksum_address(self.contract_address)
        if checksummed != self.contract_address:
            object.__setattr__(self, "contract_address", checksummed)


@dataclass(frozen=True, slots=True)
class MonitoringConfig:
    """Configuration for event monitoring and processing."""

    polling_interval: int  # seconds between event polls
    lookback_blocks: int  # blocks to look back on startup
    request_timeout: int  # HTTP request timeout in seconds
    retry_count: int  # retry attempts for operations

    def __post_init__(self) -> None:
        """Validate monitoring configuration."""
        # Validate polling interval
        if self.polling_interval <= 0:
            raise ValueError(
                f"Polling interval must be positive, got {self.polling_interval}"
            )
        if self.polling_interval > 300:
            raise ValueError(
                f"Polling interval too long (max 300s), got {self.polling_interval}"
            )

        # Validate lookback blocks
        if self.lookback_blocks <= 0:
            raise ValueError(
                f"Lookback blocks must be positive, got {self.lookback_blocks}"
            )
        if self.lookback_blocks > 1000:
            raise ValueError(
                f"Lookback blocks too high (max 1000), got {self.lookback_blocks}"
            )

        # Validate request timeout
        if self.request_timeout <= 0:
            raise ValueError(
                f"Request timeout must be positive, got {self.request_timeout}"
            )
        if self.request_timeout > 120:
            raise ValueError(
                f"Request timeout too long (max 120s), got {self.request_timeout}"
            )

        # Validate retry count
        if self.retry_count < 0:
            raise ValueError(
                f"Retry count must be non-negative, got {self.retry_count}"
            )
        if self.retry_count > 10:
            raise ValueError(
                f"Retry count too high (max 10), got {self.retry_count}"
            )


@dataclass(frozen=True, slots=True)
class OracleConfig:
    """Main configuration for the ROFL Oracle.

    Attributes:
        source_chain: Configuration for the source blockchain
        target_chain: Configuration for the target Sapphire chain
        monitoring: Configuration for monitoring and event processing
        local_mode: Whether running in local mode (for testing)
        local_private_key: Private key for local mode (optional)
    """

    source_chain: SourceChainConfig
    target_chain: TargetChainConfig
    monitoring: MonitoringConfig
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
        # Load source chain config
        source_rpc_url = os.environ.get(
            "SOURCE_RPC_URL",
            "https://ethereum.publicnode.com",  # Default public RPC
        )

        source_contract = os.environ.get("SOURCE_CONTRACT_ADDRESS", "")
        if not source_contract:
            raise ValueError(
                "SOURCE_CONTRACT_ADDRESS environment variable is required. "
                "This should be the BlockHeaderRequester contract address."
            )

        source_config = SourceChainConfig(
            rpc_url=source_rpc_url, contract_address=source_contract
        )

        # Load target chain config
        # Target chain RPC URL - default to testnet if not specified
        target_rpc_url = os.environ.get(
            "TARGET_RPC_URL", "https://testnet.sapphire.oasis.io"
        )
        target_contract = os.environ.get("CONTRACT_ADDRESS", "")

        if not target_contract:
            raise ValueError(
                "CONTRACT_ADDRESS environment variable is required. "
                "This should be the ROFLAdapter contract address on Sapphire."
            )

        target_config = TargetChainConfig(
            rpc_url=target_rpc_url, contract_address=target_contract
        )

        # Load monitoring config
        polling_interval = int(os.environ.get("POLLING_INTERVAL", "12"))
        lookback_blocks = int(os.environ.get("LOOKBACK_BLOCKS", "9"))
        request_timeout = int(os.environ.get("REQUEST_TIMEOUT", "30"))
        retry_count = int(os.environ.get("RETRY_COUNT", "3"))

        monitoring_config = MonitoringConfig(
            polling_interval=polling_interval,
            lookback_blocks=lookback_blocks,
            request_timeout=request_timeout,
            retry_count=retry_count,
        )

        # Load oracle config
        local_private_key = (
            os.environ.get("LOCAL_PRIVATE_KEY") if local_mode else None
        )

        return cls(
            source_chain=source_config,
            target_chain=target_config,
            monitoring=monitoring_config,
            local_mode=local_mode,
            local_private_key=local_private_key,
        )

    def log_config(self) -> None:
        """Log the configuration in a readable format for debugging."""
        logger.info("=" * 60)
        logger.info("ROFL Oracle Configuration")
        logger.info("=" * 60)

        logger.info("Source Chain:")
        logger.info(f"  RPC URL: {self.source_chain.rpc_url}")
        logger.info(f"  Contract: {self.source_chain.contract_address}")
        if self.source_chain.chain_id:
            logger.info(f"  Chain ID: {self.source_chain.chain_id}")

        logger.info("Target Chain (Sapphire):")
        logger.info(f"  RPC URL: {self.target_chain.rpc_url}")
        logger.info(f"  Contract: {self.target_chain.contract_address}")

        logger.info("Monitoring Settings:")
        logger.info(
            f"  Polling Interval: {self.monitoring.polling_interval} seconds"
        )
        logger.info(f"  Lookback Blocks: {self.monitoring.lookback_blocks}")
        logger.info(
            f"  Request Timeout: {self.monitoring.request_timeout} seconds"
        )
        logger.info(f"  Retry Count: {self.monitoring.retry_count}")

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
        source_config = SourceChainConfig(
            rpc_url=self.source_chain.rpc_url,
            contract_address=self.source_chain.contract_address,
            chain_id=chain_id,
        )

        return OracleConfig(
            source_chain=source_config,
            target_chain=self.target_chain,
            monitoring=self.monitoring,
            local_mode=self.local_mode,
            local_private_key=self.local_private_key,
        )
