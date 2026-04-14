"""
Tests for crypto_trading_cli.strategy

Property 10: Raw credentials never appear in log output
  - api_key and secret must not appear in any log record emitted during
    build_freqtrade_config()

Example-based tests:
  - build_freqtrade_config() returns correct structure for each strategy
  - strategy_path resolves to a real directory
  - Required top-level keys are present
"""

import logging
import os
import uuid

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from crypto_trading_cli.strategy import build_freqtrade_config, get_strategies_dir

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_GRID_PARAMS = {
    "pair": "BTC/USDT",
    "grid_count": 5,
    "grid_spacing": 1.0,
    "invest_amount": 100.0,
    "stop_loss": -0.05,
}

_RSI_PARAMS = {
    "timeframe": "5m",
    "rsi_buy": 30,
    "rsi_sell": 70,
    "stop_loss": -0.08,
}

_EMA_PARAMS = {
    "ema_short": 9,
    "ema_long": 21,
    "timeframe": "1h",
}


def _make_config(strategy: str, params: dict, **kwargs) -> dict:
    return build_freqtrade_config(
        bot_id=str(uuid.uuid4()),
        exchange="binance",
        strategy=strategy,
        params=params,
        api_key="test_api_key_abc123",
        secret="test_secret_xyz789",
        port=38291,
        ft_password="test_ft_password",
        **kwargs,
    )


# ---------------------------------------------------------------------------
# Structure tests
# ---------------------------------------------------------------------------


def test_grid_config_required_keys() -> None:
    cfg = _make_config("grid", _GRID_PARAMS)
    assert cfg["strategy"] == "GridStrategy"
    assert "strategy_path" in cfg
    assert cfg["exchange"]["name"] == "binance"
    assert cfg["api_server"]["listen_port"] == 38291
    assert cfg["dry_run"] is True  # default
    assert cfg["stoploss"] == -0.05
    assert cfg["strategy_params"] == _GRID_PARAMS


def test_rsi_config_required_keys() -> None:
    cfg = _make_config("rsi", _RSI_PARAMS)
    assert cfg["strategy"] == "RSIStrategy"
    assert cfg["timeframe"] == "5m"
    assert cfg["stoploss"] == -0.08


def test_ema_config_required_keys() -> None:
    cfg = _make_config("ema", _EMA_PARAMS)
    assert cfg["strategy"] == "EMAStrategy"
    assert cfg["timeframe"] == "1h"


def test_dry_run_false_includes_credentials() -> None:
    cfg = _make_config("grid", _GRID_PARAMS, dry_run=False)
    assert cfg["dry_run"] is False
    assert cfg["exchange"]["key"] == "test_api_key_abc123"
    assert cfg["exchange"]["secret"] == "test_secret_xyz789"


def test_dry_run_true_omits_credentials() -> None:
    cfg = _make_config("grid", _GRID_PARAMS, dry_run=True)
    assert cfg["exchange"]["key"] == ""
    assert cfg["exchange"]["secret"] == ""


def test_stop_loss_forced_negative() -> None:
    """Positive stop_loss input must be converted to negative."""
    cfg = build_freqtrade_config(
        bot_id=str(uuid.uuid4()),
        exchange="binance",
        strategy="grid",
        params={**_GRID_PARAMS, "stop_loss": 0.05},  # positive — should be negated
        api_key="k",
        secret="s",
        port=1234,
        ft_password="pw",
    )
    assert cfg["stoploss"] < 0


def test_api_server_fields() -> None:
    cfg = _make_config("grid", _GRID_PARAMS)
    api = cfg["api_server"]
    assert api["enabled"] is True
    assert api["listen_ip_address"] == "127.0.0.1"
    assert api["username"] == "freqtrade"
    assert api["password"] == "test_ft_password"
    assert len(api["jwt_secret_key"]) == 64  # 32 bytes hex


def test_user_data_dir_contains_bot_short_id() -> None:
    bot_id = str(uuid.uuid4())
    cfg = build_freqtrade_config(
        bot_id=bot_id,
        exchange="binance",
        strategy="grid",
        params=_GRID_PARAMS,
        api_key="k",
        secret="s",
        port=1234,
        ft_password="pw",
    )
    assert bot_id[:8] in cfg["user_data_dir"]


def test_okx_passphrase_in_exchange_config() -> None:
    cfg = build_freqtrade_config(
        bot_id=str(uuid.uuid4()),
        exchange="okx",
        strategy="grid",
        params=_GRID_PARAMS,
        api_key="k",
        secret="s",
        port=1234,
        ft_password="pw",
        passphrase="my_passphrase",
        dry_run=False,
    )
    assert cfg["exchange"]["ccxt_config"]["password"] == "my_passphrase"


def test_unknown_strategy_raises() -> None:
    with pytest.raises(ValueError, match="Unknown strategy"):
        _make_config("unknown_strategy", {})


# ---------------------------------------------------------------------------
# strategies_dir resolves to a real directory
# ---------------------------------------------------------------------------


def test_get_strategies_dir_exists() -> None:
    path = get_strategies_dir()
    assert os.path.isdir(path), f"strategies dir not found: {path}"


def test_strategy_files_present() -> None:
    path = get_strategies_dir()
    for fname in ("GridStrategy.py", "RSIStrategy.py", "EMAStrategy.py"):
        assert os.path.isfile(os.path.join(path, fname)), f"Missing: {fname}"


# ---------------------------------------------------------------------------
# Property 10: credentials must not appear in log output
# ---------------------------------------------------------------------------


class _LogCapture(logging.Handler):
    def __init__(self):
        super().__init__()
        self.records: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(self.format(record))


@given(
    api_key=st.text(min_size=8, max_size=64, alphabet="abcdefghijklmnopqrstuvwxyz0123456789"),
    secret=st.text(min_size=8, max_size=64, alphabet="abcdefghijklmnopqrstuvwxyz0123456789"),
)
@settings(max_examples=50)
def test_credentials_not_in_log_output(api_key: str, secret: str) -> None:
    """Property 10: plaintext credentials must not appear in any log record."""
    handler = _LogCapture()
    root_logger = logging.getLogger()
    root_logger.addHandler(handler)
    root_logger.setLevel(logging.DEBUG)

    try:
        build_freqtrade_config(
            bot_id=str(uuid.uuid4()),
            exchange="binance",
            strategy="grid",
            params=_GRID_PARAMS,
            api_key=api_key,
            secret=secret,
            port=12345,
            ft_password="pw",
            dry_run=False,
        )
    finally:
        root_logger.removeHandler(handler)

    all_log_output = "\n".join(handler.records)
    assert api_key not in all_log_output, "API key found in log output"
    assert secret not in all_log_output, "Secret found in log output"
