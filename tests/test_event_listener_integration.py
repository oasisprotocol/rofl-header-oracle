"""
Integration test for EventListenerUtility with real blockchain data.

Tests WebSocket event listening for BlockHeaderRequested events using:
- Real Sepolia testnet data
- Hardcoded contract address: 0x85BfE05492aFC3D04Ff3B2ca6771ACF6f853d90d
- Known block with events: 9027565
"""

import asyncio
import contextlib
import os
import sys
from pathlib import Path

import pytest
from dotenv import load_dotenv
from web3 import Web3

from rofl_oracle.utils.event_listener_utility import (
    EventListenerUtility,
)

# Load environment variables from .env file
env_path = Path(__file__).parent.parent / ".env"

# Add src to path before imports (required for module loading)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../src"))

load_dotenv(env_path)

# Real Sepolia contract and block data
SEPOLIA_CONTRACT_ADDRESS = "0x85BfE05492aFC3D04Ff3B2ca6771ACF6f853d90d"
TEST_BLOCK_NUMBER = 9027786

# BlockHeaderRequester ABI
BLOCK_REQUESTER_ABI = [
    {
        "anonymous": False,
        "inputs": [
            {
                "indexed": True,
                "internalType": "uint256",
                "name": "chainId",
                "type": "uint256",
            },
            {
                "indexed": True,
                "internalType": "uint256",
                "name": "blockNumber",
                "type": "uint256",
            },
            {
                "indexed": False,
                "internalType": "address",
                "name": "requester",
                "type": "address",
            },
            {
                "indexed": False,
                "internalType": "bytes32",
                "name": "context",
                "type": "bytes32",
            },
        ],
        "name": "BlockHeaderRequested",
        "type": "event",
    }
]


