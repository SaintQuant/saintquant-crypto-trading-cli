"""
Freqtrade configuration builder.

Ported from tradebot-service/app/services/strategy.py and adapted for the
single-user CLI context (no user_id, local user_data_dir under ~/.crypto-cli/).
"""

import importlib.resources as pkg_resources
import logging
import os
import secrets
from pathlib import Path
from typing import Any

from crypto_trading_cli.exchange import get_exchange_config

logger = logging.getLogger(__name__)

STRATEGY_CLASS_MAP: dict[str, str] = {
    "grid": "GridStrategy",
    "rsi": "RSIStrategy",
    "ema": "EMAStrategy",
}

EXCHANGE_STAKE_CURRENCY: dict[str, str] = {
    "binance": "USDT",
    "okx": "USDT",
    "kraken": "USDT",
    "bybit": "USDT",
    "coinbaseadvanced": "USD",
    "bitget": "USDT",
}


def get_strategies_dir() -> str:
    """Return the absolute path to the bundled strategies directory."""
    try:
        ref = pkg_resources.files("crypto_trading_cli.strategies")
        return str(ref)
    except Exception:
        return str(Path(__file__).parent / "strategies")


def _ensure_userdir(bot_id: str) -> str:
    """
    Create the Freqtrade user data directory and all required subdirectories.
    Uses the full bot_id to ensure each bot gets a completely isolated directory
    and a fresh SQLite database (avoids inheriting a paused state from a previous run).
    """
    userdir = str(Path.home() / ".crypto-cli" / f"ft_userdata_{bot_id}")
    for sub in ("", "data", "logs", "notebooks", "plot", "strategies", "hyperopts"):
        os.makedirs(os.path.join(userdir, sub), exist_ok=True)
    return userdir


def _build_minimal_roi(params: dict[str, Any]) -> dict[str, float]:
    """
    Build the minimal_roi dict for Freqtrade.

    Supports three forms:
      - ``minimal_roi`` dict in params, e.g. {"0": 0.05, "30": 0.02, "60": 0.01}
        (keys = minutes held, values = minimum profit ratio to exit)
      - ``take_profit`` float shortcut, e.g. 0.03 → {"0": 0.03}
      - Neither provided → {"0": 100} (effectively disables ROI; strategy signals control exits)
    """
    roi = params.get("minimal_roi")
    if roi and isinstance(roi, dict):
        return {str(k): float(v) for k, v in roi.items()}
    tp = params.get("take_profit")
    if tp is not None:
        return {"0": float(tp)}
    return {"0": 100}


