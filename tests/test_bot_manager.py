"""
Tests for crypto_trading_cli.bot_manager

- start/stop/restart/delete flows
- recover_on_startup() marks dead processes as error
- get_profit() and get_open_trades() raise RuntimeError when bot is not running
"""

import json
import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

import crypto_trading_cli.db as db_module
from crypto_trading_cli.bot_manager import BotManager, CreateBotParams
from crypto_trading_cli.db import BotRecord, init_db


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def tmp_db(tmp_path):
    """Fresh temporary database for each test."""
    db_path = str(tmp_path / "test_bots.db")
    init_db(db_path)
    return db_path


@pytest.fixture()
def manager():
    return BotManager(freqtrade_bin="freqtrade")


def _grid_params() -> CreateBotParams:
    return CreateBotParams(
        exchange="binance",
        strategy="grid",
        params={
            "pair": "BTC/USDT",
            "grid_count": 5,
            "grid_spacing": 1.0,
            "invest_amount": 100.0,
            "stop_loss": -0.05,
        },
        api_key="test_key",
        secret="test_secret",
        dry_run=True,
        sandbox=False,
    )


def _make_stopped_record(bot_id: str = None) -> BotRecord:
    bot_id = bot_id or str(uuid.uuid4())
    from crypto_trading_cli.crypto import encrypt
    return BotRecord(
        id=bot_id,
        exchange="binance",
        strategy="grid",
        status="stopped",
        config_json=json.dumps({
            "pair": "BTC/USDT", "grid_count": 5,
            "grid_spacing": 1.0, "invest_amount": 100.0, "stop_loss": -0.05,
        }),
        enc_api_key=encrypt("test_key"),
        enc_secret=encrypt("test_secret"),
        enc_ft_password=encrypt("ft_pw"),
        dry_run=True,
        sandbox=False,
        port=38291,
        created_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )


# ---------------------------------------------------------------------------
# start()
# ---------------------------------------------------------------------------


def test_start_creates_bot_record(tmp_db, manager) -> None:
    mock_process = MagicMock()
    mock_process.is_running.return_value = True
    mock_process.get_last_output_lines.return_value = []

    with patch("crypto_trading_cli.bot_manager.FreqtradeProcess", return_value=mock_process):
        with patch("crypto_trading_cli.bot_manager.FreqtradeProcess.alloc_port", return_value=38291):
            record = manager.start(_grid_params())

    assert record.status == "running"
    assert record.exchange == "binance"
    assert record.strategy == "grid"
    assert record.port == 38291


def test_start_raises_on_invalid_params(tmp_db, manager) -> None:
    bad_params = CreateBotParams(
        exchange="binance",
        strategy="grid",
        params={"pair": "BTC/USDT", "grid_count": -1, "grid_spacing": 1.0,
                "invest_amount": 100.0, "stop_loss": -0.05},
        api_key="k",
        secret="s",
    )
    with pytest.raises(ValueError, match="grid_count"):
        manager.start(bad_params)


def test_start_raises_when_max_bots_reached(tmp_db, manager) -> None:
    # Insert 10 running bots directly into DB
    from crypto_trading_cli.crypto import encrypt
    from crypto_trading_cli.db import insert_bot
    for _ in range(10):
        rec = _make_stopped_record()
        rec.status = "running"
        insert_bot(rec)

    with pytest.raises(RuntimeError, match="Maximum number"):
        manager.start(_grid_params())


def test_start_marks_error_on_process_failure(tmp_db, manager) -> None:
    mock_process = MagicMock()
    mock_process.start.side_effect = RuntimeError("Freqtrade crashed")
    mock_process.get_last_output_lines.return_value = ["error line"]

    with patch("crypto_trading_cli.bot_manager.FreqtradeProcess", return_value=mock_process):
        with patch("crypto_trading_cli.bot_manager.FreqtradeProcess.alloc_port", return_value=38291):
            with pytest.raises(RuntimeError, match="Freqtrade failed to start"):
                manager.start(_grid_params())

    # Bot record should exist with status 'error'
    from crypto_trading_cli.db import list_bots
    bots = list_bots()
    assert len(bots) == 1
    assert bots[0].status == "error"


