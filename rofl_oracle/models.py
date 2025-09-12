"""Data models for the ROFL Oracle system.

This module provides immutable data classes for representing blockchain events
and block headers used throughout the oracle system.
"""

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class BlockHeaderEvent:
    """Represents a BlockHeaderRequested event from the blockchain.

    This immutable data class captures all relevant information from a
    BlockHeaderRequested event, providing a type-safe representation for
    processing throughout the oracle system.

    Attributes:
        chain_id: The chain ID where the block header is requested from
        block_number: The specific block number being requested
        requester: Address that requested the block header
        context: Additional context data for the request
        event_block_number: Block number where the event was emitted
        transaction_hash: Hash of the transaction that emitted the event
        log_index: Index of the log entry in the block
    """

    chain_id: int
    block_number: int
    requester: str
    context: str
    event_block_number: int
    transaction_hash: str
    log_index: int

    def __str__(self) -> str:
        """Human-readable string representation."""
        return (
            f"BlockHeaderEvent(chain={self.chain_id}, "
            f"block={self.block_number}, "
            f"requester={self.requester[:8]}..., "
            f"event_block={self.event_block_number})"
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "chain_id": self.chain_id,
            "block_number": self.block_number,
            "requester": self.requester,
            "context": self.context,
            "event_block_number": self.event_block_number,
            "transaction_hash": self.transaction_hash,
            "log_index": self.log_index,
        }

    @property
    def unique_key(self) -> tuple[int, int, str, int]:
        """Generate a unique key for deduplication.

        Returns a tuple that uniquely identifies this event for
        deduplication purposes.
        """
        return (
            self.chain_id,
            self.block_number,
            self.transaction_hash,
            self.log_index,
        )


@dataclass(frozen=True, slots=True)
class BlockHeader:
    """Represents a block header from the blockchain.

    This immutable data class encapsulates block header information
    retrieved from the source chain for submission to the target chain.

    Attributes:
        chain_id: The chain ID this block belongs to
        block_number: The block number
        block_hash: The block hash (with 0x prefix)
        timestamp: Block timestamp (Unix timestamp)
        parent_hash: Parent block hash (with 0x prefix)
    """

    chain_id: int
    block_number: int
    block_hash: str
    timestamp: int
    parent_hash: str

    def __str__(self) -> str:
        """Human-readable string representation."""
        return (
            f"BlockHeader(chain={self.chain_id}, "
            f"number={self.block_number}, "
            f"hash={self.block_hash[:10]}...)"
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "chain_id": self.chain_id,
            "block_number": self.block_number,
            "block_hash": self.block_hash,
            "timestamp": self.timestamp,
            "parent_hash": self.parent_hash,
        }
