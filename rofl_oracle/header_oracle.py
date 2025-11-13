import logging
from asyncio import sleep
from typing import Any

from web3 import Web3
from web3.types import BlockData

from .block_submitter import BlockSubmitter
from .config import (
    EventListenerModeConfig,
    OracleConfig,
    OracleMode,
    WatcherModeConfig,
)
from .event_processor import EventProcessor
from .health_check import HealthCheckServer
from .utils.contract_utility import ContractUtility
from .utils.logging_utility import AsyncPerformanceTimer
from .utils.polling_event_listener import PollingEventListener
from .utils.retry_utility import (
    CircuitBreaker,
    CircuitBreakerConfig,
    RetryConfig,
    retry_with_backoff,
)
from .utils.rofl_utility import RoflUtility

logger = logging.getLogger(__name__)


class HeaderOracle:
    """
    Header Oracle that fetches block headers from a source chain
    and submits them to the ROFLAdapter contract on Oasis Sapphire.
    """

    @classmethod
    async def create(cls, config: OracleConfig) -> "HeaderOracle":
        """
        Factory method to create and initialize HeaderOracle asynchronously.

        :param config: Oracle configuration object
        :return: Initialized HeaderOracle instance
        """
        instance = cls()
        await instance._initialize(config)
        return instance

    async def _initialize(self, config: OracleConfig) -> None:
        """
        Initialize the HeaderOracle with configuration.

        :param config: Oracle configuration object
        """
        self.config = config
        logger.info(
            f"Starting HeaderOracle initialization {'(LOCAL MODE)' if config.local_mode else ''}"
        )

        try:
            # Log configuration
            self.config.log_config()

            # Initialize circuit breakers for resilience
            self.source_rpc_circuit = CircuitBreaker(
                CircuitBreakerConfig(
                    failure_threshold=5,
                    success_threshold=2,
                    timeout=60.0,
                    window_size=10,
                ),
                name="source_rpc",
            )
            self.target_rpc_circuit = CircuitBreaker(
                CircuitBreakerConfig(
                    failure_threshold=5,
                    success_threshold=2,
                    timeout=60.0,
                    window_size=10,
                ),
                name="target_rpc",
            )

            # Configure retry behavior
            self.retry_config = RetryConfig(
                max_attempts=config.common_config.retry_count,
                initial_delay=1.0,
                max_delay=30.0,
                exponential_base=2.0,
                jitter=True,
            )

            # Initialize health check server
            self.health_server = HealthCheckServer(
                port=8080, oracle_instance=self
            )

            if not config.local_mode:
                # Initialize ROFL utility
                logger.debug("Initializing ROFL utility...")
                self.rofl_utility = RoflUtility()

                # Generate/fetch oracle signing key
                logger.info("Generating oracle signing key from ROFL...")
                self.secret = await self.rofl_utility.fetch_key(
                    "rofl-oracle-signer"
                )
                logger.info("Oracle signing key generated successfully")
            else:
                # Use local private key for testing
                logger.debug("Using local private key (LOCAL MODE)")
                self.secret = config.local_private_key
                self.rofl_utility = None
                logger.debug("Local private key loaded")

            # Initialize contract utility with secret for both modes
            logger.debug("Initializing contract utility with signing key...")
            self.contract_utility = ContractUtility(
                config.common_config.target_rpc_url, self.secret
            )
            logger.debug("Contract utility initialized with signing capability")

            # Connect to source chain for block fetching
            logger.debug(
                f"Connecting to source chain at {config.common_config.source_rpc_url}"
            )
            self.source_w3 = Web3(
                Web3.HTTPProvider(
                    config.common_config.source_rpc_url,
                    request_kwargs={
                        "timeout": config.common_config.request_timeout
                    },
                )
            )
            if not self.source_w3.is_connected():
                raise Exception(
                    f"Failed to connect to source chain at {config.common_config.source_rpc_url}"
                )

            # Fetch chain ID from the connected RPC endpoint and update config
            logger.debug("Fetching chain ID...")
            chain_id = self.source_w3.eth.chain_id

            # Update config with chain ID
            self.config = self.config.with_chain_id(chain_id)
            self.source_chain_id = chain_id

            # Initialize block submitter
            logger.debug("Initializing block submitter...")
            self.block_submitter = BlockSubmitter(
                contract_util=self.contract_utility,
                rofl_util=self.rofl_utility if not config.local_mode else None,
                source_chain_id=self.source_chain_id,
                contract_address=config.common_config.target_contract_address,
                request_timeout=config.common_config.request_timeout,
                circuit_breaker=self.target_rpc_circuit,
                retry_config=self.retry_config,
            )
            logger.debug("Block submitter initialized")

            # Register oracle address if in ROFL mode
            if not config.local_mode:
                oracle_address = self.contract_utility.w3.eth.default_account
                logger.info(f"Oracle address: {oracle_address}")

                # Check if oracle is already registered
                current_oracle = (
                    await self.block_submitter.get_registered_oracle()
                )

                if current_oracle != oracle_address:
                    logger.info(
                        "Registering oracle address with ROFLAdapter..."
                    )
                    success = await self.block_submitter.register_oracle()
                    if success:
                        logger.info(
                            f"Oracle address {oracle_address} registered successfully"
                        )
                    else:
                        raise Exception(
                            f"Failed to register oracle address {oracle_address}"
                        )
                else:
                    logger.info(
                        f"Oracle address {oracle_address} already registered"
                    )

            # Initialize event processor
            logger.debug("Initializing event processor...")
            self.event_processor = EventProcessor(
                source_chain_id=self.source_chain_id,
                dedupe_window=1000,  # Track last 1000 events
            )
            logger.debug("Event processor initialized")

            # Load BlockHeaderRequester ABI for event listening (only needed in event listener mode)
            if config.oracle_mode == OracleMode.EVENT_LISTENER:
                logger.debug("Loading BlockHeaderRequester ABI...")
                self.block_requester_abi = (
                    self.contract_utility.get_contract_abi(
                        "BlockHeaderRequester"
                    )
                )
                logger.debug("ABI loaded")
            else:
                self.block_requester_abi = None

            # Initialize polling event listener, push mode, or watcher mode (based on config)
            if config.oracle_mode == OracleMode.WATCHER:
                assert isinstance(config.mode_config, WatcherModeConfig)
                logger.info(
                    f"Watcher mode - monitoring {len(config.mode_config.watch_addresses)} address(es) for interactions"
                )
                for addr in config.mode_config.watch_addresses:
                    logger.info(f"  Watching: {addr}")
                self.event_listener = None
                self.watched_addresses = {
                    addr.lower() for addr in config.mode_config.watch_addresses
                }
                self.processed_blocks = set()
            elif config.oracle_mode == OracleMode.PUSH:
                logger.info("Push oracle mode - will push latest block headers")
                self.event_listener = None
            else:
                assert isinstance(config.mode_config, EventListenerModeConfig)
                logger.debug("Initializing polling event listener...")
                self.event_listener = PollingEventListener(
                    rpc_url=config.common_config.source_rpc_url,
                    contract_address=config.mode_config.contract_address,
                    event_name="BlockHeaderRequested",
                    abi=self.block_requester_abi,
                    lookback_blocks=config.mode_config.lookback_blocks,
                )
                logger.debug("Polling event listener initialized")

            logger.info(
                f"HeaderOracle initialized ({'LOCAL' if config.local_mode else 'ROFL'} mode, source chain: {chain_id})"
            )

        except Exception as e:
            logger.error(f"HeaderOracle initialization failed: {e}")
            logger.error(f"Exception type: {type(e).__name__}", exc_info=True)
            raise

    async def fetch_block_by_number(self, block_number: int) -> BlockData | None:
        """
        Fetch a specific block by number from the source chain with retry logic.

        :param block_number: The block number to fetch
        :return: Block data or None if fetch fails
        """
        try:

            async def _fetch() -> BlockData:
                return self.source_w3.eth.get_block(block_number)

            block = await retry_with_backoff(
                _fetch,
                config=self.retry_config,
                circuit_breaker=self.source_rpc_circuit,
                error_types=(Exception,),
            )
            return block
        except Exception as e:
            logger.error(
                f"Error fetching block {block_number} after retries: {e}"
            )
            return None

    async def process_block_header_event(self, event_data: Any) -> None:
        """
        Process a BlockHeaderRequested event using the EventProcessor.

        This method delegates event parsing, validation, and deduplication
        to the EventProcessor, then handles block fetching and submission
        for valid events.

        :param event_data: Event data from the event listener
        """
        async with AsyncPerformanceTimer("process_block_header_event"):
            try:
                # Use EventProcessor to parse, validate, and check for duplicates
                event = await self.event_processor.process_event(event_data)

                if not event:
                    # Event was filtered, duplicate, or invalid
                    return

                logger.info("Processing validated BlockHeaderRequested event:")
                logger.info(f"  Chain ID: {event.chain_id}")
                logger.info(f"  Requested Block: {event.block_number}")
                logger.info(f"  Requester: {event.requester}")
                logger.info(f"  Event Block: {event.event_block_number}")

                # Fetch the requested block
                block = await self.fetch_block_by_number(event.block_number)

                if block:
                    block_hash = block.get("hash")

                    if block_hash is not None:
                        # Convert block_hash to hex string with 0x prefix
                        block_hash_hex = (
                            block_hash.hex()
                            if isinstance(block_hash, bytes)
                            else block_hash
                        )
                        if not block_hash_hex.startswith("0x"):
                            block_hash_hex = "0x" + block_hash_hex

                        # Submit the block header using BlockSubmitter
                        success = (
                            await self.block_submitter.submit_block_header(
                                event.block_number, block_hash_hex
                            )
                        )

                        if success:
                            logger.info(
                                f"Successfully submitted block {event.block_number} header to Sapphire"
                            )
                        else:
                            logger.error(
                                f"Failed to submit block {event.block_number} header"
                            )
                else:
                    logger.error(f"Could not fetch block {event.block_number}")

                # Periodically log metrics
                if self.event_processor.events_processed % 10 == 0:
                    self.event_processor.log_metrics()

            except Exception as e:
                logger.error(
                    f"Error processing BlockHeaderRequested event: {e}",
                    exc_info=True,
                )

    async def push_latest_block_header(self) -> None:
        """
        Push the latest block header from the source chain to the target chain.
        Used in push oracle mode.
        """
        async with AsyncPerformanceTimer("push_latest_block_header"):
            try:
                # Get the latest block from source chain
                latest_block_number = self.source_w3.eth.block_number
                last_stored_block = (
                    await self.block_submitter.get_latest_block_number()
                )

                if last_stored_block is None or last_stored_block == 0:
                    next_block_to_push = latest_block_number
                    end_block = latest_block_number
                else:
                    next_block_to_push = last_stored_block + 1
                    end_block = min(latest_block_number, last_stored_block + 20)

                while next_block_to_push <= end_block:
                    logger.info(
                        f"Pushing latest block header: {next_block_to_push}"
                    )
                    # Fetch the block at the current contract block number
                    block = await self.fetch_block_by_number(next_block_to_push)

                    if block:
                        block_hash = block.get("hash")

                        if block_hash is not None:
                            # Convert block_hash to hex string with 0x prefix
                            block_hash_hex = (
                                block_hash.hex()
                                if isinstance(block_hash, bytes)
                                else block_hash
                            )
                            if not block_hash_hex.startswith("0x"):
                                block_hash_hex = "0x" + block_hash_hex

                            # Submit the block header using BlockSubmitter
                            success = (
                                await self.block_submitter.submit_block_header(
                                    next_block_to_push, block_hash_hex
                                )
                            )

                            if success:
                                logger.info(
                                    f"Successfully pushed block {next_block_to_push} header to Sapphire"
                                )
                                next_block_to_push += 1
                            else:
                                logger.error(
                                    f"Failed to push block {next_block_to_push} header"
                                )
                                break
                        else:
                            logger.error(
                                f"Block {next_block_to_push} has no hash"
                            )
                            break
                    else:
                        logger.error(
                            f"Could not fetch latest block {next_block_to_push}"
                        )
                        break

            except Exception as e:
                logger.error(
                    f"Error pushing latest block header: {e}",
                    exc_info=True,
                )

    async def watch_addresses_for_interactions(self) -> None:
        """
        Watch configured addresses for any interactions and push blocks when detected.
        Used in watcher mode.
        """
        try:
            # Get the latest block from source chain
            latest_block_number = self.source_w3.eth.block_number

            # Get the last processed block (stored on target chain)
            last_stored_block = (
                await self.block_submitter.get_latest_block_number()
            )

            # Determine starting point
            if last_stored_block is None or last_stored_block == 0:
                assert isinstance(self.config.mode_config, WatcherModeConfig)
                start_block = max(
                    0,
                    latest_block_number
                    - self.config.mode_config.lookback_blocks,
                )
            else:
                start_block = last_stored_block + 1

            # Don't scan too far ahead
            end_block = min(latest_block_number, start_block + 50)

            if start_block > latest_block_number:
                logger.debug(
                    f"Watcher is up to date (last: {last_stored_block}, latest: {latest_block_number})"
                )
                return

            logger.info(
                f"Scanning blocks {start_block} to {end_block} for watched address interactions"
            )

            # Scan blocks for interactions with watched addresses
            for block_number in range(start_block, end_block + 1):
                if await self._check_block_for_interactions(block_number):
                    logger.info(
                        f"Interaction detected in block {block_number}, pushing block header"
                    )

                    # Fetch and push the block
                    block = await self.fetch_block_by_number(block_number)
                    if block:
                        block_hash = block.get("hash")
                        if block_hash is not None:
                            # Convert block_hash to hex string with 0x prefix
                            block_hash_hex = (
                                block_hash.hex()
                                if isinstance(block_hash, bytes)
                                else block_hash
                            )
                            if not block_hash_hex.startswith("0x"):
                                block_hash_hex = "0x" + block_hash_hex

                            # Submit the block header
                            success = (
                                await self.block_submitter.submit_block_header(
                                    block_number, block_hash_hex
                                )
                            )

                            if success:
                                logger.info(
                                    f"Successfully pushed block {block_number} header with interaction"
                                )
                            else:
                                logger.error(
                                    f"Failed to push block {block_number} header"
                                )
                                break  # Stop on failure
                        else:
                            logger.error(f"Block {block_number} has no hash")
                            break
                    else:
                        logger.error(f"Could not fetch block {block_number}")
                        break

        except Exception as e:
            logger.error(
                f"Error watching addresses for interactions: {e}",
                exc_info=True,
            )

    async def _check_block_for_interactions(self, block_number: int) -> bool:
        """
        Check if a block contains any interactions with watched addresses.

        Checks both direct transactions and optionally internal transactions
        (if enable_internal_tx_detection is enabled).

        :param block_number: Block number to check
        :return: True if interactions detected, False otherwise
        """
        try:
            block = await self.fetch_block_by_number(block_number)
            if not block:
                return False

            transactions = block.get("transactions", [])
            assert isinstance(self.config.mode_config, WatcherModeConfig)
            check_internal = (
                self.config.mode_config.enable_internal_tx_detection
            )

            # If transactions are just hashes, we need to fetch full transaction details
            if transactions and isinstance(transactions[0], str):
                # Transactions are hashes, need to fetch details
                for tx_hash in transactions:
                    try:
                        tx = self.source_w3.eth.get_transaction(tx_hash)
                        if self._is_watched_transaction(tx):
                            logger.debug(
                                f"Found direct interaction in tx {tx_hash.hex() if isinstance(tx_hash, bytes) else tx_hash}"
                            )
                            return True

                        # Check internal transactions if enabled
                        if check_internal:
                            tx_hash_str = (
                                tx_hash.hex()
                                if isinstance(tx_hash, bytes)
                                else tx_hash
                            )
                            if await self._check_internal_transactions(
                                tx_hash_str
                            ):
                                logger.debug(
                                    f"Found internal interaction in tx {tx_hash_str}"
                                )
                                return True

                    except Exception as e:
                        logger.warning(
                            f"Error fetching transaction {tx_hash}: {e}"
                        )
                        continue
            else:
                # Transactions are full objects
                for tx in transactions:
                    if self._is_watched_transaction(tx):
                        tx_hash = tx.get("hash", "unknown")
                        logger.debug(
                            f"Found direct interaction in tx {tx_hash.hex() if isinstance(tx_hash, bytes) else tx_hash}"
                        )
                        return True

                    # Check internal transactions if enabled
                    if check_internal:
                        tx_hash = tx.get("hash")
                        if tx_hash:
                            tx_hash_str = (
                                tx_hash.hex()
                                if isinstance(tx_hash, bytes)
                                else tx_hash
                            )
                            if await self._check_internal_transactions(
                                tx_hash_str
                            ):
                                logger.debug(
                                    f"Found internal interaction in tx {tx_hash_str}"
                                )
                                return True

            return False

        except Exception as e:
            logger.error(
                f"Error checking block {block_number} for interactions: {e}"
            )
            return False

    def _is_watched_transaction(self, tx: Any) -> bool:
        """
        Check if a transaction involves any watched addresses.

        :param tx: Transaction object
        :return: True if transaction involves watched address
        """
        if not tx:
            return False

        # Check 'from' address
        from_addr = tx.get("from", "").lower() if tx.get("from") else ""
        if from_addr in self.watched_addresses:
            return True

        # Check 'to' address
        to_addr = tx.get("to", "").lower() if tx.get("to") else ""
        return to_addr in self.watched_addresses

    async def _check_internal_transactions(self, tx_hash: str) -> bool:
        """
        Check if a transaction has internal calls to watched addresses.

        Uses debug_traceTransaction to detect internal transactions.
        Requires archive node access and debug API support.

        :param tx_hash: Transaction hash to trace
        :return: True if internal transactions involve watched addresses
        """
        try:
            trace_result = self.source_w3.provider.make_request(
                "debug_traceTransaction",
                [tx_hash, {"tracer": "callTracer"}],
            )

            if "result" not in trace_result:
                return False

            return self._check_trace_for_watched_addresses(
                trace_result["result"]
            )

        except Exception as e:
            logger.debug(
                f"Internal transaction tracing not available or failed for {tx_hash}: {e}"
            )
            return False

    def _check_trace_for_watched_addresses(self, trace: dict[str, Any]) -> bool:
        """
        Recursively check trace results for watched addresses.

        :param trace: Trace result from debug_traceTransaction
        :return: True if any call involves watched addresses
        """
        if not trace:
            return False

        # Check 'to' address in this call
        to_addr = trace.get("to", "").lower() if trace.get("to") else ""
        if to_addr in self.watched_addresses:
            logger.debug(f"Found watched address in internal call: {to_addr}")
            return True

        # Check 'from' address
        from_addr = trace.get("from", "").lower() if trace.get("from") else ""
        if from_addr in self.watched_addresses:
            logger.debug(
                f"Found watched address as caller in internal call: {from_addr}"
            )
            return True

        # Recursively check nested calls
        calls = trace.get("calls", [])
        for call in calls:
            if self._check_trace_for_watched_addresses(call):
                return True

        return False

    async def shutdown(self) -> None:
        """Gracefully shutdown the oracle."""
        logger.info("Shutting down HeaderOracle...")
        if self.event_listener:
            await self.event_listener.stop()
        if hasattr(self, "health_server"):
            await self.health_server.stop()
        logger.info("HeaderOracle shutdown complete")

    async def run(self) -> None:
        """
        Main entry point for the HeaderOracle.
        Starts event polling, push mode, or watcher mode based on configuration.
        """
        logger.info("Starting HeaderOracle...")

        try:
            # Start health check server
            if hasattr(self, "health_server"):
                await self.health_server.start()
                logger.info(
                    "Health check server running on http://0.0.0.0:8080/health"
                )

            if self.config.oracle_mode == OracleMode.WATCHER:
                assert isinstance(self.config.mode_config, WatcherModeConfig)
                logger.info(
                    f"Running in watcher mode - monitoring {len(self.config.mode_config.watch_addresses)} address(es)"
                )
                await self._run_watcher_mode()
            elif self.config.oracle_mode == OracleMode.PUSH:
                logger.info(
                    "Running in push oracle mode - pushing latest block headers"
                )
                await self._run_push_mode()
            else:
                assert isinstance(
                    self.config.mode_config, EventListenerModeConfig
                )
                logger.info(
                    f"Running in event listener mode - polling for BlockHeaderRequested events from {self.config.mode_config.contract_address}"
                )
                await self._run_event_listener_mode()
        finally:
            if hasattr(self, "health_server"):
                await self.health_server.stop()

    async def _run_push_mode(self) -> None:
        """Run in push oracle mode - continuously push latest block headers."""
        try:
            from .config import PushModeConfig

            assert isinstance(self.config.mode_config, PushModeConfig)
            logger.info(
                f"Starting push oracle with {self.config.mode_config.push_interval} second interval..."
            )

            # Main push loop
            while True:
                await self.push_latest_block_header()
                await sleep(self.config.mode_config.push_interval)

        except KeyboardInterrupt:
            logger.info("Push oracle interrupted")
        except Exception as e:
            logger.error(f"Error in push oracle loop: {e}", exc_info=True)
        finally:
            logger.info("Push oracle stopped")

    async def _run_watcher_mode(self) -> None:
        """Run in watcher mode - continuously scan for address interactions."""
        try:
            assert isinstance(self.config.mode_config, WatcherModeConfig)
            logger.info(
                f"Starting watcher with {self.config.mode_config.scan_interval} second interval..."
            )

            # Main watcher loop
            while True:
                await self.watch_addresses_for_interactions()
                await sleep(self.config.mode_config.scan_interval)

        except KeyboardInterrupt:
            logger.info("Watcher interrupted")
        except Exception as e:
            logger.error(f"Error in watcher loop: {e}", exc_info=True)
        finally:
            logger.info("Watcher stopped")

    async def _run_event_listener_mode(self) -> None:
        """Run in event listener mode - poll for BlockHeaderRequested events."""
        try:
            assert isinstance(self.config.mode_config, EventListenerModeConfig)
            logger.info(
                f"Starting polling event listener with {self.config.mode_config.polling_interval} second interval..."
            )

            # Start event polling (this will run indefinitely)
            await self.event_listener.start_polling(
                callback=self.process_block_header_event,
                interval=self.config.mode_config.polling_interval,
            )

        except Exception as e:
            logger.error(f"Error in event listener loop: {e}", exc_info=True)
        finally:
            logger.info("Cleaning up...")
            if self.event_listener:
                await self.event_listener.stop()
            logger.info("HeaderOracle stopped")
