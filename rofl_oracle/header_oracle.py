import logging
import time
from asyncio import sleep
from typing import Any

from web3 import Web3
from web3.types import BlockData

from .block_submitter import BlockSubmitter
from .config import (
    EventListenerModeConfig,
    OracleConfig,
    OracleMode,
    TokenWatcherModeConfig,
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

TRANSFER_EVENT_SIGNATURE = (
    "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
)


class HeaderOracle:
    """
    Header Oracle that fetches block headers from a source chain
    and submits them to the ROFLAdapter contract on Oasis Sapphire.
    """

    last_heartbeat_time: float | None = None

    @property
    def _log_prefix(self) -> str:
        """Log prefix with chain ID for multi-chain disambiguation."""
        chain_id = getattr(self, "source_chain_id", None)
        return f"[chain:{chain_id}]" if chain_id else "[chain:?]"

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

            logger.debug("Fetching chain ID...")
            chain_id = self.source_w3.eth.chain_id
            self.config = self.config.with_chain_id(chain_id)
            self.source_chain_id = chain_id
            logger.info(f"Connected to source chain with ID: {chain_id}")

            if not config.local_mode:
                logger.debug("Initializing ROFL utility...")
                self.rofl_utility = RoflUtility()

                # Chain-specific key derivation to avoid nonce collisions
                key_id = f"rofl-oracle-signer-{chain_id}"
                logger.info(f"Deriving chain-specific signing key: {key_id}")
                self.secret = await self.rofl_utility.fetch_key(key_id)
                logger.info("Chain-specific signing key generated successfully")
            else:
                # Use local private key for testing
                logger.debug("Using local private key (LOCAL MODE)")
                self.secret = config.local_private_key
                self.rofl_utility = None
                logger.debug("Local private key loaded")

            logger.debug("Initializing contract utility with signing key...")
            self.contract_utility = ContractUtility(
                config.common_config.target_rpc_url, self.secret
            )
            logger.debug("Contract utility initialized with signing capability")

            # Check reporter balance before proceeding
            reporter_address = self.contract_utility.w3.eth.default_account
            logger.info(f"Reporter address: {reporter_address}")
            await self._wait_for_sufficient_balance(
                reporter_address,
                config.common_config.min_reporter_balance
            )

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
                min_reporter_balance=config.common_config.min_reporter_balance,
            )
            logger.debug("Block submitter initialized")

            # Register chain-specific reporter if in ROFL mode
            if not config.local_mode:
                reporter_address = self.contract_utility.w3.eth.default_account
                logger.info(
                    f"Chain {self.source_chain_id} reporter address: {reporter_address}"
                )

                # Check if this chain's reporter is already registered
                current_reporter = (
                    await self.block_submitter.get_registered_reporter()
                )

                if current_reporter != reporter_address:
                    logger.info(
                        f"Registering reporter for chain {self.source_chain_id}..."
                    )
                    await self.block_submitter.register_reporter()
                    logger.info(
                        f"Reporter {reporter_address} registered for chain {self.source_chain_id}"
                    )
                else:
                    logger.info(
                        f"Reporter already registered for chain {self.source_chain_id}"
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

            # Initialize mode-specific components
            if config.oracle_mode == OracleMode.TOKEN_WATCHER:
                assert isinstance(config.mode_config, TokenWatcherModeConfig)
                logger.info(
                    f"Token watcher mode - monitoring {len(config.mode_config.token_addresses)} token(s) "
                    f"for transfers to {len(config.mode_config.recipient_addresses)} recipient(s)"
                )
                for addr in config.mode_config.token_addresses:
                    logger.info(f"  Token: {addr}")
                for addr in config.mode_config.recipient_addresses:
                    logger.info(f"  Recipient: {addr}")
                self.event_listener = None
                self.last_scanned_block: int | None = None
                self.processed_tx_hashes: dict[str, None] = {}
                self.max_tx_cache_size = 10000
                self.last_heartbeat_time: float | None = None
            elif config.oracle_mode == OracleMode.WATCHER:
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
                # In-memory scan position tracking. Intentionally not persisted:
                # - On restart, recovers from contract's lastStoredBlock state
                # - Ensures no blocks are permanently skipped even if process crashes
                # - Trades potential re-scanning for data integrity
                self.last_scanned_block: int | None = None
                # Heartbeat tracking for periodic checkpoint submissions
                # Ensures sync time is bounded even without watched address activity
                self.last_heartbeat_time: float | None = None
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

    async def _wait_for_sufficient_balance(
        self, address: str, min_balance: float
    ) -> None:
        """
        Check reporter balance and wait if insufficient.
        Blocks startup until the reporter has enough funds.

        Args:
            address: Reporter wallet address
            min_balance: Minimum required balance in native tokens
        """
        check_interval = 30  # seconds
        min_balance_wei = int(min_balance * 10**18)

        while True:
            try:
                balance = self.contract_utility.w3.eth.get_balance(address)
                balance_native = balance / 10**18

                if balance >= min_balance_wei:
                    logger.info(
                        f"Reporter {address} has sufficient balance: {balance_native:.6f} native tokens"
                    )
                    return

                logger.warning(
                    f"⚠️  Insufficient reporter balance!\n"
                    f"    Address: {address}\n"
                    f"    Current: {balance_native:.6f} native tokens\n"
                    f"    Minimum: {min_balance:.6f} native tokens\n"
                    f"    Please fund this address to continue.\n"
                    f"    Checking again in {check_interval}s..."
                )
                await sleep(check_interval)

            except Exception as e:
                logger.error(f"Error checking balance for {address}: {e}")
                await sleep(check_interval)

    async def fetch_block_by_number(
        self, block_number: int
    ) -> BlockData | None:
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
                    block_hash_hex = self._normalize_block_hash(block.get("hash"))

                    if block_hash_hex is not None:
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

                block_numbers = []
                block_hashes = []

                for block_num in range(next_block_to_push, end_block + 1):
                    logger.info(
                        f"Fetching block {block_num} for batch submission"
                    )
                    block = await self.fetch_block_by_number(block_num)

                    if block:
                        block_hash_hex = self._normalize_block_hash(
                            block.get("hash")
                        )

                        if block_hash_hex is not None:
                            block_numbers.append(block_num)
                            block_hashes.append(block_hash_hex)
                        else:
                            logger.error(f"Block {block_num} has no hash")
                            break
                    else:
                        logger.error(f"Could not fetch block {block_num}")
                        break

                if block_numbers:
                    logger.info(
                        f"Submitting batch of {len(block_numbers)} blocks: {block_numbers[0]} to {block_numbers[-1]}"
                    )
                    success = (
                        await self.block_submitter.submit_block_headers_batch(
                            block_numbers, block_hashes
                        )
                    )

                    if success:
                        logger.info(
                            f"Successfully pushed {len(block_numbers)} block headers to Sapphire"
                        )
                    else:
                        logger.error(
                            f"Failed to push batch of {len(block_numbers)} block headers"
                        )

            except Exception as e:
                logger.error(
                    f"Error pushing latest block header: {e}",
                    exc_info=True,
                )

    async def watch_addresses_for_interactions(self) -> None:
        """
        Watch configured addresses for any interactions and push blocks when detected.
        Used in watcher mode.

        Also submits periodic heartbeat blocks when no activity is detected,
        to ensure sync time is bounded on oracle restart.
        """
        try:
            # Get the latest block from source chain
            latest_block_number = self.source_w3.eth.block_number
            assert isinstance(self.config.mode_config, WatcherModeConfig)

            current_time = time.time()
            heartbeat_interval = self.config.mode_config.heartbeat_interval_seconds
            heartbeat_due = (
                self.last_heartbeat_time is None
                or (current_time - self.last_heartbeat_time) >= heartbeat_interval
            )

            # Determine starting point using last_scanned_block (in-memory state)
            # Track the last processed block for logging purposes
            last_processed_block: int | None = None

            if self.last_scanned_block is not None:
                start_block = self.last_scanned_block + 1
                last_processed_block = self.last_scanned_block
            else:
                last_stored_block = (
                    await self.block_submitter.get_latest_block_number()
                )
                if last_stored_block is not None and last_stored_block > 0:
                    start_block = last_stored_block + 1
                    last_processed_block = last_stored_block
                    logger.info(
                        f"Resuming from last stored block {last_stored_block}"
                    )
                else:
                    start_block = max(
                        0,
                        latest_block_number
                        - self.config.mode_config.lookback_blocks,
                    )

            batch_size = self.config.mode_config.batch_size
            end_block = min(latest_block_number, start_block + batch_size - 1)

            if start_block > latest_block_number:
                logger.info(
                    f"Watcher is up to date (last: {last_processed_block}, latest: {latest_block_number})"
                )
                return

            num_blocks = end_block - start_block + 1
            logger.info(
                f"{self._log_prefix} Scanning {num_blocks} blocks ({start_block}-{end_block})"
            )

            blocks_with_interactions = []
            block_hashes_to_submit = []
            last_successful_block = start_block - 1

            for block_number in range(start_block, end_block + 1):
                if (
                    block_number - start_block
                ) % 10 == 0 and block_number != start_block:
                    logger.info(
                        f"{self._log_prefix} Progress: {block_number - start_block}/{num_blocks} blocks"
                    )

                try:
                    if await self._check_block_for_interactions(block_number):
                        logger.info(
                            f"{self._log_prefix} Interaction in block {block_number}"
                        )

                        block = await self.fetch_block_by_number(block_number)
                        if block:
                            block_hash_hex = self._normalize_block_hash(
                                block.get("hash")
                            )
                            if block_hash_hex is not None:
                                blocks_with_interactions.append(block_number)
                                block_hashes_to_submit.append(block_hash_hex)
                            else:
                                logger.error(
                                    f"Block {block_number} has no hash, stopping scan"
                                )
                                break
                        else:
                            logger.error(
                                f"Could not fetch block {block_number}, stopping scan"
                            )
                            break

                    last_successful_block = block_number

                except Exception as e:
                    logger.error(f"Error processing block {block_number}: {e}")
                    break  # Stop and retry this block next cycle

            submission_succeeded = True

            # Submit all blocks with interactions in a single batch
            if blocks_with_interactions:
                logger.info(
                    f"{self._log_prefix} Submitting {len(blocks_with_interactions)} blocks"
                )
                success = await self.block_submitter.submit_block_headers_batch(
                    blocks_with_interactions, block_hashes_to_submit
                )

                if success:
                    logger.info(
                        f"{self._log_prefix} Submitted {len(blocks_with_interactions)} block headers"
                    )
                    # Reset heartbeat timer on successful activity submission
                    self.last_heartbeat_time = time.time()
                    submission_succeeded = True
                else:
                    logger.error(
                        f"{self._log_prefix} Submission failed, will retry"
                    )
                    submission_succeeded = False

            elif heartbeat_due and last_successful_block >= start_block:
                # Heartbeat: use last scanned block as checkpoint
                heartbeat_block = last_successful_block
                logger.info(
                    f"{self._log_prefix} Heartbeat block {heartbeat_block}"
                )

                block = await self.fetch_block_by_number(heartbeat_block)
                if block:
                    block_hash_hex = self._normalize_block_hash(block.get("hash"))
                    if block_hash_hex is not None:
                        success = await self.block_submitter.submit_block_header(
                            heartbeat_block, block_hash_hex
                        )

                        if success:
                            logger.info(
                                f"Heartbeat: stored block {heartbeat_block} as checkpoint"
                            )
                        else:
                            logger.warning(
                                f"Heartbeat submission failed for block {heartbeat_block}"
                            )
                    else:
                        logger.warning(
                            f"Heartbeat block {heartbeat_block} has no hash"
                        )
                else:
                    logger.warning(
                        f"Could not fetch heartbeat block {heartbeat_block}"
                    )

                # Always update timer, avoid retry storm for non-critical block
                self.last_heartbeat_time = time.time()

            elif heartbeat_due:
                # No new blocks scanned - either chain idle or RPC issue
                logger.info(
                    f"{self._log_prefix} Heartbeat skipped: no new blocks to checkpoint"
                )
                self.last_heartbeat_time = time.time()

            # Update scan position only if submission succeeded (or no submission needed)
            if submission_succeeded and last_successful_block >= start_block:
                self.last_scanned_block = last_successful_block
            elif not submission_succeeded:
                logger.warning(
                    f"Keeping scan position at {self.last_scanned_block} due to submission failure"
                )

            scanned_count = (
                last_successful_block - start_block + 1
                if last_successful_block >= start_block
                else 0
            )
            logger.info(
                f"{self._log_prefix} Scan complete: {scanned_count}/{num_blocks} blocks, {len(blocks_with_interactions)} interactions"
            )

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
            block = self.source_w3.eth.get_block(
                block_number, full_transactions=True
            )
            if not block:
                return False

            transactions = block.get("transactions", [])
            assert isinstance(self.config.mode_config, WatcherModeConfig)
            check_internal = (
                self.config.mode_config.enable_internal_tx_detection
            )

            for tx in transactions:
                if self._is_watched_transaction(tx):
                    tx_hash = tx.get("hash", "unknown")
                    logger.debug(
                        f"Found direct interaction in tx {tx_hash.hex() if isinstance(tx_hash, bytes) else tx_hash}"
                    )
                    return True

                if check_internal:
                    tx_hash = tx.get("hash")
                    if tx_hash:
                        tx_hash_str = (
                            tx_hash.hex()
                            if isinstance(tx_hash, bytes)
                            else tx_hash
                        )
                        if await self._check_internal_transactions(tx_hash_str):
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

    def _normalize_block_hash(self, block_hash: bytes | str | None) -> str | None:
        """
        Normalize block hash to hex string with 0x prefix.

        :param block_hash: Block hash as bytes, hex string, or None
        :return: Normalized hex string with 0x prefix, or None if input is None
        """
        if block_hash is None:
            return None
        hex_str = block_hash.hex() if isinstance(block_hash, bytes) else block_hash
        return hex_str if hex_str.startswith("0x") else f"0x{hex_str}"

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

    async def watch_token_transfers(self) -> None:
        try:
            latest_block_number = self.source_w3.eth.block_number
            assert isinstance(self.config.mode_config, TokenWatcherModeConfig)

            current_time = time.time()
            heartbeat_interval = self.config.mode_config.heartbeat_interval_seconds
            heartbeat_due = (
                self.last_heartbeat_time is None
                or (current_time - self.last_heartbeat_time) >= heartbeat_interval
            )

            if self.last_scanned_block is not None:
                start_block = self.last_scanned_block + 1
            else:
                start_block = latest_block_number
                logger.info(f"{self._log_prefix} First run: starting from block {start_block}")

            if start_block > latest_block_number:
                if heartbeat_due:
                    logger.info(
                        f"{self._log_prefix} Heartbeat skipped: no new blocks to checkpoint"
                    )
                    self.last_heartbeat_time = time.time()
                return

            end_block = min(
                start_block + self.config.mode_config.max_blocks_per_scan,
                latest_block_number,
            )
            num_blocks = end_block - start_block + 1
            logger.info(
                f"{self._log_prefix} Scanning {num_blocks} blocks ({start_block}-{end_block})"
            )

            blocks_with_transfers = set()

            # Build recipient topics array for OR matching (reduces RPC calls from O(n*m) to O(n))
            recipient_topics = [
                "0x" + addr[2:].lower().zfill(64)
                for addr in self.config.mode_config.recipient_addresses
            ]

            for token_addr in self.config.mode_config.token_addresses:
                filter_params = {
                    "fromBlock": hex(start_block),
                    "toBlock": hex(end_block),
                    "address": token_addr,
                    "topics": [
                        TRANSFER_EVENT_SIGNATURE,
                        None,
                        recipient_topics,  # Array = OR matching across recipients
                    ],
                }

                try:
                    logs = self.source_w3.eth.get_logs(filter_params)

                    for log in logs:
                        tx_hash = log.get("transactionHash")
                        block_num = log.get("blockNumber")

                        if tx_hash and block_num:
                            tx_hash_str = (
                                tx_hash.hex()
                                if isinstance(tx_hash, bytes)
                                else tx_hash
                            )

                            if tx_hash_str in self.processed_tx_hashes:
                                continue

                            self.processed_tx_hashes[tx_hash_str] = None

                            if (
                                len(self.processed_tx_hashes)
                                > self.max_tx_cache_size
                            ):
                                keys_to_remove = list(
                                    self.processed_tx_hashes.keys()
                                )[: self.max_tx_cache_size // 2]
                                for key in keys_to_remove:
                                    del self.processed_tx_hashes[key]

                            blocks_with_transfers.add(block_num)
                            logger.info(
                                f"{self._log_prefix} Transfer: block={block_num}, tx={tx_hash_str[:18]}..."
                            )

                except Exception as e:
                    logger.error(
                        f"{self._log_prefix} Query failed for {token_addr}, aborting scan to retry: {e}"
                    )
                    return

            if blocks_with_transfers:
                block_hashes_to_submit = []
                sorted_blocks = sorted(blocks_with_transfers)

                for block_num in sorted_blocks:
                    block = await self.fetch_block_by_number(block_num)
                    if block:
                        block_hash_hex = self._normalize_block_hash(
                            block.get("hash")
                        )
                        if block_hash_hex:
                            block_hashes_to_submit.append(block_hash_hex)

                if len(sorted_blocks) == len(block_hashes_to_submit):
                    success = (
                        await self.block_submitter.submit_block_headers_batch(
                            sorted_blocks, block_hashes_to_submit
                        )
                    )
                    if success:
                        logger.info(
                            f"{self._log_prefix} Submitted {len(sorted_blocks)} block headers"
                        )
                        self.last_scanned_block = end_block
                        # Reset heartbeat timer after successful submission
                        self.last_heartbeat_time = time.time()
                    else:
                        logger.warning(
                            f"{self._log_prefix} Submission failed, will retry {sorted_blocks[0]}-{sorted_blocks[-1]}"
                        )
                else:
                    logger.warning(
                        f"Could not fetch all block hashes "
                        f"({len(block_hashes_to_submit)}/{len(sorted_blocks)}) - will retry"
                    )
            elif heartbeat_due and self.last_scanned_block is not None:
                # No transfers but heartbeat due - submit checkpoint (skip on first run)
                heartbeat_block = end_block
                logger.info(
                    f"{self._log_prefix} Heartbeat: submitting block {heartbeat_block} as checkpoint"
                )
                block = await self.fetch_block_by_number(heartbeat_block)
                if block:
                    block_hash_hex = self._normalize_block_hash(block.get("hash"))
                    if block_hash_hex is not None:
                        success = await self.block_submitter.submit_block_header(
                            heartbeat_block, block_hash_hex
                        )
                        if success:
                            logger.info(
                                f"{self._log_prefix} Heartbeat: stored block {heartbeat_block}"
                            )
                        else:
                            logger.warning(
                                f"{self._log_prefix} Heartbeat submission failed for block {heartbeat_block}"
                            )
                self.last_scanned_block = end_block
                self.last_heartbeat_time = time.time()
            else:
                # No transfers found, no heartbeat due - safe to advance scan position
                self.last_scanned_block = end_block

            logger.info(
                f"{self._log_prefix} Scan complete: {len(blocks_with_transfers)} transfers in {num_blocks} blocks"
            )

        except Exception as e:
            logger.error(f"Error in token watcher: {e}", exc_info=True)

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
        Starts event polling, push mode, watcher mode, or token watcher mode based on configuration.
        """
        logger.info("Starting HeaderOracle...")

        try:
            # Start health check server
            if hasattr(self, "health_server"):
                await self.health_server.start()
                logger.info(
                    "Health check server running on http://0.0.0.0:8080/health"
                )

            if self.config.oracle_mode == OracleMode.TOKEN_WATCHER:
                assert isinstance(
                    self.config.mode_config, TokenWatcherModeConfig
                )
                logger.info(
                    f"Running in token watcher mode - monitoring {len(self.config.mode_config.token_addresses)} token(s) "
                    f"for transfers to {len(self.config.mode_config.recipient_addresses)} recipient(s)"
                )
                await self._run_token_watcher_mode()
            elif self.config.oracle_mode == OracleMode.WATCHER:
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

    async def _run_token_watcher_mode(self) -> None:
        """Run in token watcher mode - continuously scan for ERC20 token transfers."""
        try:
            assert isinstance(self.config.mode_config, TokenWatcherModeConfig)
            logger.info(
                f"Starting token watcher with {self.config.mode_config.scan_interval} second interval..."
            )

            while True:
                await self.watch_token_transfers()
                await sleep(self.config.mode_config.scan_interval)

        except KeyboardInterrupt:
            logger.info("Token watcher interrupted")
        except Exception as e:
            logger.error(f"Error in token watcher loop: {e}", exc_info=True)
        finally:
            logger.info("Token watcher stopped")

    async def _run_event_listener_mode(self) -> None:
        """Run in event listener mode - poll for BlockHeaderRequested events."""
        try:
            assert isinstance(self.config.mode_config, EventListenerModeConfig)
            logger.info(
                f"Starting polling event listener with {self.config.mode_config.polling_interval} second interval..."
            )

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