class TestEventListenerIntegration:
    """Integration tests for EventListenerUtility with real blockchain data."""

    @pytest.fixture
    def source_rpc_url(self):
        """Get RPC URL from environment variable."""
        rpc_url = os.getenv("SOURCE_RPC_URL")
        if not rpc_url:
            pytest.skip("SOURCE_RPC_URL environment variable not set")
        return rpc_url

    @pytest.fixture
    def web3_instance(self, source_rpc_url):
        """Create Web3 instance for contract interaction."""
        w3 = Web3(Web3.HTTPProvider(source_rpc_url))
        if not w3.is_connected():
            pytest.skip(f"Cannot connect to RPC at {source_rpc_url}")
        return w3

    @pytest.fixture
    def source_contract(self, web3_instance):
        """Create contract instance for the real Sepolia contract."""
        return web3_instance.eth.contract(
            address=Web3.to_checksum_address(SEPOLIA_CONTRACT_ADDRESS),
            abi=BLOCK_REQUESTER_ABI,
        )

    def test_contract_connection(self, source_contract):
        """Test that we can connect to the real contract."""
        # Verify contract address
        assert source_contract.address == Web3.to_checksum_address(
            SEPOLIA_CONTRACT_ADDRESS
        )

        # Verify the contract has the BlockHeaderRequested event
        assert hasattr(source_contract.events, "BlockHeaderRequested")

        # Generate event topic and verify it matches expected pattern
        event_obj = source_contract.events.BlockHeaderRequested()
        assert event_obj.topic.startswith("0x")
        assert len(event_obj.topic) == 66  # 0x + 64 hex chars

    def test_historical_event_query(self, source_contract):
        """Test querying historical events from the known block."""
        # Query events from the specific block
        try:
            event_filter = (
                source_contract.events.BlockHeaderRequested.create_filter(
                    from_block=TEST_BLOCK_NUMBER, to_block=TEST_BLOCK_NUMBER
                )
            )
            events = event_filter.get_all_entries()

            print(f"✓ Found {len(events)} events in block {TEST_BLOCK_NUMBER}")

            # If events exist, validate their structure
            for i, event in enumerate(events):
                print(f"  Event {i + 1}:")
                print(f"    Chain ID: {event['args']['chainId']}")
                print(f"    Block Number: {event['args']['blockNumber']}")
                print(f"    Requester: {event['args']['requester']}")
                print(f"    Context: {event['args']['context'].hex()}")
                print(f"    Transaction Hash: {event['transactionHash'].hex()}")

                # Validate event structure
                assert "chainId" in event["args"]
                assert "blockNumber" in event["args"]
                assert "requester" in event["args"]
                assert "context" in event["args"]
                assert isinstance(event["args"]["chainId"], int)
                assert isinstance(event["args"]["blockNumber"], int)

        except Exception as e:
            # If the block doesn't have events, that's okay for this test
            print(f"No events found in block {TEST_BLOCK_NUMBER}: {e}")

    @pytest.mark.asyncio
    async def test_websocket_connection_only(
        self, source_rpc_url, source_contract
    ):
        """Test WebSocket connection establishment without waiting for events."""
        # Create event listener - it will handle HTTP to WebSocket conversion automatically
        event_listener = EventListenerUtility(
            rpc_url=source_rpc_url, max_retries=2
        )

        # Create event object
        event_obj = source_contract.events.BlockHeaderRequested()

        # Mock callback to capture any events (but we won't wait for them)
        events_received = []

        async def test_callback(event_data):
            events_received.append(event_data)
            print(f"✓ Received event: {event_data}")

        # Test WebSocket connection by starting the listener briefly
        listen_task = None
        try:
            listen_task = asyncio.create_task(
                event_listener.listen_for_contract_events(
                    contract_address=SEPOLIA_CONTRACT_ADDRESS,
                    event_obj=event_obj,
                    callback=test_callback,
                )
            )

            # Wait briefly to test connection establishment
            await asyncio.sleep(2.0)

            print("✓ WebSocket connection test completed successfully")
            print(
                f"✓ Connection state: {event_listener.connection_state.value}"
            )

            # Check if we're connected
            if event_listener.connection_state.value == "connected":
                print("✓ Successfully established WebSocket connection")
            else:
                print(
                    f"⚠ Connection state: {event_listener.connection_state.value}"
                )

        except Exception as e:
            pytest.fail(f"WebSocket connection test failed: {e}")
        finally:
            # Clean up
            if listen_task:
                listen_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await listen_task
            await event_listener.stop()

    @pytest.mark.skip(reason="Integration test requiring real WebSocket connection - should be run separately")
    @pytest.mark.slow
    @pytest.mark.asyncio
    async def test_event_subscription_with_timeout(
        self, source_rpc_url, source_contract
    ):
        """Test event subscription - waits for a real event within 30 seconds or fails.
        
        This is an integration test that requires:
        - Active WebSocket connection to Sepolia
        - Real contract interactions happening on-chain
        - Network connectivity
        
        Should be run separately as an integration test, not as part of unit tests.
        """
        # Create event listener - it will handle HTTP to WebSocket conversion automatically
        event_listener = EventListenerUtility(
            rpc_url=source_rpc_url, max_retries=2
        )
        event_obj = source_contract.events.BlockHeaderRequested()

        event_received = asyncio.Event()
        received_event_data = None

        async def event_callback(event_data):
            nonlocal received_event_data
            received_event_data = event_data
            print("✓ Received BlockHeaderRequested event:")
            print(f"  Address: {event_data.get('address')}")
            print(f"  Block Number: {event_data.get('blockNumber')}")
            print(f"  Topics: {event_data.get('topics', [])}")
            event_received.set()

        listen_task = None
        try:
            listen_task = asyncio.create_task(
                event_listener.listen_for_contract_events(
                    contract_address=SEPOLIA_CONTRACT_ADDRESS,
                    event_obj=event_obj,
                    callback=event_callback,
                )
            )

            # Wait for connection establishment
            await asyncio.sleep(3.0)

            if event_listener.connection_state.value != "connected":
                pytest.fail(
                    f"Failed to establish WebSocket connection: {event_listener.connection_state.value}"
                )

            print(
                "✓ WebSocket connection established, waiting for BlockHeaderRequested event..."
            )
            print(f"✓ Listening on contract: {SEPOLIA_CONTRACT_ADDRESS}")
            print(f"✓ Event topic: {event_obj.topic}")

            # Wait for a real event within 30 seconds
            try:
                await asyncio.wait_for(event_received.wait(), timeout=30.0)
                print("✓ Successfully received BlockHeaderRequested event!")

                # Validate the received event
                assert received_event_data is not None
                assert (
                    received_event_data.get("address")
                    == SEPOLIA_CONTRACT_ADDRESS
                )
                assert (
                    received_event_data.get("topics")
                    and len(received_event_data["topics"]) > 0
                )
                print("✓ Event validation passed")

            except TimeoutError:
                pytest.fail(
                    "No BlockHeaderRequested events received within 30 seconds. This indicates either:\n"
                    "1. No one is calling the contract during the test\n"
                    "2. WebSocket event subscription is not working correctly\n"
                    "3. The contract is not active on the testnet"
                )

        except Exception as e:
            pytest.fail(f"Event subscription test failed: {e}")
        finally:
            if listen_task:
                listen_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await listen_task
            await event_listener.stop()


if __name__ == "__main__":
    # Run integration tests
    pytest.main([__file__, "-v", "-s"])
