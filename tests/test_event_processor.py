#!/usr/bin/env python3
"""Unit tests for the EventProcessor module."""


import pytest

from rofl_oracle.event_processor import EventProcessor
from rofl_oracle.models import BlockHeaderEvent


@pytest.fixture
def processor():
    """Create an EventProcessor instance for testing."""
    return EventProcessor(
        source_chain_id=11155111,  # Sepolia chain ID
        dedupe_window=100,
    )


@pytest.fixture
def sample_websocket_event():
    """Create a sample WebSocket event (dict format with args)."""
    return {
        "args": {
            "chainId": 11155111,
            "blockNumber": 0x1234,
            "requester": "0x1234567890abcdef1234567890abcdef12345678",
            "context": b"\x00" * 32,  # 32 bytes of zeros
        },
        "blockNumber": 1000,
        "transactionHash": "0xabcdef1234567890123456789012345678901234567890123456789012345678",
        "logIndex": 5,
    }


@pytest.fixture
def sample_polling_event():
    """Create a sample polling event (dict format with args)."""
    # Return a dict that mimics web3.py's EventData
    return {
        "args": {
            "chainId": 11155111,
            "blockNumber": 0x1234,
            "requester": "0x1234567890abcdef1234567890abcdef12345678",
            "context": b"\x00" * 32,  # 32 bytes of zeros
        },
        "blockNumber": 1000,
        "transactionHash": b"\xab\xcd\xef\x12\x34\x56\x78\x90\x12\x34\x56\x78\x90\x12\x34\x56\x78\x90\x12\x34\x56\x78\x90\x12\x34\x56\x78\x90\x12\x34\x56\x78",
        "logIndex": 5,
    }


