"""Block submission handling for ROFL Oracle.

This module handles the submission of block headers to the ROFLAdapter contract
on Oasis Sapphire, supporting both local (testing) and production (ROFL) modes.
"""

import asyncio
import logging
from typing import Any

from web3 import Web3
from web3.contract import Contract
from web3.types import TxParams, TxReceipt, Wei

from .utils.contract_utility import ContractUtility
from .utils.retry_utility import (
    CircuitBreaker,
    RetryConfig,
    retry_with_backoff,
)
from .utils.rofl_utility import RoflUtility

logger = logging.getLogger(__name__)

# Gas estimation constants for block header submissions
GAS_SINGLE_HEADER = 300_000  # Base gas for single header submission
GAS_BATCH_BASE = 300_000  # Base gas for batch submission
GAS_PER_HEADER = 50_000  # Additional gas per header in batch


class BlockSubmitter:
    """Handles block header submission to ROFLAdapter contract.

    Supports both local testing and production (ROFL) modes using the same
    ROFLAdapter contract interface. Both modes use storeBlockHeader (singular)
    and storeBlockheaders (plural) functions.
    """

    def __init__(
        self,
        contract_util: ContractUtility,
        rofl_util: RoflUtility | None,
        source_chain_id: int,
        contract_address: str,
        request_timeout: int = 30,
        circuit_breaker: CircuitBreaker | None = None,
        retry_config: RetryConfig | None = None,
        min_reporter_balance: float = 1,
    ) -> None:
        """
        Initialize the BlockSubmitter.

        Args:
            contract_util: Utility for contract interactions
            rofl_util: ROFL utility for transaction submission (None for local mode)
            source_chain_id: Chain ID of the source chain
            contract_address: Address of the ROFLAdapter/MockAdapter contract
            request_timeout: Timeout for transaction receipts in seconds (default: 30)
            circuit_breaker: Optional circuit breaker for resilience
            retry_config: Optional retry configuration
            min_reporter_balance: Minimum required balance in native tokens (default: 0.001)
        """
        self.contract_util: ContractUtility = contract_util
        self.rofl_util: RoflUtility | None = rofl_util
        self.source_chain_id: int = source_chain_id
        self.contract_address: str = Web3.to_checksum_address(contract_address)
        self.request_timeout: int = request_timeout
        self.circuit_breaker = circuit_breaker
        self.retry_config = retry_config or RetryConfig()
        self.min_reporter_balance = min_reporter_balance

        contract_name = "ROFLAdapter"
        self.adapter_abi: list[dict[str, Any]] = (
            self.contract_util.get_contract_abi("ROFLAdapter")
        )

        self.contract: Contract = self.contract_util.w3.eth.contract(
            address=self.contract_address, abi=self.adapter_abi
        )

        mode = "ROFL production" if rofl_util else "local testing"
        logger.info(f"BlockSubmitter initialized in {mode} mode")
        logger.info(f"  Source Chain ID: {source_chain_id}")
        logger.info(f"  Adapter Contract: {contract_name} at {contract_address}")

    def check_balance(self) -> tuple[int, bool]:
        """
        Check reporter balance and return (balance_wei, is_sufficient).

        Returns:
            Tuple of (balance in wei, whether balance meets minimum threshold)
        """
        address = self.contract_util.w3.eth.default_account
        balance = self.contract_util.w3.eth.get_balance(address)
        min_balance_wei = int(self.min_reporter_balance * 10**18)
        return balance, balance >= min_balance_wei

    async def _wait_for_balance(self) -> None:
        """
        Pause and wait until reporter has sufficient balance.
        Called when balance drops below minimum during operation.
        """
        check_interval = 30  # seconds
        address = self.contract_util.w3.eth.default_account
        min_balance_wei = int(self.min_reporter_balance * 10**18)

        while True:
            balance = self.contract_util.w3.eth.get_balance(address)
            balance_native = balance / 10**18

            if balance >= min_balance_wei:
                logger.info(
                    f"Reporter {address} balance restored: {balance_native:.6f} native tokens. Resuming..."
                )
                return

            logger.warning(
                f"⚠️  PAUSED - Insufficient balance!\n"
                f"    Reporter: {address}\n"
                f"    Current: {balance_native:.6f} native tokens\n"
                f"    Minimum: {self.min_reporter_balance:.6f} native tokens\n"
                f"    Waiting {check_interval}s before retry..."
            )
            await asyncio.sleep(check_interval)

    async def get_registered_reporter(self) -> str | None:
        """
        Get the registered reporter address for this chain from the ROFLAdapter contract.

        Returns:
            The registered reporter address for this chain, or None if not set
        """
        try:
            if not self.rofl_util:
                return None

            reporter_address = self.contract.functions.chainReporters(
                self.source_chain_id
            ).call()
            return (
                reporter_address
                if reporter_address
                != "0x0000000000000000000000000000000000000000"
                else None
            )
        except Exception as e:
            logger.error(
                f"Error getting reporter for chain {self.source_chain_id}: {e}"
            )
            return None

    async def register_reporter(self) -> None:
        """
        Register this chain's reporter address with the ROFLAdapter contract.
        Only needed in ROFL mode on first initialization.

        Raises:
            Exception: If registration fails
        """
        if not self.rofl_util:
            logger.debug("Reporter registration not needed in local mode")
            return

        reporter_address = self.contract_util.w3.eth.default_account
        logger.info(
            f"Registering reporter {reporter_address} for chain {self.source_chain_id}"
        )

        tx_params: TxParams = {
            "from": "0x0000000000000000000000000000000000000000",  # ROFL will override
            "gas": 200000,
            "gasPrice": self.contract_util.w3.eth.gas_price,
            "value": Wei(0),
        }

        tx_data: TxParams = self.contract.functions.setChainReporter(
            self.source_chain_id,
            reporter_address
        ).build_transaction(tx_params)

        logger.debug("Submitting chain reporter registration via ROFL...")

        await self.rofl_util.submit_tx(tx_data)
        logger.info(
            f"Reporter {reporter_address} registered for chain {self.source_chain_id}"
        )

    async def is_chain_supported(self) -> bool:
        """Check if the source chain is registered as supported."""
        try:
            reporter = self.contract.functions.chainReporters(
                self.source_chain_id
            ).call()
            return reporter != "0x0000000000000000000000000000000000000000"
        except Exception as e:
            logger.error(f"Error checking if chain {self.source_chain_id} is supported: {e}")
            return False

    async def get_latest_block_number(self) -> int | None:
        """
        Get the latest stored block number for the source chain from the contract.

        Returns:
            The latest stored block number, or None if not set or on error
        """
        try:
            latest_block_number = self.contract.functions.lastStoredBlock(
                self.source_chain_id
            ).call()
            return latest_block_number if latest_block_number != 0 else None
        except Exception as e:
            logger.error(f"Error getting latest block number: {e}")
            return None

    async def submit_block_headers_batch(
        self, block_numbers: list[int], block_hashes: list[str]
    ) -> bool:
        """
        Submit multiple block headers in a single transaction using storeBlockheaders.

        This is more efficient than submitting blocks one by one when you have
        multiple blocks to submit.

        Args:
            block_numbers: List of block numbers to submit (must be in ascending order)
            block_hashes: List of corresponding block hashes (with 0x prefix)

        Returns:
            True if submission was successful, False otherwise
        """
        if len(block_numbers) != len(block_hashes):
            logger.error(
                f"Block numbers and hashes length mismatch: {len(block_numbers)} vs {len(block_hashes)}"
            )
            return False

        if len(block_numbers) == 0:
            logger.warning("Empty batch submission requested")
            return True

        logger.info(
            f"Submitting batch of {len(block_numbers)} block headers: {block_numbers[0]} to {block_numbers[-1]}"
        )

        async def _submit() -> bool:
            try:
                mode_label = "ROFL" if self.rofl_util else "LOCAL"
                reporter = self.contract_util.w3.eth.default_account

                # Check balance before submission
                balance, is_sufficient = self.check_balance()
                if not is_sufficient:
                    logger.warning(
                        f"Low balance for reporter {reporter}: {balance / 10**18:.6f} native tokens. "
                        f"Minimum required: {self.min_reporter_balance}. Pausing..."
                    )
                    await self._wait_for_balance()

                logger.info(
                    f"{mode_label} MODE: Submitting {len(block_numbers)} blocks in batch (reporter: {reporter})"
                )

                batch_gas = GAS_BATCH_BASE + (GAS_PER_HEADER * len(block_numbers))
                tx_hash = self.contract.functions.storeBlockheaders(
                    self.source_chain_id, block_numbers, block_hashes
                ).transact(
                    {
                        "gas": batch_gas,
                        "gasPrice": self.contract_util.w3.eth.gas_price,
                    }
                )

                logger.info(
                    f"Batch transaction submitted successfully: {Web3.to_hex(tx_hash)}"
                )

                receipt: TxReceipt = (
                    self.contract_util.w3.eth.wait_for_transaction_receipt(
                        tx_hash, timeout=self.request_timeout
                    )
                )

                if (status := receipt.get("status", 0)) == 1:
                    logger.info(
                        f"Batch transaction confirmed in block {receipt['blockNumber']}"
                    )
                    return True
                else:
                    logger.error(f"Batch transaction failed with status={status}")
                    return False

            except Exception as tx_error:
                error_str = str(tx_error)
                if self.rofl_util and (
                    "ReadTimeout" in error_str or "timeout" in error_str.lower()
                ):
                    logger.warning(
                        "Batch transaction timed out - transaction likely succeeded (check explorer)"
                    )
                    return True
                else:
                    raise

        try:
            return await retry_with_backoff(
                _submit,
                config=self.retry_config,
                circuit_breaker=self.circuit_breaker,
                error_types=(Exception,),
            )
        except Exception as e:
            logger.error(
                f"Error submitting batch block headers after retries: {e}",
                exc_info=True,
            )
            return False

    async def submit_block_header(
        self, block_number: int, block_hash: str
    ) -> bool:
        """
        Submit a block header to the adapter contract with retry logic.

        This method handles both local mode (MockAdapter with setHashes) and
        production mode (ROFLAdapter with storeBlockHeader) based on whether
        rofl_util was provided.

        Args:
            block_number: The block number to submit
            block_hash: The block hash (with 0x prefix)

        Returns:
            True if submission was successful, False otherwise
        """
        logger.info(
            f"Submitting block header for block {block_number}, hash: {block_hash}"
        )

        async def _submit() -> bool:
            try:
                mode_label = "ROFL" if self.rofl_util else "LOCAL"
                reporter = self.contract_util.w3.eth.default_account

                # Check balance before submission
                balance, is_sufficient = self.check_balance()
                if not is_sufficient:
                    logger.warning(
                        f"Low balance for reporter {reporter}: {balance / 10**18:.6f} native tokens. "
                        f"Minimum required: {self.min_reporter_balance}. Pausing..."
                    )
                    await self._wait_for_balance()

                logger.info(f"{mode_label} MODE: Submitting single block header (reporter: {reporter})")

                tx_hash = self.contract.functions.storeBlockHeader(
                    self.source_chain_id, block_number, block_hash
                ).transact(
                    {
                        "gas": GAS_SINGLE_HEADER,
                        "gasPrice": self.contract_util.w3.eth.gas_price,
                    }
                )

                logger.info(
                    f"Transaction submitted successfully: {Web3.to_hex(tx_hash)}"
                )

                receipt: TxReceipt = (
                    self.contract_util.w3.eth.wait_for_transaction_receipt(
                        tx_hash, timeout=self.request_timeout
                    )
                )

                if (status := receipt.get("status", 0)) == 1:
                    logger.info(
                        f"Transaction confirmed in block {receipt['blockNumber']}"
                    )
                    return True
                else:
                    logger.error(f"Transaction failed with status={status}")
                    return False

            except Exception as tx_error:
                error_str = str(tx_error)
                if self.rofl_util and (
                    "ReadTimeout" in error_str or "timeout" in error_str.lower()
                ):
                    logger.warning(
                        f"Transaction submission timed out for block {block_number} - "
                        "transaction likely succeeded (check explorer). "
                        "This is common when confirmation is slow."
                    )
                    return True
                else:
                    raise

        try:
            return await retry_with_backoff(
                _submit,
                config=self.retry_config,
                circuit_breaker=self.circuit_breaker,
                error_types=(Exception,),
            )
        except Exception as e:
            logger.error(
                f"Error submitting block header after retries: {e}",
                exc_info=True,
            )
            return False
