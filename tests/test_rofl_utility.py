#!/usr/bin/env python3
"""Tests for RoflUtility class.

This module tests the ROFL interaction utilities including
socket communication, CBOR decoding, and transaction submission.
"""

import unittest
from unittest.mock import AsyncMock, MagicMock, Mock, patch

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

    def test_decode_cbor_response_non_dict_wraps_in_data(self):
        """Test that non-dict CBOR results get wrapped in {"data": ...}."""
        # CBOR encoding of string "hello" (pre-computed, stable format)
        # 0x65 = text string of length 5, followed by "hello" bytes
        cbor_hello_hex = "6568656c6c6f"

        utility = RoflUtility()
        result = utility._decode_cbor_response(cbor_hello_hex)

        assert result == {"data": "hello"}

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
    async def test_submit_tx_payload_construction(
        self, mock_decode, mock_appd_post
    ):
        """Test payload construction: hex stripping, value→string, gas→int."""
        mock_appd_post.return_value = {"data": "unused"}
        mock_decode.return_value = {"ok": True}

        utility = RoflUtility()
        tx: TxParams = {
            "gas": 150000,
            "to": "0xABCDEF1234567890ABCDEF1234567890ABCDEF12",
            "value": 1000000000000000000,  # 1 ETH in Wei
            "data": "0x12345678",
        }
        await utility.submit_tx(tx)

        payload = mock_appd_post.call_args[0][1]
        tx_data = payload["tx"]["data"]

        # gas converted to int
        assert tx_data["gas_limit"] == 150000
        assert isinstance(tx_data["gas_limit"], int)

        # value converted to string (for large Wei values)
        assert tx_data["value"] == "1000000000000000000"
        assert isinstance(tx_data["value"], str)

        # 0x prefix stripped, lowercase preserved
        assert tx_data["to"] == "ABCDEF1234567890ABCDEF1234567890ABCDEF12"
        assert tx_data["data"] == "12345678"

    @patch.object(RoflUtility, "_appd_post")
    @patch.object(RoflUtility, "_decode_cbor_response")
    async def test_submit_tx_handles_bytes_input(
        self, mock_decode, mock_appd_post
    ):
        """Test payload handles bytes input for to/data fields."""
        mock_appd_post.return_value = {"data": "unused"}
        mock_decode.return_value = {"ok": True}

        utility = RoflUtility()
        tx: TxParams = {
            "gas": 100000,
            "to": bytes.fromhex("1234567890123456789012345678901234567890"),
            "value": 0,
            "data": bytes.fromhex("abcdef"),
        }
        await utility.submit_tx(tx)

        payload = mock_appd_post.call_args[0][1]
        tx_data = payload["tx"]["data"]

        assert tx_data["to"] == "1234567890123456789012345678901234567890"
        assert tx_data["data"] == "abcdef"

    @patch.object(RoflUtility, "_appd_post")
    @patch.object(RoflUtility, "_decode_cbor_response")
    async def test_submit_tx_ok_returns_true(self, mock_decode, mock_appd_post):
        """Test that ok response returns True."""
        mock_appd_post.return_value = {"data": "unused"}
        mock_decode.return_value = {"ok": "tx_hash"}

        utility = RoflUtility()
        result = await utility.submit_tx(self.test_tx)
        assert result is True

    @patch.object(RoflUtility, "_appd_post")
    @patch.object(RoflUtility, "_decode_cbor_response")
    async def test_submit_tx_fail_raises_with_message(
        self, mock_decode, mock_appd_post
    ):
        """Test that fail response raises exception with message field."""
        mock_appd_post.return_value = {"data": "unused"}
        mock_decode.return_value = {"fail": {"message": "out of gas"}}

        utility = RoflUtility()
        with pytest.raises(Exception, match="out of gas"):
            await utility.submit_tx(self.test_tx)

    @patch.object(RoflUtility, "_appd_post")
    @patch.object(RoflUtility, "_decode_cbor_response")
    async def test_submit_tx_fail_without_message_uses_str(
        self, mock_decode, mock_appd_post
    ):
        """Test that fail response without message field stringifies the dict."""
        mock_appd_post.return_value = {"data": "unused"}
        mock_decode.return_value = {"fail": {"code": 42}}

        utility = RoflUtility()
        with pytest.raises(Exception, match="code.*42"):
            await utility.submit_tx(self.test_tx)

    @patch.object(RoflUtility, "_appd_post")
    @patch.object(RoflUtility, "_decode_cbor_response")
    async def test_submit_tx_error_raises(self, mock_decode, mock_appd_post):
        """Test that error response raises exception."""
        mock_appd_post.return_value = {"data": "unused"}
        mock_decode.return_value = {"error": "network timeout"}

        utility = RoflUtility()
        with pytest.raises(Exception, match="network timeout"):
            await utility.submit_tx(self.test_tx)

    @patch.object(RoflUtility, "_appd_post")
    @patch.object(RoflUtility, "_decode_cbor_response")
    async def test_submit_tx_unknown_format_raises(
        self, mock_decode, mock_appd_post
    ):
        """Test that unknown response format raises (fail-closed)."""
        mock_appd_post.return_value = {"data": "unused"}
        mock_decode.return_value = {"unexpected": "format"}

        utility = RoflUtility()
        with pytest.raises(Exception, match="Unknown ROFL response format"):
            await utility.submit_tx(self.test_tx)

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