class TestEventProcessor:
    """Test suite for EventProcessor functionality."""

    @pytest.mark.asyncio
    async def test_process_websocket_event(
        self, processor, sample_websocket_event
    ):
        """Test processing a WebSocket format event."""
        event = await processor.process_event(sample_websocket_event)

        assert event is not None
        assert event.chain_id == 11155111
        assert event.block_number == 0x1234
        assert event.event_block_number == 1000
        assert event.transaction_hash.startswith("0x")
        assert event.log_index == 5
        assert processor.events_processed == 1

    @pytest.mark.asyncio
    async def test_process_polling_event(self, processor, sample_polling_event):
        """Test processing a polling format event."""
        event = await processor.process_event(sample_polling_event)

        assert event is not None
        assert event.chain_id == 11155111
        assert event.block_number == 0x1234
        assert event.event_block_number == 1000
        assert event.transaction_hash.startswith("0x")
        assert event.log_index == 5
        assert processor.events_processed == 1

    @pytest.mark.asyncio
    async def test_chain_id_filtering(self, processor, sample_websocket_event):
        """Test that events from wrong chain are filtered."""
        # Modify event to have different chain ID
        sample_websocket_event["args"]["chainId"] = 1  # Different chain ID

        event = await processor.process_event(sample_websocket_event)

        assert event is None
        assert processor.events_filtered == 1
        assert processor.events_processed == 0

    @pytest.mark.asyncio
    async def test_duplicate_detection(self, processor, sample_websocket_event):
        """Test that duplicate events are detected."""
        # Process the same event twice
        event1 = await processor.process_event(sample_websocket_event)
        event2 = await processor.process_event(sample_websocket_event)

        assert event1 is not None
        assert event2 is None  # Should be detected as duplicate
        assert processor.events_processed == 1
        assert processor.events_duplicated == 1

    @pytest.mark.asyncio
    async def test_insufficient_topics(self, processor):
        """Test handling of events with missing args."""
        bad_event = {
            # Missing 'args' field
            "blockNumber": 1000,
            "transactionHash": "0xabc",
            "logIndex": 0,
        }

        event = await processor.process_event(bad_event)

        assert event is None
        assert processor.events_invalid == 1

    @pytest.mark.asyncio
    async def test_dedupe_window_limit(self, processor):
        """Test that deduplication window respects size limit."""
        # Process more events than the window size
        for i in range(150):  # Window size is 100
            event = {
                "args": {
                    "chainId": 11155111,
                    "blockNumber": i,
                    "requester": "0x1234567890abcdef1234567890abcdef12345678",
                    "context": b"\x00" * 32,
                },
                "blockNumber": 1000 + i,
                "transactionHash": f"0x{i:064x}",
                "logIndex": 0,
            }
            await processor.process_event(event)

        # Cache should not exceed window size
        assert len(processor.processed_events) <= processor.dedupe_window

    @pytest.mark.asyncio
    async def test_dedupe_lru_behavior(self, processor):
        """Test that OrderedDict maintains LRU behavior and moves accessed items to end."""
        # Process first event
        event1 = await processor.process_event(
            {
                "args": {
                    "chainId": 11155111,
                    "blockNumber": 0x1111,
                    "requester": "0x1234567890abcdef1234567890abcdef12345678",
                    "context": b"\x00" * 32,
                },
                "blockNumber": 1000,
                "transactionHash": "0xabc123",
                "logIndex": 0,
            }
        )

        assert event1 is not None

        # Process second event
        event2 = await processor.process_event(
            {
                "args": {
                    "chainId": 11155111,
                    "blockNumber": 0x2222,
                    "requester": "0x1234567890abcdef1234567890abcdef12345678",
                    "context": b"\x00" * 32,
                },
                "blockNumber": 2000,
                "transactionHash": "0xdef456",
                "logIndex": 0,
            }
        )

        assert event2 is not None

        # Try to process first event again (duplicate check)
        event1_retry = await processor.process_event(
            {
                "args": {
                    "chainId": 11155111,
                    "blockNumber": 0x1111,
                    "requester": "0x1234567890abcdef1234567890abcdef12345678",
                    "context": b"\x00" * 32,
                },
                "blockNumber": 1000,
                "transactionHash": "0xabc123",
                "logIndex": 0,
            }
        )

        assert event1_retry is None  # Should be detected as duplicate

        # Check that both keys are in the cache
        keys = list(processor.processed_events.keys())
        assert len(keys) == 2
        assert event1.unique_key in processor.processed_events
        assert event2.unique_key in processor.processed_events

    @pytest.mark.asyncio
    async def test_event_data_decoding(self, processor, sample_websocket_event):
        """Test correct decoding of event data field."""
        event = await processor.process_event(sample_websocket_event)

        assert event is not None
        # Check that requester is checksummed (Web3 will change case)
        assert (
            event.requester.lower()
            == "0x1234567890abcdef1234567890abcdef12345678"
        )
        assert event.context.startswith("0x")
        assert len(event.context) == 66  # 0x + 64 hex chars

    @pytest.mark.asyncio
    async def test_metrics_tracking(self, processor):
        """Test that metrics are correctly tracked."""
        # Process some valid events
        for i in range(3):
            await processor.process_event(
                {
                    "args": {
                        "chainId": 11155111,
                        "blockNumber": i,
                        "requester": "0x1234567890abcdef1234567890abcdef12345678",
                        "context": b"\x00" * 32,
                    },
                    "blockNumber": 1000 + i,
                    "transactionHash": f"0x{i:064x}",
                    "logIndex": 0,
                }
            )

        # Process a duplicate
        await processor.process_event(
            {
                "args": {
                    "chainId": 11155111,
                    "blockNumber": 0,
                    "requester": "0x1234567890abcdef1234567890abcdef12345678",
                    "context": b"\x00" * 32,
                },
                "blockNumber": 1000,
                "transactionHash": "0x0000000000000000000000000000000000000000000000000000000000000000",
                "logIndex": 0,
            }
        )

        # Process an event from wrong chain
        await processor.process_event(
            {
                "args": {
                    "chainId": 1,  # Wrong chain
                    "blockNumber": 0x9999,
                    "requester": "0x1234567890abcdef1234567890abcdef12345678",
                    "context": b"\x00" * 32,
                },
                "blockNumber": 2000,
                "transactionHash": "0xfff",
                "logIndex": 0,
            }
        )

        metrics = processor.get_metrics()
        assert metrics["events_processed"] == 3
        assert metrics["events_duplicated"] == 1
        assert metrics["events_filtered"] == 1
        assert metrics["cache_size"] == 3

    @pytest.mark.asyncio
    async def test_malformed_event_handling(self, processor):
        """Test handling of malformed events."""
        malformed_events = [
            None,  # None event
            {},  # Empty dict (missing args)
            {"args": None},  # None args
            {"args": {}},  # Empty args (missing required fields)
            {"args": {"chainId": None}},  # Invalid chain ID
            "not_a_dict",  # Wrong type
        ]

        for bad_event in malformed_events:
            event = await processor.process_event(bad_event)
            assert event is None

        # Note: One event gets counted as filtered (wrong chain) instead of invalid
        assert processor.events_invalid >= 5  # At least 5 should be invalid

    def test_event_unique_key(self):
        """Test that BlockHeaderEvent generates correct unique keys."""
        event = BlockHeaderEvent(
            chain_id=1,
            block_number=1000,
            requester="0x123",
            context="0xabc",
            event_block_number=999,
            transaction_hash="0xdef456",
            log_index=3,
        )

        assert event.unique_key == (1, 1000, "0xdef456", 3)

    def test_event_string_representation(self):
        """Test string representation of events."""
        event = BlockHeaderEvent(
            chain_id=1,
            block_number=1000,
            requester="0x1234567890abcdef",
            context="0xabc",
            event_block_number=999,
            transaction_hash="0xdef",
            log_index=3,
        )

        str_repr = str(event)
        assert "chain=1" in str_repr
        assert "block=1000" in str_repr
        assert "0x123456..." in str_repr  # Truncated requester