def build_freqtrade_config(
    bot_id: str,
    exchange: str,
    strategy: str,
    params: dict[str, Any],
    api_key: str,
    secret: str,
    port: int,
    ft_password: str,
    dry_run: bool = True,
    sandbox: bool = False,
    passphrase: str | None = None,
    proxy_url: str = "",
) -> dict[str, Any]:
    """
    Assemble and return a complete Freqtrade config dict in memory.

    The dict is never written to a persistent file — it is only written to a
    temporary file immediately before spawning a Freqtrade subprocess, and that
    file is deleted as soon as the process reads it.

    Common params (all strategies):
    ─────────────────────────────────────────────────────────────────
    Trading pair & capital
      pair                    str    Trading pair, e.g. "BTC/USDT"
      invest_amount           float  Amount to invest per trade (USDT). Default 100.0
      max_open_trades         int    Max concurrent open trades. -1 = unlimited. Default 3
      tradable_balance_ratio  float  Fraction of balance available to trade (0–1). Default 0.99

    Order type
      order_type  str  "market" (default) — fill immediately at market price
                       "limit"            — place a limit order at a specific price

    Limit order pricing (only relevant when order_type="limit")
      entry_price_side    str    "other" (default) / "same" / "bid" / "ask"
      entry_price_offset  float  Price offset ratio, e.g. -0.001 = 0.1% below market
      exit_price_side     str    Same options as entry_price_side. Default "other"
      exit_price_offset   float  Same as entry_price_offset. Default 0
      use_order_book      bool   Use order book for pricing. Default False
      order_book_top      int    Order book depth level to use. Default 1

    Stop-loss
      stop_loss                       float  Stop-loss ratio, e.g. -0.05 = -5%. Default -0.10
      trailing_stop                   bool   Enable trailing stop-loss. Default False
      trailing_stop_positive          float  Trailing stop ratio once in profit, e.g. 0.02
      trailing_stop_positive_offset   float  Profit threshold to activate trailing stop, e.g. 0.01
      trailing_only_offset_is_reached bool   Only activate trailing stop after offset is reached
      stoploss_on_exchange            bool   Place stop-loss order on exchange. Default False

    Take-profit (ROI)
      take_profit  float  Quick take-profit ratio, e.g. 0.03 = exit at +3%
      minimal_roi  dict   Fine-grained ROI config, e.g. {"0": 0.05, "30": 0.02, "60": 0.01}
                          Keys = minutes held, values = minimum profit ratio to exit

    Candle timeframe
      timeframe  str  e.g. "1m" / "5m" / "15m" / "1h". Default "5m"

    Protection
      max_drawdown             float  Max drawdown protection, e.g. 0.15 = stop at -15%
      cooldown_lookback_period int    Candles to wait after a trade closes before re-entering
    ─────────────────────────────────────────────────────────────────
    """
    strategy_class = STRATEGY_CLASS_MAP.get(strategy.lower())
    if not strategy_class:
        raise ValueError(f"Unknown strategy: '{strategy}'. Supported: {list(STRATEGY_CLASS_MAP)}")

    exchange_cfg = get_exchange_config(
        exchange, sandbox=sandbox, passphrase=passphrase, proxy_url=proxy_url
    )
    exchange_cfg["key"] = "" if dry_run else api_key
    exchange_cfg["secret"] = "" if dry_run else secret

    stake_currency = EXCHANGE_STAKE_CURRENCY.get(exchange, "USDT")
    userdir = _ensure_userdir(bot_id)
    strategies_dir = get_strategies_dir()
    jwt_secret = secrets.token_hex(32)

    # ── Trading pair ──────────────────────────────────────────────────────────
    pair = params.get("pair", f"BTC/{stake_currency}")
    exchange_cfg["pair_whitelist"] = [pair]

    # ── Stop-loss ─────────────────────────────────────────────────────────────
    stoploss = float(params.get("stop_loss", -0.10))
    if stoploss > 0:
        stoploss = -stoploss

    # ── Order type ────────────────────────────────────────────────────────────
    order_type = params.get("order_type", "market")

    # ── Limit order pricing ───────────────────────────────────────────────────
    entry_price_side = params.get("entry_price_side", "other")
    exit_price_side = params.get("exit_price_side", "other")
    entry_price_offset = float(params.get("entry_price_offset", 0.0))
    exit_price_offset = float(params.get("exit_price_offset", 0.0))
    use_order_book = bool(params.get("use_order_book", False))
    order_book_top = int(params.get("order_book_top", 1))

    # ── Capital ───────────────────────────────────────────────────────────────
    invest_amount = params.get("invest_amount", 100.0)
    max_open_trades = int(params.get("max_open_trades", 3))
    tradable_balance_ratio = float(params.get("tradable_balance_ratio", 0.99))

    # dry_run_wallet: give enough balance for max_open_trades × invest_amount × 2
    if isinstance(invest_amount, (int, float)):
        dry_run_wallet = float(invest_amount) * max_open_trades * 2
    else:
        dry_run_wallet = 10000.0  # "unlimited" stake — give a large wallet

    # ── Trailing stop-loss ────────────────────────────────────────────────────
    trailing_stop = bool(params.get("trailing_stop", False))
    trailing_stop_positive = params.get("trailing_stop_positive")
    trailing_stop_positive_offset = params.get("trailing_stop_positive_offset", 0.0)
    trailing_only_offset_is_reached = bool(params.get("trailing_only_offset_is_reached", False))

    # ── Protections ───────────────────────────────────────────────────────────
    protections: list[dict] = []
    max_drawdown = params.get("max_drawdown")
    if max_drawdown:
        protections.append({
            "method": "MaxDrawdown",
            "lookback_period_candles": 48,
            "trade_limit": 1,
            "stop_duration_candles": 4,
            "max_allowed_drawdown": float(max_drawdown),
        })
    cooldown = int(params.get("cooldown_lookback_period", 0))
    if cooldown > 0:
        protections.append({
            "method": "CooldownPeriod",
            "stop_duration_candles": cooldown,
        })

    # ── Entry / exit pricing ──────────────────────────────────────────────────
    entry_pricing: dict[str, Any] = {
        "price_side": entry_price_side,
        "use_order_book": use_order_book,
        "order_book_top": order_book_top,
        "check_depth_of_market": {"enabled": False, "bids_to_ask_delta": 1},
    }
    if entry_price_offset != 0.0:
        entry_pricing["price_last_balance"] = entry_price_offset

    exit_pricing: dict[str, Any] = {
        "price_side": exit_price_side,
        "use_order_book": use_order_book,
        "order_book_top": order_book_top,
    }
    if exit_price_offset != 0.0:
        exit_pricing["price_last_balance"] = exit_price_offset

    # ── Full config ───────────────────────────────────────────────────────────
    config: dict[str, Any] = {
        "bot_name": f"bot_{bot_id[:8]}",
        "strategy": strategy_class,
        "strategy_path": strategies_dir,
        "strategy_params": params,
        "exchange": exchange_cfg,
        "api_server": {
            "enabled": True,
            "listen_ip_address": "127.0.0.1",
            "listen_port": port,
            "verbosity": "error",
            "enable_openapi": False,
            "username": "freqtrade",
            "password": ft_password,
            "jwt_secret_key": jwt_secret,
            "CORS_origins": [],
        },
        "initial_state": "running",
        "dry_run": dry_run,
        "dry_run_wallet": dry_run_wallet,
        "internals": {"process_throttle_secs": 5},
        "stake_currency": stake_currency,
        "stake_amount": invest_amount,
        "max_open_trades": max_open_trades,
        "timeframe": params.get("timeframe", "5m"),
        "stoploss": stoploss,
        "trailing_stop": trailing_stop,
        "trailing_only_offset_is_reached": trailing_only_offset_is_reached,
        "minimal_roi": _build_minimal_roi(params),
        "entry_pricing": entry_pricing,
        "exit_pricing": exit_pricing,
        "order_types": {
            "entry": order_type,
            "exit": order_type,
            "stoploss": "market",
            "stoploss_on_exchange": bool(params.get("stoploss_on_exchange", False)),
            "emergency_exit": "market",
        },
        "order_time_in_force": {
            "entry": "GTC",
            "exit": "GTC",
        },
        "pairlists": [{"method": "StaticPairList"}],
        "tradable_balance_ratio": tradable_balance_ratio,
        "last_stake_amount_min_ratio": 0.5,
        "user_data_dir": userdir,
        "dataformat_ohlcv": "json",
        "dataformat_trades": "jsongz",
        "db_url": f"sqlite:///{userdir}/tradesv3{'_dryrun' if dry_run else ''}.sqlite",
    }

    # Only add trailing stop positive params if set — Freqtrade rejects them when trailing_stop=False
    if trailing_stop and trailing_stop_positive is not None:
        config["trailing_stop_positive"] = float(trailing_stop_positive)
        config["trailing_stop_positive_offset"] = float(trailing_stop_positive_offset)

    if protections:
        config["protections"] = protections

    return config
