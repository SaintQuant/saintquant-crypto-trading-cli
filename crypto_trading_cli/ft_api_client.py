"""
Freqtrade REST API client.

Synchronous HTTP client using httpx. Handles JWT authentication with token
caching and automatic refresh, and retries failed requests with exponential
back-off.

Freqtrade API authentication flow:
  POST /api/v1/token/login  (HTTP Basic Auth)  → { access_token, refresh_token }
  GET  /api/v1/profit       (Bearer token)     → profit data
"""

import logging
import time
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# Retry delays in seconds (3 retries = 4 total attempts)
_RETRY_DELAYS = [1, 2, 4]

# Token lifetime: Freqtrade access tokens are valid for ~15 minutes.
# We refresh 1 minute early to avoid expiry mid-request.
_TOKEN_LIFETIME_SECS = 14 * 60


class FtApiClient:
    """
    Lightweight synchronous Freqtrade REST API client.

    Features:
      - JWT token caching with automatic refresh before expiry
      - Force re-login on HTTP 401
      - Exponential back-off retry (up to 3 retries)
      - ``ping()`` for liveness checks (no auth required)
    """

    def __init__(self, base_url: str, username: str, password: str, proxy_url: str = "") -> None:
        """
        Args:
            base_url:  Freqtrade API base URL, e.g. ``http://127.0.0.1:38291/api/v1``
            username:  Always ``"freqtrade"`` for Freqtrade's built-in API.
            password:  Per-bot random password set in the Freqtrade config.
            proxy_url: Optional proxy URL, e.g. ``http://127.0.0.1:7890``.
                       Empty string means no proxy.
        """
        self._base_url = base_url.rstrip("/")
        self._username = username
        self._password = password
        self._proxy_url = proxy_url or None
        self._access_token: str | None = None
        self._refresh_token: str | None = None
        self._token_expires_at: float = 0.0  # monotonic timestamp

    # ---------------------------------------------------------------------------
    # Authentication
    # ---------------------------------------------------------------------------

    def _make_client(self) -> httpx.Client:
        """Create an httpx client, routing through the proxy if configured.
        Local addresses (127.0.0.1, localhost) always bypass the proxy.
        """
        if self._proxy_url:
            return httpx.Client(
                timeout=15,
                proxy=self._proxy_url,
                mounts={
                    "http://127.0.0.1": None,
                    "http://localhost": None,
                },
            )
        return httpx.Client(timeout=15)

    def _login(self) -> None:
        """Obtain a fresh JWT pair via HTTP Basic Auth."""
        with self._make_client() as client:
            resp = client.post(
                f"{self._base_url}/token/login",
                auth=(self._username, self._password),
            )
            resp.raise_for_status()
            data = resp.json()
            self._access_token = data["access_token"]
            self._refresh_token = data.get("refresh_token")
            self._token_expires_at = time.monotonic() + _TOKEN_LIFETIME_SECS

    def _refresh(self) -> None:
        """Refresh the access token using the refresh token, or re-login."""
        if not self._refresh_token:
            self._login()
            return
        try:
            with self._make_client() as client:
                resp = client.post(
                    f"{self._base_url}/token/refresh",
                    headers={"Authorization": f"Bearer {self._refresh_token}"},
                )
                resp.raise_for_status()
                self._access_token = resp.json()["access_token"]
                self._token_expires_at = time.monotonic() + _TOKEN_LIFETIME_SECS
        except Exception:
            # Refresh failed — fall back to full re-login
            self._login()

    def _get_token(self) -> str:
        """Return a valid access token, refreshing if necessary."""
        if not self._access_token or time.monotonic() >= self._token_expires_at:
            self._login()
        return self._access_token  # type: ignore[return-value]

    # ---------------------------------------------------------------------------
    # Request with retry
    # ---------------------------------------------------------------------------

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        """
        Make an authenticated request with automatic retry.

        Retries up to 3 times with delays of 1s, 2s, 4s on connection errors
        or non-2xx responses. On HTTP 401, forces a re-login before retrying.

        Raises:
            RuntimeError: After all retries are exhausted.
        """
        last_exc: Exception | None = None

        for attempt, delay in enumerate(_RETRY_DELAYS + [None]):  # type: ignore[list-item]
            try:
                token = self._get_token()
                with self._make_client() as client:
                    resp = client.request(
                        method,
                        f"{self._base_url}{path}",
                        headers={"Authorization": f"Bearer {token}"},
                        **kwargs,
                    )

                    if resp.status_code == 401:
                        # Token rejected — force re-login and retry once
                        self._access_token = None
                        self._login()
                        token = self._access_token
                        resp = client.request(
                            method,
                            f"{self._base_url}{path}",
                            headers={"Authorization": f"Bearer {token}"},
                            **kwargs,
                        )

                    resp.raise_for_status()
                    return resp.json()

            except Exception as exc:
                last_exc = exc
                if delay is not None:
                    logger.debug(
                        "FtApiClient retry %d/%d after %ds: %s",
                        attempt + 1,
                        len(_RETRY_DELAYS),
                        delay,
                        exc,
                    )
                    time.sleep(delay)

        raise RuntimeError(
            f"Freqtrade API request failed after {len(_RETRY_DELAYS)} retries: {last_exc}"
        ) from last_exc

    # ---------------------------------------------------------------------------
    # Public API methods
    # ---------------------------------------------------------------------------

    def ping(self) -> bool:
        """
        Check if the Freqtrade API server is reachable (no auth required).

        Returns:
            True if the server responds with HTTP 200, False otherwise.
        """
        try:
            with self._make_client() as client:
                resp = client.get(f"{self._base_url}/ping", timeout=5)
                return resp.status_code == 200
        except Exception:
            return False

    def get_profit(self) -> dict[str, Any]:
        """
        Return the profit summary from ``GET /profit``.

        Relevant keys: ``profit_all_percent``, ``profit_closed_percent``,
        ``trade_count``.
        """
        return self._request("GET", "/profit")

    def get_status(self) -> list[dict[str, Any]]:
        """
        Return the list of open trades from ``GET /status``.

        Each item contains: ``trade_id``, ``pair``, ``open_rate``,
        ``current_rate``, ``profit_pct``, ``open_date``.
        """
        return self._request("GET", "/status")

    def get_health(self) -> dict[str, Any]:
        """
        Return health information from ``GET /health``.

        Relevant keys: ``last_process_ts``.
        """
        return self._request("GET", "/health")

    def force_exit(
        self,
        trade_id: int | str,
        order_type: str = "market",
    ) -> dict[str, Any]:
        """
        Force-exit a trade via ``POST /forceexit``.

        Args:
            trade_id:   The trade ID to exit (integer or string).
            order_type: Order type, default ``"market"``.
        """
        return self._request(
            "POST",
            "/forceexit",
            json={"tradeid": str(trade_id), "ordertype": order_type},
        )

    def start_trading(self) -> dict[str, Any]:
        """Resume trading via ``POST /start``."""
        return self._request("POST", "/start")

    def stop_trading(self) -> dict[str, Any]:
        """Pause new entries via ``POST /stopbuy``."""
        return self._request("POST", "/stopbuy")

    def get_balance(self) -> dict[str, Any]:
        """Return account balance via ``GET /balance``."""
        return self._request("GET", "/balance")
