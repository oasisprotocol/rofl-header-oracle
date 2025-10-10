#!/usr/bin/env python3
"""Tests for ContractUtility class.

This module tests both full mode (with signing) and read-only mode
of the ContractUtility class.
"""

import json
import unittest
from unittest.mock import MagicMock, Mock, patch

import pytest
from eth_account import Account

from rofl_oracle.utils.contract_utility import ContractUtility


class TestContractUtility(unittest.TestCase):
    """Test cases for ContractUtility class."""

    def setUp(self):
        """Set up test fixtures."""
        self.test_rpc_url = "https://test.rpc.url"
        self.test_private_key = "0x" + "1" * 64  # Valid test private key
        self.test_address = Account.from_key(self.test_private_key).address

    @patch("rofl_oracle.utils.contract_utility.Web3")
    def test_init_read_only_mode(self, mock_web3):
        """Test initialization in read-only mode (no private key)."""
        mock_w3_instance = MagicMock()
        mock_web3.return_value = mock_w3_instance
        mock_web3.HTTPProvider = Mock(return_value="mock_provider")

        utility = ContractUtility(self.test_rpc_url)

        mock_web3.assert_called_once_with(
            mock_web3.HTTPProvider(self.test_rpc_url)
        )
        assert utility.rpc_url == self.test_rpc_url
        assert utility.w3 == mock_w3_instance
        # Middleware should not be added in read-only mode
        mock_w3_instance.middleware_onion.add.assert_not_called()

    @patch("rofl_oracle.utils.contract_utility.Web3")
    @patch("rofl_oracle.utils.contract_utility.SignAndSendRawMiddlewareBuilder")
    @patch("rofl_oracle.utils.contract_utility.Account")
    def test_init_full_mode(
        self, mock_account, mock_middleware_builder, mock_web3
    ):
        """Test initialization in full mode (with private key)."""
        mock_w3_instance = MagicMock()
        mock_web3.return_value = mock_w3_instance
        mock_web3.HTTPProvider = Mock(return_value="mock_provider")

        mock_account_instance = MagicMock()
        mock_account_instance.address = self.test_address
        mock_account.from_key.return_value = mock_account_instance

        mock_middleware = MagicMock()
        mock_middleware_builder.build.return_value = mock_middleware

        ContractUtility(self.test_rpc_url, self.test_private_key)

        mock_web3.assert_called_once_with(
            mock_web3.HTTPProvider(self.test_rpc_url)
        )
        mock_account.from_key.assert_called_once_with(self.test_private_key)
        mock_middleware_builder.build.assert_called_once_with(
            mock_account_instance
        )
        mock_w3_instance.middleware_onion.add.assert_called_once_with(
            mock_middleware
        )
        assert mock_w3_instance.eth.default_account == self.test_address

    def test_init_no_rpc_url(self):
        """Test initialization fails without RPC URL."""
        with pytest.raises(ValueError, match="RPC URL is required"):
            ContractUtility("")

        with pytest.raises(ValueError, match="RPC URL is required"):
            ContractUtility(None)

    @patch("rofl_oracle.utils.contract_utility.Web3")
    @patch("rofl_oracle.utils.contract_utility.SignAndSendRawMiddlewareBuilder")
    @patch("rofl_oracle.utils.contract_utility.Account")
    def test_add_signing_middleware(
        self, mock_account, mock_middleware_builder, mock_web3
    ):
        """Test adding signing middleware to existing instance."""
        mock_w3_instance = MagicMock()
        mock_web3.return_value = mock_w3_instance
        mock_web3.HTTPProvider = Mock(return_value="mock_provider")

        # Create instance in read-only mode
        utility = ContractUtility(self.test_rpc_url)

        # Set up mocks for adding middleware
        mock_account_instance = MagicMock()
        mock_account_instance.address = self.test_address
        mock_account.from_key.return_value = mock_account_instance

        mock_middleware = MagicMock()
        mock_middleware_builder.build.return_value = mock_middleware

        # Add signing middleware
        utility._add_signing_middleware(self.test_private_key)

        mock_account.from_key.assert_called_once_with(self.test_private_key)
        mock_middleware_builder.build.assert_called_once_with(
            mock_account_instance
        )
        mock_w3_instance.middleware_onion.add.assert_called_once_with(
            mock_middleware
        )
        assert mock_w3_instance.eth.default_account == self.test_address

    @patch("rofl_oracle.utils.contract_utility.Web3")
    def test_add_signing_middleware_no_secret(self, mock_web3):
        """Test adding signing middleware fails without secret."""
        mock_w3_instance = MagicMock()
        mock_web3.return_value = mock_w3_instance
        mock_web3.HTTPProvider = Mock(return_value="mock_provider")

        utility = ContractUtility(self.test_rpc_url)

        with pytest.raises(
            ValueError, match="Private key is required for signing transactions"
        ):
            utility._add_signing_middleware("")

        with pytest.raises(
            ValueError, match="Private key is required for signing transactions"
        ):
            utility._add_signing_middleware(None)

    @patch("rofl_oracle.utils.contract_utility.Web3")
    @patch("pathlib.Path.open")
    def test_get_contract_abi_success(self, mock_path_open, mock_web3):
        """Test successful ABI loading from contract file."""
        mock_w3_instance = MagicMock()
        mock_web3.return_value = mock_w3_instance
        mock_web3.HTTPProvider = Mock(return_value="mock_provider")

        utility = ContractUtility(self.test_rpc_url)

        test_abi = [{"name": "test", "type": "function"}]
        test_contract_data = {"abi": test_abi}

        mock_path_open.return_value.__enter__ = Mock(
            return_value=Mock(
                read=Mock(return_value=json.dumps(test_contract_data))
            )
        )
        mock_path_open.return_value.__exit__ = Mock(return_value=None)

        abi = utility.get_contract_abi("TestContract")
        assert abi == test_abi

    @patch("rofl_oracle.utils.contract_utility.Web3")
    @patch("pathlib.Path.open")
    def test_get_contract_abi_file_not_found(self, mock_path_open, mock_web3):
        """Test ABI loading fails when contract file doesn't exist."""
        mock_w3_instance = MagicMock()
        mock_web3.return_value = mock_w3_instance
        mock_web3.HTTPProvider = Mock(return_value="mock_provider")

        utility = ContractUtility(self.test_rpc_url)

        mock_path_open.side_effect = FileNotFoundError()

        with pytest.raises(FileNotFoundError):
            utility.get_contract_abi("NonExistentContract")

    @patch("rofl_oracle.utils.contract_utility.Web3")
    @patch("pathlib.Path.open")
    def test_get_contract_abi_invalid_json(self, mock_path_open, mock_web3):
        """Test ABI loading fails with invalid JSON."""
        mock_w3_instance = MagicMock()
        mock_web3.return_value = mock_w3_instance
        mock_web3.HTTPProvider = Mock(return_value="mock_provider")

        utility = ContractUtility(self.test_rpc_url)

        mock_path_open.return_value.__enter__ = Mock(
            return_value=Mock(read=Mock(return_value="invalid json"))
        )
        mock_path_open.return_value.__exit__ = Mock(return_value=None)

        with pytest.raises(json.JSONDecodeError):
            utility.get_contract_abi("TestContract")

    @patch("rofl_oracle.utils.contract_utility.Web3")
    @patch("pathlib.Path.open")
    def test_get_contract_abi_path_resolution(self, mock_path_open, mock_web3):
        """Test contract ABI path resolution."""
        mock_w3_instance = MagicMock()
        mock_web3.return_value = mock_w3_instance
        mock_web3.HTTPProvider = Mock(return_value="mock_provider")

        utility = ContractUtility(self.test_rpc_url)

        test_abi = [{"name": "test", "type": "function"}]
        test_contract_data = {"abi": test_abi}

        mock_path_open.return_value.__enter__ = Mock(
            return_value=Mock(
                read=Mock(return_value=json.dumps(test_contract_data))
            )
        )
        mock_path_open.return_value.__exit__ = Mock(return_value=None)

        abi = utility.get_contract_abi("TestContract")

        # Verify the correct path was constructed
        assert abi == test_abi
        # Check that open was called (path resolution happens internally)
        mock_path_open.assert_called_once()


if __name__ == "__main__":
    unittest.main()
