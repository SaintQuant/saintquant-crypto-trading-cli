"""
Tests for crypto_trading_cli.ft_api_client

- Retry logic: 3 retries on connection error, then raises RuntimeError
- 401 response triggers re-login before retrying
- Successful responses are parsed and returned correctly
- ping() returns False on connection error
"""

import time
from unittest.mock import MagicMock, call, patch

import httpx
import pytest

from crypto_trading_cli.ft_api_client import FtApiClient


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_client() -> FtApiClient:
    return FtApiClient(
        base_url="http://127.0.0.1:38291/api/v1",
        username="freqtrade",
        password="test_password",
    )


def _mock_response(status_code: int, json_data: dict | list) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data
    resp.raise_for_status = MagicMock()
    if status_code >= 400:
        resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            f"HTTP {status_code}", request=MagicMock(), response=resp
        )
    return resp


# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------


def test_login_stores_tokens() -> None:
    client = _make_client()
    login_resp = _mock_response(200, {"access_token": "tok_abc", "refresh_token": "ref_xyz"})

    mock_http = MagicMock()
    mock_http.__enter__ = MagicMock(return_value=mock_http)
    mock_http.__exit__ = MagicMock(return_value=False)
    mock_http.post.return_value = login_resp

    with patch("crypto_trading_cli.ft_api_client.httpx.Client", return_value=mock_http):
        client._login()

    assert client._access_token == "tok_abc"
    assert client._refresh_token == "ref_xyz"


# ---------------------------------------------------------------------------
# Retry logic
# ---------------------------------------------------------------------------


def test_request_retries_on_connection_error() -> None:
    """3 retries on connection error → RuntimeError after all attempts."""
    client = _make_client()
    # Pre-set a token so _get_token() doesn't try to login
    client._access_token = "tok"
    client._token_expires_at = time.monotonic() + 900

    mock_http = MagicMock()
    mock_http.__enter__ = MagicMock(return_value=mock_http)
    mock_http.__exit__ = MagicMock(return_value=False)
    mock_http.request.side_effect = httpx.ConnectError("connection refused")

    with patch("crypto_trading_cli.ft_api_client.httpx.Client", return_value=mock_http):
        with patch("crypto_trading_cli.ft_api_client.time.sleep"):  # skip delays
            with pytest.raises(RuntimeError, match="failed after"):
                client._request("GET", "/profit")

    # 3 retry delays → 4 total attempts (initial + 3 retries)
    assert mock_http.request.call_count == 4


def test_request_succeeds_on_second_attempt() -> None:
    """Succeeds on the second attempt after one connection error."""
    client = _make_client()
    client._access_token = "tok"
    client._token_expires_at = time.monotonic() + 900

    profit_data = {"profit_all_percent": 5.0, "profit_closed_percent": 3.0, "trade_count": 10}
    success_resp = _mock_response(200, profit_data)

    mock_http = MagicMock()
    mock_http.__enter__ = MagicMock(return_value=mock_http)
    mock_http.__exit__ = MagicMock(return_value=False)
    mock_http.request.side_effect = [
        httpx.ConnectError("connection refused"),
        success_resp,
    ]

    with patch("crypto_trading_cli.ft_api_client.httpx.Client", return_value=mock_http):
        with patch("crypto_trading_cli.ft_api_client.time.sleep"):
            result = client._request("GET", "/profit")

    assert result == profit_data


# ---------------------------------------------------------------------------
# 401 triggers re-login
# ---------------------------------------------------------------------------


def test_401_triggers_relogin() -> None:
    """HTTP 401 response causes a re-login before the next attempt."""
    client = _make_client()
    client._access_token = "expired_tok"
    client._token_expires_at = time.monotonic() + 900

    resp_401 = _mock_response(401, {"detail": "Unauthorized"})
    resp_401.raise_for_status = MagicMock()  # don't raise on 401 — handled manually
    resp_401.status_code = 401

    profit_data = {"profit_all_percent": 2.0}
    resp_200 = _mock_response(200, profit_data)

    login_resp = _mock_response(200, {"access_token": "new_tok", "refresh_token": "ref"})

    mock_http = MagicMock()
    mock_http.__enter__ = MagicMock(return_value=mock_http)
    mock_http.__exit__ = MagicMock(return_value=False)
    # First request returns 401, second (after re-login) returns 200
    mock_http.request.side_effect = [resp_401, resp_200]
    mock_http.post.return_value = login_resp

    with patch("crypto_trading_cli.ft_api_client.httpx.Client", return_value=mock_http):
        result = client._request("GET", "/profit")

    assert result == profit_data
    assert client._access_token == "new_tok"


# ---------------------------------------------------------------------------
# ping()
# ---------------------------------------------------------------------------


def test_ping_returns_true_on_200() -> None:
    client = _make_client()
    resp = _mock_response(200, {"status": "pong"})

    mock_http = MagicMock()
    mock_http.__enter__ = MagicMock(return_value=mock_http)
    mock_http.__exit__ = MagicMock(return_value=False)
    mock_http.get.return_value = resp

    with patch("crypto_trading_cli.ft_api_client.httpx.Client", return_value=mock_http):
        assert client.ping() is True


def test_ping_returns_false_on_connection_error() -> None:
    client = _make_client()

    mock_http = MagicMock()
    mock_http.__enter__ = MagicMock(return_value=mock_http)
    mock_http.__exit__ = MagicMock(return_value=False)
    mock_http.get.side_effect = httpx.ConnectError("refused")

    with patch("crypto_trading_cli.ft_api_client.httpx.Client", return_value=mock_http):
        assert client.ping() is False


def test_ping_returns_false_on_non_200() -> None:
    client = _make_client()
    resp = _mock_response(503, {})
    resp.raise_for_status = MagicMock()

    mock_http = MagicMock()
    mock_http.__enter__ = MagicMock(return_value=mock_http)
    mock_http.__exit__ = MagicMock(return_value=False)
    mock_http.get.return_value = resp

    with patch("crypto_trading_cli.ft_api_client.httpx.Client", return_value=mock_http):
        assert client.ping() is False


# ---------------------------------------------------------------------------
# Public API methods
# ---------------------------------------------------------------------------


def test_get_profit_returns_data() -> None:
    client = _make_client()
    client._access_token = "tok"
    client._token_expires_at = time.monotonic() + 900

    data = {"profit_all_percent": 10.5, "profit_closed_percent": 8.0, "trade_count": 25}
    resp = _mock_response(200, data)

    mock_http = MagicMock()
    mock_http.__enter__ = MagicMock(return_value=mock_http)
    mock_http.__exit__ = MagicMock(return_value=False)
    mock_http.request.return_value = resp

    with patch("crypto_trading_cli.ft_api_client.httpx.Client", return_value=mock_http):
        result = client.get_profit()

    assert result == data


def test_force_exit_sends_correct_payload() -> None:
    client = _make_client()
    client._access_token = "tok"
    client._token_expires_at = time.monotonic() + 900

    resp = _mock_response(200, {"result": "Created sell order for trade 42"})

    mock_http = MagicMock()
    mock_http.__enter__ = MagicMock(return_value=mock_http)
    mock_http.__exit__ = MagicMock(return_value=False)
    mock_http.request.return_value = resp

    with patch("crypto_trading_cli.ft_api_client.httpx.Client", return_value=mock_http):
        client.force_exit(42, "market")

    call_kwargs = mock_http.request.call_args
    assert call_kwargs.kwargs["json"] == {"tradeid": "42", "ordertype": "market"}