# ---------------------------------------------------------------------------
# stop()
# ---------------------------------------------------------------------------


def test_stop_updates_status(tmp_db, manager) -> None:
    from crypto_trading_cli.db import insert_bot
    rec = _make_stopped_record()
    rec.status = "running"
    insert_bot(rec)

    mock_process = MagicMock()
    manager._instances[rec.id] = mock_process

    result = manager.stop(rec.id)
    assert result.status == "stopped"
    mock_process.stop.assert_called_once()
    assert rec.id not in manager._instances


def test_stop_raises_for_unknown_bot(tmp_db, manager) -> None:
    with pytest.raises(ValueError, match="Bot not found"):
        manager.stop("nonexistent-id")


# ---------------------------------------------------------------------------
# delete()
# ---------------------------------------------------------------------------


def test_delete_removes_bot_from_db(tmp_db, manager) -> None:
    from crypto_trading_cli.db import get_bot, insert_bot
    rec = _make_stopped_record()
    insert_bot(rec)

    manager.delete(rec.id)
    assert get_bot(rec.id) is None


def test_delete_stops_running_process(tmp_db, manager) -> None:
    from crypto_trading_cli.db import insert_bot
    rec = _make_stopped_record()
    rec.status = "running"
    insert_bot(rec)

    mock_process = MagicMock()
    manager._instances[rec.id] = mock_process

    manager.delete(rec.id)
    mock_process.stop.assert_called_once()


# ---------------------------------------------------------------------------
# get_profit() and get_open_trades() — bot not running
# ---------------------------------------------------------------------------


def test_get_profit_raises_when_not_running(tmp_db, manager) -> None:
    from crypto_trading_cli.db import insert_bot
    rec = _make_stopped_record()
    insert_bot(rec)

    with pytest.raises(RuntimeError, match="not running"):
        manager.get_profit(rec.id)


def test_get_open_trades_raises_when_not_running(tmp_db, manager) -> None:
    from crypto_trading_cli.db import insert_bot
    rec = _make_stopped_record()
    insert_bot(rec)

    with pytest.raises(RuntimeError, match="not running"):
        manager.get_open_trades(rec.id)


def test_get_profit_returns_data_when_running(tmp_db, manager) -> None:
    from crypto_trading_cli.db import insert_bot
    rec = _make_stopped_record()
    rec.status = "running"
    insert_bot(rec)

    mock_process = MagicMock()
    mock_process.is_running.return_value = True
    mock_process.api.get_profit.return_value = {
        "profit_all_percent": 5.0,
        "profit_closed_percent": 3.0,
        "trade_count": 10,
    }
    manager._instances[rec.id] = mock_process

    result = manager.get_profit(rec.id)
    assert result["profit_total"] == 5.0
    assert result["trade_count"] == 10


# ---------------------------------------------------------------------------
# recover_on_startup()
# ---------------------------------------------------------------------------


def test_recover_on_startup_marks_unreachable_bots_as_error(tmp_db, manager) -> None:
    from crypto_trading_cli.db import get_bot, insert_bot
    rec = _make_stopped_record()
    rec.status = "running"
    rec.port = 38291
    insert_bot(rec)

    # Mock FtApiClient.ping() to return False (process not reachable)
    with patch("crypto_trading_cli.bot_manager.FtApiClient") as MockClient:
        mock_api = MagicMock()
        mock_api.ping.return_value = False
        MockClient.return_value = mock_api

        manager.recover_on_startup()

    assert get_bot(rec.id).status == "error"


def test_recover_on_startup_keeps_reachable_bots_running(tmp_db, manager) -> None:
    from crypto_trading_cli.db import get_bot, insert_bot
    rec = _make_stopped_record()
    rec.status = "running"
    rec.port = 38291
    insert_bot(rec)

    with patch("crypto_trading_cli.bot_manager.FtApiClient") as MockClient:
        mock_api = MagicMock()
        mock_api.ping.return_value = True
        MockClient.return_value = mock_api

        manager.recover_on_startup()

    # Status should remain 'running'
    assert get_bot(rec.id).status == "running"
