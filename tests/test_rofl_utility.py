#!/usr/bin/env python3
"""Tests for RoflUtility class.

This module tests the ROFL interaction utilities including
socket communication, CBOR decoding, and transaction submission.
"""

import codecs
import unittest
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import cbor2
import httpx
import pytest
from web3.types import TxParams

from rofl_oracle.utils.rofl_utility import RoflUtility


class TestRoflUtility(unittest.IsolatedAsyncioTestCase):
    """Test cases for RoflUtility class."""

    def setUp(self):
        """Set up test fixtures."""
        self.rofl_utility = RoflUtility()
        self.test_tx: TxParams = {
            "gas": 100000,
            "to": "0x1234567890123456789012345678901234567890",
            "value": 0,
            "data": "0xabcdef",
        }

    async def test_init_default(self):
        """Test default initialization."""
        utility = RoflUtility()
        assert utility.url == ""

    async def test_init_with_url(self):
        """Test initialization with custom URL."""
        test_url = "http://localhost:8080"
        utility = RoflUtility(test_url)
        assert utility.url == test_url

    @patch("rofl_oracle.utils.rofl_utility.httpx.AsyncClient")
    async def test_appd_post_unix_socket(self, mock_client_class):
        """Test _appd_post using Unix domain socket (default)."""
        mock_client = AsyncMock()
        mock_response = MagicMock()
        mock_response.json = MagicMock(return_value={"result": "success"})
        mock_response.raise_for_status = MagicMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client_class.return_value.__aenter__.return_value = mock_client

        utility = RoflUtility()
        result = await utility._appd_post("/test/path", {"test": "data"})

        # Verify Unix socket transport was used
        mock_client_class.assert_called_once()
        transport_arg = mock_client_class.call_args[1]["transport"]
        assert isinstance(transport_arg, httpx.AsyncHTTPTransport)

        # Verify request was made correctly
        mock_client.post.assert_called_once_with(
            "http://localhost/test/path", json={"test": "data"}, timeout=60.0
        )
        assert result == {"result": "success"}

    @patch("rofl_oracle.utils.rofl_utility.httpx.AsyncClient")
    async def test_appd_post_http_url(self, mock_client_class):
        """Test _appd_post using HTTP URL."""
        mock_client = AsyncMock()
        mock_response = MagicMock()
        mock_response.json = MagicMock(return_value={"result": "success"})
        mock_response.raise_for_status = MagicMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client_class.return_value.__aenter__.return_value = mock_client

        utility = RoflUtility("http://test.server:8080")
        result = await utility._appd_post("/test/path", {"test": "data"})

        # Verify HTTP URL was used directly
        mock_client.post.assert_called_once_with(
            "http://test.server:8080/test/path",
            json={"test": "data"},
            timeout=60.0,
        )
        assert result == {"result": "success"}

    @patch("rofl_oracle.utils.rofl_utility.httpx.AsyncClient")
    async def test_appd_post_socket_path(self, mock_client_class):
        """Test _appd_post using custom socket path."""
        mock_client = AsyncMock()
        mock_response = MagicMock()
        mock_response.json = MagicMock(return_value={"result": "success"})
        mock_response.raise_for_status = MagicMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client_class.return_value.__aenter__.return_value = mock_client

        utility = RoflUtility("/custom/socket.sock")
        result = await utility._appd_post("/test/path", {"test": "data"})

        # Verify custom socket transport was used
        mock_client_class.assert_called_once()
        transport_arg = mock_client_class.call_args[1]["transport"]
        assert isinstance(transport_arg, httpx.AsyncHTTPTransport)

        assert result == {"result": "success"}

    @patch("rofl_oracle.utils.rofl_utility.httpx.AsyncClient")
    async def test_appd_post_error_handling(self, mock_client_class):
        """Test _appd_post error handling."""
        mock_client = AsyncMock()
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock(
            side_effect=httpx.HTTPStatusError(
                "Server error", request=Mock(), response=Mock()
            )
        )
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client_class.return_value.__aenter__.return_value = mock_client

        utility = RoflUtility()

        with pytest.raises(httpx.HTTPStatusError):
            await utility._appd_post("/test/path", {"test": "data"})

    @patch.object(RoflUtility, "_appd_post")
    async def test_fetch_key(self, mock_appd_post):
        """Test fetch_key method."""
        mock_appd_post.return_value = {"key": "test_key_value"}

        utility = RoflUtility()
        result = await utility.fetch_key("test_id")

        mock_appd_post.assert_called_once_with(
            "/rofl/v1/keys/generate", {"key_id": "test_id", "kind": "secp256k1"}
        )
        assert result == "test_key_value"

    def test_decode_cbor_response_success(self):
        """Test successful CBOR response decoding."""
        test_data = {"status": "ok", "value": 123}
        cbor_bytes = cbor2.dumps(test_data)
        hex_string = codecs.encode(cbor_bytes, "hex").decode()

        utility = RoflUtility()
        result = utility._decode_cbor_response(hex_string)

        assert result == test_data

    def test_decode_cbor_response_non_dict(self):
        """Test CBOR decoding with non-dict result."""
        test_data = "simple_string"
        cbor_bytes = cbor2.dumps(test_data)
        hex_string = codecs.encode(cbor_bytes, "hex").decode()

        utility = RoflUtility()
        result = utility._decode_cbor_response(hex_string)

        assert result == {"data": test_data}

    def test_decode_cbor_response_invalid_hex(self):
        """Test CBOR decoding with invalid hex string."""
        utility = RoflUtility()
        result = utility._decode_cbor_response("invalid_hex")

        assert "error" in result
        assert result["error"] == "decode_failed"
        assert result["raw"] == "invalid_hex"

    def test_decode_cbor_response_invalid_cbor(self):
        """Test CBOR decoding with invalid CBOR data."""
        # Use actually invalid hex that can't be CBOR decoded
        invalid_cbor = "zzzinvalidhex"

        utility = RoflUtility()
        result = utility._decode_cbor_response(invalid_cbor)

        assert "error" in result
        assert result["error"] == "decode_failed"
        assert result["raw"] == invalid_cbor

    @patch.object(RoflUtility, "_appd_post")
    @patch.object(RoflUtility, "_decode_cbor_response")
    async def test_submit_tx_success(self, mock_decode, mock_appd_post):
        """Test successful transaction submission."""
        mock_appd_post.return_value = {"data": "cbor_response_hex"}
        mock_decode.return_value = {"ok": True}

        utility = RoflUtility()
        result = await utility.submit_tx(self.test_tx)

        expected_payload = {
            "tx": {
                "kind": "eth",
                "data": {
                    "gas_limit": 100000,
                    "to": "1234567890123456789012345678901234567890",
                    "value": 0,
                    "data": "abcdef",
                },
            },
            "encrypt": False,
        }

        mock_appd_post.assert_called_once_with(
            "/rofl/v1/tx/sign-submit", expected_payload
        )
        mock_decode.assert_called_once_with("cbor_response_hex")
        assert result is True

    @patch.object(RoflUtility, "_appd_post")
    @patch.object(RoflUtility, "_decode_cbor_response")
    async def test_submit_tx_error_response(self, mock_decode, mock_appd_post):
        """Test transaction submission with error response."""
        mock_appd_post.return_value = {"data": "cbor_response_hex"}
        mock_decode.return_value = {"error": "Transaction failed"}

        utility = RoflUtility()

        with pytest.raises(
            Exception, match="ROFL transaction failed: Transaction failed"
        ):
            await utility.submit_tx(self.test_tx)

    @patch.object(RoflUtility, "_appd_post")
    @patch.object(RoflUtility, "_decode_cbor_response")
    async def test_submit_tx_unknown_response(
        self, mock_decode, mock_appd_post
    ):
        """Test transaction submission with unknown response format."""
        mock_appd_post.return_value = {"data": "cbor_response_hex"}
        mock_decode.return_value = {"unknown_field": "value"}

        utility = RoflUtility()
        result = await utility.submit_tx(self.test_tx)

        # Should assume success if no clear error
        assert result is True

    @patch.object(RoflUtility, "_appd_post")
    async def test_submit_tx_removes_0x_prefix(self, mock_appd_post):
        """Test that submit_tx removes 0x prefix from hex values."""
        mock_appd_post.return_value = {
            "data": "a163026b01f4"
        }  # CBOR for {"ok": True}

        utility = RoflUtility()
        await utility.submit_tx(self.test_tx)

        # Check that 0x was removed from 'to' and 'data' fields
        call_args = mock_appd_post.call_args[0][1]
        assert (
            call_args["tx"]["data"]["to"]
            == "1234567890123456789012345678901234567890"
        )
        assert call_args["tx"]["data"]["data"] == "abcdef"

    @patch("rofl_oracle.utils.rofl_utility.httpx.AsyncClient")
    async def test_timeout_configuration(self, mock_client_class):
        """Test that timeout is correctly set to 60 seconds."""
        mock_client = AsyncMock()
        mock_response = MagicMock()
        mock_response.json = MagicMock(return_value={"result": "success"})
        mock_response.raise_for_status = MagicMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client_class.return_value.__aenter__.return_value = mock_client

        utility = RoflUtility()
        await utility._appd_post("/test/path", {"test": "data"})

        # Verify timeout was set to 60 seconds
        mock_client.post.assert_called_once()
        assert mock_client.post.call_args[1]["timeout"] == 60.0


if __name__ == "__main__":
    unittest.main()
