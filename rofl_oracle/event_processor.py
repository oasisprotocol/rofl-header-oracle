"""Event processing module for the ROFL Oracle.

This module handles the processing, validation, and deduplication of blockchain
events, specifically BlockHeaderRequested events from the source chain.
"""

import logging
from collections import OrderedDict
from collections.abc import Mapping
from typing import Any

from web3 import Web3
from web3.types import EventData

from .models import BlockHeaderEvent

logger = logging.getLogger(__name__)


class EventProcessor:
    """Processes and validates blockchain events for the oracle.

    This class is responsible for:
    - Parsing raw event data into structured BlockHeaderEvent objects
    - Validating event structure and data
    - Filtering events by chain ID
    - Preventing duplicate event processing
    - Maintaining metrics on processed events
    """

    def __init__(self, source_chain_id: int, dedupe_window: int = 1000) -> None:
        """Initialize the EventProcessor.

        Args:
            source_chain_id: The chain ID to filter events for
            dedupe_window: Maximum number of events to track for deduplication
        """
        self.source_chain_id = source_chain_id
        self.dedupe_window = dedupe_window

        # Deduplication cache using OrderedDict for O(1) lookups
        # Stores event unique keys as keys, None as values
        self.processed_events: OrderedDict[tuple[int, int, str, int], None] = (
            OrderedDict()
        )

        # Metrics tracking
        self.events_processed = 0
        self.events_filtered = 0
        self.events_duplicated = 0
        self.events_invalid = 0

        logger.info(
            f"EventProcessor initialized for chain {source_chain_id} "
            f"with dedupe window of {dedupe_window} events"
        )

    async def process_event(
        self, event_data: EventData
    ) -> BlockHeaderEvent | None:
        """Process an event into a validated BlockHeaderEvent.

        This method handles EventData from web3.py's contract.events.get_logs(),
        validates the event structure, filters by chain ID, and checks for duplicates.

        Args:
            event_data: Parsed event data from the event listener (EventData from web3.py)

        Returns:
            BlockHeaderEvent if valid and not duplicate, None otherwise
        """
        try:
            # Parse the raw event data
            parsed_event: BlockHeaderEvent | None = self._parse_event_data(
                event_data
            )
            if not parsed_event:
                return None

            # Filter by chain ID
            if not self._should_process_chain(parsed_event.chain_id):
                self.events_filtered += 1
                logger.debug(
                    f"Filtered event for chain {parsed_event.chain_id} "
                    f"(configured for chain {self.source_chain_id})"
                )
                return None

            # Check for duplicates
            if self._is_duplicate(parsed_event):
                self.events_duplicated += 1
                logger.debug(f"Duplicate event detected: {parsed_event}")
                return None

            # Mark as processed
            self._mark_processed(parsed_event)
            self.events_processed += 1

            logger.info(f"Processed event: {parsed_event}")
            return parsed_event

        except Exception as e:
            self.events_invalid += 1
            logger.error(f"Error processing event: {e}", exc_info=True)
            return None

    def _parse_event_data(
        self, event_data: EventData
    ) -> BlockHeaderEvent | None:
        """Parse event data into a BlockHeaderEvent.

        Args:
            event_data: Parsed event data

        Returns:
            Parsed BlockHeaderEvent or None if parsing fails
        """
        try:
            args: Mapping[str, Any] = event_data.get("args", {})
            if not args:
                logger.warning("Event missing 'args' field")
                logger.debug(
                    f"Event data keys: {list(event_data.keys()) if hasattr(event_data, 'keys') else 'No keys method'}"
                )
                logger.debug(f"Event data type: {type(event_data)}")
                self.events_invalid += 1
                return None

            chain_id: int = args.get("chainId", 0)
            requested_block: int = args.get(
                "blockNumber", 0
            )  # This is the requested block from the event
            requester: str = args.get("requester", "")
            context_raw: bytes | str = args.get("context", b"")

            context: str
            if isinstance(context_raw, bytes):
                context = f"0x{context_raw.hex()}"
            else:
                context = str(context_raw)

            if Web3.is_address(requester):
                requester = Web3.to_checksum_address(requester)

            event_block: int = event_data.get(
                "blockNumber", 0
            )  # Block where event was emitted
            tx_hash_raw: bytes | str = event_data.get("transactionHash", b"")
            log_index: int = event_data.get("logIndex", 0)

            tx_hash: str
            if isinstance(tx_hash_raw, bytes):
                tx_hash = f"0x{tx_hash_raw.hex()}"
            elif isinstance(tx_hash_raw, str):
                tx_hash = tx_hash_raw
            else:
                tx_hash = ""

            return BlockHeaderEvent(
                chain_id=chain_id,
                block_number=requested_block,
                requester=requester,
                context=context,
                event_block_number=event_block,
                transaction_hash=tx_hash,
                log_index=log_index,
            )

        except Exception as e:
            logger.error(f"Failed to parse event data: {e}")
            self.events_invalid += 1
            return None

    def _should_process_chain(self, chain_id: int) -> bool:
        """Check if an event's chain ID matches our configured chain.

        Args:
            chain_id: Chain ID from the event

        Returns:
            True if the event should be processed, False otherwise
        """
        if chain_id == self.source_chain_id:
            return True

        logger.warning(
            f"Skipping event for chain {chain_id} "
            f"(configured for chain {self.source_chain_id})"
        )
        return False

    def _is_duplicate(self, event: BlockHeaderEvent) -> bool:
        """Check if an event has already been processed.

        Args:
            event: The event to check

        Returns:
            True if duplicate, False otherwise
        """
        return event.unique_key in self.processed_events

    def _mark_processed(self, event: BlockHeaderEvent) -> None:
        """Mark an event as processed for deduplication.

        Uses OrderedDict with automatic eviction of oldest entries when
        the cache reaches the maximum size.

        Args:
            event: The event to mark as processed
        """
        event_key: tuple[int, int, str, int] = event.unique_key

        # Check if already exists - if so, move to end (most recent)
        if event_key in self.processed_events:
            self.processed_events.move_to_end(event_key)
        else:
            # Check if at capacity and evict oldest if needed using walrus
            if len(self.processed_events) >= self.dedupe_window:
                # Remove oldest (first) item - FIFO eviction
                self.processed_events.popitem(last=False)

            # Add new event key (becomes most recent)
            self.processed_events[event_key] = None

    def get_metrics(self) -> dict[str, int]:
        """Get current processing metrics.

        Returns:
            Dictionary of metric names to values
        """
        return {
            "events_processed": self.events_processed,
            "events_filtered": self.events_filtered,
            "events_duplicated": self.events_duplicated,
            "events_invalid": self.events_invalid,
            "cache_size": len(self.processed_events),
        }

    def log_metrics(self) -> None:
        """Log current processing metrics."""
        metrics = self.get_metrics()
        logger.info(
            f"EventProcessor Metrics: "
            f"Processed={metrics['events_processed']}, "
            f"Filtered={metrics['events_filtered']}, "
            f"Duplicates={metrics['events_duplicated']}, "
            f"Invalid={metrics['events_invalid']}, "
            f"Cache={metrics['cache_size']}/{self.dedupe_window}"
        )
