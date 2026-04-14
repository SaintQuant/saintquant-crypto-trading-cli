"""
Exchange configuration helpers.

Provides per-exchange ccxt configuration dicts that are injected into the
Freqtrade config JSON. Handles sandbox/testnet URL overrides and OKX passphrase.
"""

from typing import Any

# Default ccxt timeout in milliseconds
_TIMEOUT_MS = 30_000

# Sandbox / testnet base URLs
_BYBIT_SANDBOX_URL = "https://api-testnet.bybit.com"
_COINBASE_SANDBOX_URL = "https://api-sandbox.coinbase.com"
# OKX sandbox uses the same host with a special request header (x-simulated-trading: 1)

# Supported exchange identifiers (must match Freqtrade / ccxt exchange names)
SUPPORTED_EXCHANGES: list[str] = [
    "binance",
    "okx",
    "kraken",
    "bybit",
    "coinbaseadvanced",
    "bitget",
]

# Human-readable display names for the interactive menu
EXCHANGE_DISPLAY_NAMES: dict[str, str] = {
    "binance": "Binance",
    "okx": "OKX",
    "kraken": "Kraken",
    "bybit": "Bybit",
    "coinbaseadvanced": "Coinbase Advanced",
    "bitget": "Bitget",
}

# Exchanges that require a passphrase in addition to API key + secret
EXCHANGES_REQUIRING_PASSPHRASE: set[str] = {"okx"}

# Base ccxt configuration per exchange
EXCHANGE_CONFIGS: dict[str, dict[str, Any]] = {
    "binance": {
        "name": "binance",
        "ccxt_config": {"timeout": _TIMEOUT_MS},
        "ccxt_async_config": {"timeout": _TIMEOUT_MS},
    },
    "okx": {
        "name": "okx",
        "ccxt_config": {"timeout": _TIMEOUT_MS},
        "ccxt_async_config": {"timeout": _TIMEOUT_MS},
    },
    "kraken": {
        "name": "kraken",
        "ccxt_config": {"timeout": _TIMEOUT_MS, "enableRateLimit": True},
        "ccxt_async_config": {
            "timeout": _TIMEOUT_MS,
            "enableRateLimit": True,
            "rateLimit": 3100,
        },
    },
    "bybit": {
        "name": "bybit",
        "trading_mode": "spot",
        "margin_mode": "isolated",
        "ccxt_config": {"timeout": _TIMEOUT_MS},
        "ccxt_async_config": {"timeout": _TIMEOUT_MS},
    },
    "coinbaseadvanced": {
        "name": "coinbaseadvanced",
        "ccxt_config": {"timeout": _TIMEOUT_MS},
        "ccxt_async_config": {"timeout": _TIMEOUT_MS},
    },
    "bitget": {
        "name": "bitget",
        "trading_mode": "spot",
        "margin_mode": "isolated",
        "ccxt_config": {"timeout": _TIMEOUT_MS},
        "ccxt_async_config": {"timeout": _TIMEOUT_MS},
    },
}


def get_exchange_config(
    exchange: str,
    sandbox: bool = False,
    passphrase: str | None = None,
    proxy_url: str = "",
) -> dict[str, Any]:
    """
    Return the ccxt exchange configuration dict for *exchange*.

    Args:
        exchange:   Exchange identifier (must be in SUPPORTED_EXCHANGES).
        sandbox:    If True, apply testnet/sandbox URL overrides.
        passphrase: OKX passphrase (ignored for other exchanges).
        proxy_url:  Optional HTTP/HTTPS/SOCKS5 proxy URL.  When set, the proxy
                    is injected into both ``ccxt_config`` and
                    ``ccxt_async_config`` so Freqtrade routes all exchange
                    traffic through it.

    Returns:
        A deep-copied configuration dict ready to be embedded in the
        Freqtrade config JSON under the ``exchange`` key.

    Raises:
        ValueError: If *exchange* is not in SUPPORTED_EXCHANGES.
    """
    if exchange not in EXCHANGE_CONFIGS:
        raise ValueError(
            f"Unsupported exchange: '{exchange}'. "
            f"Supported: {', '.join(SUPPORTED_EXCHANGES)}"
        )

    cfg: dict[str, Any] = {
        k: (v.copy() if isinstance(v, dict) else v)
        for k, v in EXCHANGE_CONFIGS[exchange].items()
    }
    cfg["ccxt_config"] = cfg.get("ccxt_config", {}).copy()
    cfg["ccxt_async_config"] = cfg.get("ccxt_async_config", {}).copy()

    # OKX passphrase
    if exchange == "okx" and passphrase:
        cfg["ccxt_config"]["password"] = passphrase
        cfg["ccxt_async_config"]["password"] = passphrase

    # Proxy — injected as ccxt proxies dict and aiohttp_proxy
    if proxy_url:
        proxy_dict = {"http": proxy_url, "https": proxy_url}
        cfg["ccxt_config"]["proxies"] = proxy_dict
        cfg["ccxt_async_config"]["proxies"] = proxy_dict
        cfg["ccxt_async_config"]["aiohttp_proxy"] = proxy_url

    # Sandbox / testnet overrides
    if sandbox:
        if exchange == "okx":
            cfg["ccxt_config"].setdefault("headers", {})["x-simulated-trading"] = "1"
            cfg["ccxt_async_config"].setdefault("headers", {})["x-simulated-trading"] = "1"
        elif exchange == "bybit":
            urls = {"api": {"public": _BYBIT_SANDBOX_URL, "private": _BYBIT_SANDBOX_URL}}
            cfg["ccxt_config"]["urls"] = urls
            cfg["ccxt_async_config"]["urls"] = urls
        elif exchange == "coinbaseadvanced":
            cfg["ccxt_config"]["urls"] = {"api": _COINBASE_SANDBOX_URL}
            cfg["ccxt_async_config"]["urls"] = {"api": _COINBASE_SANDBOX_URL}

    return cfg
