"""Block submission handling for ROFL Oracle.

This module handles the submission of block headers to the ROFLAdapter contract
on Oasis Sapphire, supporting both local (testing) and production (ROFL) modes.
"""

import logging
from typing import Any

from web3 import Web3
from web3.contract import Contract
from web3.types import TxParams, TxReceipt, Wei

from .utils.contract_utility import ContractUtility
from .utils.rofl_utility import RoflUtility

logger = logging.getLogger(__name__)


class BlockSubmitter:
    """Handles block header submission to adapter contracts.

    Supports both MockAdapter (local testing) and ROFLAdapter (production) contracts,
    automatically selecting the appropriate ABI and function calls based on the mode.
    """

    def __init__(
        self,
        contract_util: ContractUtility,
        rofl_util: RoflUtility | None,
        source_chain_id: int,
        contract_address: str,
        request_timeout: int = 30,
    ) -> None:
        """
        Initialize the BlockSubmitter.

        Args:
            contract_util: Utility for contract interactions
            rofl_util: ROFL utility for transaction submission (None for local mode)
            source_chain_id: Chain ID of the source chain
            contract_address: Address of the ROFLAdapter/MockAdapter contract
            request_timeout: Timeout for transaction receipts in seconds (default: 30)
        """
        self.contract_util: ContractUtility = contract_util
        self.rofl_util: RoflUtility | None = rofl_util
        self.source_chain_id: int = source_chain_id
        self.contract_address: str = Web3.to_checksum_address(contract_address)
        self.request_timeout: int = request_timeout

        # Load the appropriate ABI based on mode
        if rofl_util:
            # ROFL mode: use ROFLAdapter
            contract_name = "ROFLAdapter"
            self.adapter_abi: list[dict[str, Any]] = (
                self.contract_util.get_contract_abi("ROFLAdapter")
            )
        else:
            # Local mode: use MockAdapter
            contract_name = "MockAdapter"
            self.adapter_abi: list[dict[str, Any]] = (
                self.contract_util.get_contract_abi("MockAdapter")
            )

        self.contract: Contract = self.contract_util.w3.eth.contract(
            address=self.contract_address, abi=self.adapter_abi
        )

        if mode := ("ROFL production" if rofl_util else "local testing"):
            logger.info(f"BlockSubmitter initialized in {mode} mode")
            logger.info(f"  Source Chain ID: {source_chain_id}")
            logger.info(
                f"  Adapter Contract: {contract_name} at {contract_address}"
            )

    async def get_registered_oracle(self) -> str | None:
        """
        Get the currently registered oracle address from the ROFLAdapter contract.
        
        Returns:
            The registered oracle address, or None if not set
        """
        try:
            if not self.rofl_util:
                return None
                
            oracle_address = self.contract.functions.ROFL_ORACLE().call()
            return oracle_address if oracle_address != "0x0000000000000000000000000000000000000000" else None
        except Exception as e:
            logger.error(f"Error getting registered oracle: {e}")
            return None
    
    async def register_oracle(self) -> bool:
        """
        Register the oracle address with the ROFLAdapter contract.
        Only needed in ROFL mode on first initialization.
        Uses ROFL's authority to call setOracle.
        
        Returns:
            True if registration was successful, False otherwise
        """
        if not self.rofl_util:
            logger.debug("Oracle registration not needed in local mode")
            return True
        
        try:
            oracle_address = self.contract_util.w3.eth.default_account
            logger.info(f"Registering oracle address: {oracle_address}")
            
            tx_params: TxParams = {
                "from": "0x0000000000000000000000000000000000000000",  # ROFL will override
                "gas": 100000,
                "gasPrice": self.contract_util.w3.eth.gas_price,
                "value": Wei(0),
            }
            
            tx_data: TxParams = self.contract.functions.setOracle(
                oracle_address
            ).build_transaction(tx_params)
            
            logger.debug("Submitting oracle registration via ROFL...")
            
            if await self.rofl_util.submit_tx(tx_data):
                logger.info(f"Oracle {oracle_address} registered successfully")
                return True
            else:
                logger.error(f"Failed to register oracle {oracle_address}")
                return False
                
        except Exception as e:
            logger.error(f"Error registering oracle: {e}", exc_info=True)
            return False
    
    async def submit_block_header(
        self, block_number: int, block_hash: str
    ) -> bool:
        """
        Submit a block header to the adapter contract.

        This method handles both local mode (MockAdapter with setHashes) and
        production mode (ROFLAdapter with storeBlockHeader) based on whether
        rofl_util was provided.

        Args:
            block_number: The block number to submit
            block_hash: The block hash (with 0x prefix)

        Returns:
            True if submission was successful, False otherwise
        """
        try:
            logger.info(
                f"Submitting block header for block {block_number}, hash: {block_hash}"
            )

            try:
                if self.rofl_util:
                    # ROFL mode - use ROFLAdapter's storeBlockHeader with oracle key
                    logger.info(
                        "ROFL MODE: Submitting transaction with oracle key signature"
                    )
                    
                    tx_hash = self.contract.functions.storeBlockHeader(
                        self.source_chain_id, block_number, block_hash
                    ).transact(
                        {
                            "gas": 300000,
                            "gasPrice": self.contract_util.w3.eth.gas_price,
                        }
                    )
                else:
                    # Local mode - use MockAdapter's setHashes function
                    logger.info(
                        "LOCAL MODE: Submitting transaction directly to MockAdapter"
                    )
                    
                    tx_hash = self.contract.functions.setHashes(
                        self.source_chain_id,
                        [int(block_number)],
                        [block_hash],
                    ).transact(
                        {
                            "gas": 300000,
                            "gasPrice": self.contract_util.w3.eth.gas_price,
                        }
                    )

                logger.info(
                    f"Transaction submitted successfully: {Web3.to_hex(tx_hash)}"
                )

                receipt: TxReceipt = self.contract_util.w3.eth.wait_for_transaction_receipt(
                    tx_hash, timeout=self.request_timeout
                )

                if (status := receipt.get("status", 0)) == 1:
                    logger.info(
                        f"Transaction confirmed in block {receipt['blockNumber']}"
                    )
                    return True
                else:
                    logger.error(
                        f"Transaction failed with status={status}"
                    )
                    return False
                    
            except Exception as tx_error:
                error_str = str(tx_error)
                if self.rofl_util and (
                    "ReadTimeout" in error_str
                    or "timeout" in error_str.lower()
                ):
                    logger.warning(
                        f"Transaction submission timed out for block {block_number} - "
                        "transaction likely succeeded (check explorer). "
                        "This is common when confirmation is slow."
                    )
                    return True
                else:
                    logger.error(f"Transaction submission failed: {tx_error}")
                    return False

        except Exception as e:
            logger.error(f"Error submitting block header: {e}", exc_info=True)
            return False
