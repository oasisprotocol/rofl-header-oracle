import logging
from asyncio import sleep
from typing import Any

from web3 import Web3
from web3.types import BlockData

from .block_submitter import BlockSubmitter
from .config import OracleConfig
from .event_processor import EventProcessor
from .utils.contract_utility import ContractUtility
from .utils.polling_event_listener import PollingEventListener
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

            if not config.local_mode:
                # Initialize ROFL utility
                logger.debug("Initializing ROFL utility...")
                self.rofl_utility = RoflUtility()
                
                # Generate/fetch oracle signing key
                logger.info("Generating oracle signing key from ROFL...")
                self.secret = await self.rofl_utility.fetch_key("rofl-oracle-signer")
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
                config.target_chain.rpc_url, self.secret
            )
            logger.debug("Contract utility initialized with signing capability")

            # Connect to source chain for block fetching
            logger.debug(
                f"Connecting to source chain at {config.source_chain.rpc_url}"
            )
            self.source_w3 = Web3(
                Web3.HTTPProvider(
                    config.source_chain.rpc_url,
                    request_kwargs={
                        "timeout": config.monitoring.request_timeout
                    },
                )
            )
            if not self.source_w3.is_connected():
                raise Exception(
                    f"Failed to connect to source chain at {config.source_chain.rpc_url}"
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
                contract_address=config.target_chain.contract_address,
                request_timeout=config.monitoring.request_timeout,
            )
            logger.debug("Block submitter initialized")
            
            # Register oracle address if in ROFL mode
            if not config.local_mode:
                oracle_address = self.contract_utility.w3.eth.default_account
                logger.info(f"Oracle address: {oracle_address}")
                
                # Check if oracle is already registered
                current_oracle = await self.block_submitter.get_registered_oracle()
                
                if current_oracle != oracle_address:
                    logger.info("Registering oracle address with ROFLAdapter...")
                    success = await self.block_submitter.register_oracle()
                    if success:
                        logger.info(f"Oracle address {oracle_address} registered successfully")
                    else:
                        raise Exception(f"Failed to register oracle address {oracle_address}")
                else:
                    logger.info(f"Oracle address {oracle_address} already registered")

            # Initialize event processor
            logger.debug("Initializing event processor...")
            self.event_processor = EventProcessor(
                source_chain_id=self.source_chain_id,
                dedupe_window=1000,  # Track last 1000 events
            )
            logger.debug("Event processor initialized")

            # Load BlockHeaderRequester ABI for event listening (only needed in event listener mode)
            if not config.source_chain.is_push_oracle:
                logger.debug("Loading BlockHeaderRequester ABI...")
                self.block_requester_abi = self.contract_utility.get_contract_abi(
                    "BlockHeaderRequester"
                )
                logger.debug("ABI loaded")
            else:
                self.block_requester_abi = None

            # Initialize polling event listener or push mode (based on config)
            if config.source_chain.is_push_oracle:
                logger.info("Push oracle mode - will push latest block headers")
                self.event_listener = None
            else:
                logger.debug("Initializing polling event listener...")
                self.event_listener = PollingEventListener(
                    rpc_url=config.source_chain.rpc_url,
                    contract_address=config.source_chain.contract_address,
                    event_name="BlockHeaderRequested",
                    abi=self.block_requester_abi,
                    lookback_blocks=config.monitoring.lookback_blocks,
                )
                logger.debug("Polling event listener initialized")

            logger.info(
                f"HeaderOracle initialized ({'LOCAL' if config.local_mode else 'ROFL'} mode, source chain: {chain_id})"
            )

        except Exception as e:
            logger.error(f"HeaderOracle initialization failed: {e}")
            logger.error(f"Exception type: {type(e).__name__}", exc_info=True)
            raise

    def fetch_block_by_number(self, block_number: int) -> BlockData | None:
        """
        Fetch a specific block by number from the source chain.

        :param block_number: The block number to fetch
        :return: Block data or None if fetch fails
        """
        try:
            block = self.source_w3.eth.get_block(block_number)
            return block
        except Exception as e:
            logger.error(f"Error fetching block {block_number}: {e}")
            return None

    async def process_block_header_event(self, event_data: Any) -> None:
        """
        Process a BlockHeaderRequested event using the EventProcessor.

        This method delegates event parsing, validation, and deduplication
        to the EventProcessor, then handles block fetching and submission
        for valid events.

        :param event_data: Event data from the event listener
        """
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
            block = self.fetch_block_by_number(event.block_number)

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
                    success = await self.block_submitter.submit_block_header(
                        event.block_number, block_hash_hex
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
        try:
            # Get the latest block from source chain
            latest_block_number = self.source_w3.eth.block_number
            last_stored_block = await self.block_submitter.get_latest_block_number()

            if last_stored_block == 0:
                next_block_to_push = latest_block_number
            else:
                next_block_to_push = last_stored_block + 1
            

            while(next_block_to_push < min(latest_block_number, last_stored_block + 20)):
                logger.info(f"Pushing latest block header: {next_block_to_push}")
                # Fetch the block at the current contract block number
                block = self.fetch_block_by_number(next_block_to_push)
                
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
                        success = await self.block_submitter.submit_block_header(
                            next_block_to_push, block_hash_hex
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
                    else:
                        logger.error(f"Block {next_block_to_push} has no hash")
                else:
                    logger.error(f"Could not fetch latest block {next_block_to_push}")

        except Exception as e:
            logger.error(
                f"Error pushing latest block header: {e}",
                exc_info=True,
            )

    async def shutdown(self) -> None:
        """Gracefully shutdown the oracle."""
        logger.info("Shutting down HeaderOracle...")
        if self.event_listener:
            await self.event_listener.stop()
        logger.info("HeaderOracle shutdown complete")

    async def run(self) -> None:
        """
        Main entry point for the HeaderOracle.
        Starts event polling or push mode based on configuration.
        """
        logger.info("Starting HeaderOracle...")
        
        if self.config.source_chain.is_push_oracle:
            logger.info("Running in push oracle mode - pushing latest block headers")
            await self._run_push_mode()
        else:
            logger.info(
                f"Running in event listener mode - polling for BlockHeaderRequested events from {self.config.source_chain.contract_address}"
            )
            await self._run_event_listener_mode()

    async def _run_push_mode(self) -> None:
        """Run in push oracle mode - continuously push latest block headers."""
        try:
            logger.info(
                f"Starting push oracle with {self.config.monitoring.push_interval} second interval..."
            )

            # Main push loop
            while True:
                await self.push_latest_block_header()
                await sleep(self.config.monitoring.push_interval)

        except Exception as e:
            logger.error(f"Error in push oracle loop: {e}", exc_info=True)
        finally:
            logger.info("Push oracle stopped")

    async def _run_event_listener_mode(self) -> None:
        """Run in event listener mode - poll for BlockHeaderRequested events."""
        try:
            logger.info(
                f"Starting polling event listener with {self.config.monitoring.polling_interval} second interval..."
            )

            # Start event polling (this will run indefinitely)
            await self.event_listener.start_polling(
                callback=self.process_block_header_event,
                interval=self.config.monitoring.polling_interval,
            )

        except Exception as e:
            logger.error(f"Error in event listener loop: {e}", exc_info=True)
        finally:
            logger.info("Cleaning up...")
            if self.event_listener:
                await self.event_listener.stop()
            logger.info("HeaderOracle stopped")
