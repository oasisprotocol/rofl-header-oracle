"""Entry point for the ROFL Header Oracle backend service.

This module provides the main entry point for the oracle service
that runs as a containerized backend in either production (ROFL)
or local testing mode.
"""

import argparse
import asyncio
import logging
import os
import sys

from rofl_oracle.config import OracleConfig
from rofl_oracle.header_oracle import HeaderOracle
from rofl_oracle.utils.logging_utility import setup_structured_logging

logger = logging.getLogger(__name__)


async def main() -> None:
    """Main entry point for the ROFL Header Oracle backend service.

    Parses startup arguments, loads configuration from environment,
    and starts the oracle service that continuously polls for events.

    Raises:
        SystemExit: On configuration or runtime errors
    """
    # Parse startup arguments
    parser = argparse.ArgumentParser(description="ROFL Header Oracle")
    parser.add_argument(
        "--local",
        action="store_true",
        default=False,
        help="Run in local mode without ROFL utilities (for testing)",
    )
    parser.add_argument(
        "--log-level",
        default=os.environ.get("LOG_LEVEL", "INFO"),
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        help="Set the logging level (default: INFO)",
    )
    parser.add_argument(
        "--json-logs",
        action="store_true",
        default=os.environ.get("JSON_LOGS", "").lower() in ("true", "1", "yes"),
        help="Enable JSON-formatted structured logging",
    )
    args: argparse.Namespace = parser.parse_args()

    setup_structured_logging(args.log_level, use_json=args.json_logs)

    logger.info(
        f"=== ROFL Header Oracle Starting {'(LOCAL MODE)' if args.local else ''} ==="
    )

    try:
        # Load configuration from environment
        config: OracleConfig = OracleConfig.from_env(local_mode=args.local)
        header_oracle: HeaderOracle = await HeaderOracle.create(config)
        await header_oracle.run()

    except ValueError as e:
        logger.error(f"Configuration error: {e}")
        logger.error("Required environment variables:")
        logger.error("  - SOURCE_RPC_URL: Source chain RPC endpoint")
        logger.error(
            "  - TARGET_RPC_URL: Target chain RPC endpoint (default: testnet)"
        )
        logger.error(
            "  - SOURCE_CONTRACT_ADDRESS: BlockHeaderRequester contract address (for event_listener mode only)"
        )
        logger.error(
            "  - WATCH_ADDRESSES: Comma-separated addresses to watch (for watcher mode only)"
        )
        logger.error("  - ROFL_ADAPTER_ADDRESS: ROFLAdapter contract address")
        if args.local:
            logger.error("  - LOCAL_PRIVATE_KEY: Private key for local mode")
        sys.exit(1)

    except KeyboardInterrupt:
        logger.info("\nReceived interrupt signal, shutting down gracefully...")
        sys.exit(0)

    except Exception as e:
        logger.error(f"Fatal Error: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
