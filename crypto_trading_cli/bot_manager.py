"""
Bot lifecycle manager.

BotManager is the single orchestrator for all bot operations. It owns the
in-memory map of bot_id → FreqtradeProcess and coordinates with the DB layer
for persistence.

All methods are synchronous — no async runtime is required for a CLI tool.
"""

import json
import logging
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

from crypto_trading_cli import db as db_module
from crypto_trading_cli.crypto import decrypt, encrypt
from crypto_trading_cli.db import BotRecord, delete_bot, get_bot, insert_bot
from crypto_trading_cli.ft_api_client import FtApiClient
from crypto_trading_cli.db import list_bots as db_list_bots
from crypto_trading_cli.db import list_bots_by_status, update_bot_port, update_bot_status
from crypto_trading_cli.ft_process import FreqtradeProcess
from crypto_trading_cli.strategy import build_freqtrade_config
from crypto_trading_cli.validators import validate_params

logger = logging.getLogger(__name__)

# Maximum number of concurrently running bots
MAX_RUNNING_BOTS = 10


@dataclass
class CreateBotParams:
    """Parameters collected from the user during bot creation."""

    exchange: str
    strategy: str
    params: dict[str, Any]
    api_key: str
    secret: str
    passphrase: Optional[str] = None
    dry_run: bool = True
    sandbox: bool = False


class BotManager:
    """
    Manages Freqtrade bot subprocesses and their DB records.

    Usage::

        manager = BotManager(freqtrade_bin="/path/to/freqtrade", proxy_url="http://127.0.0.1:7890")
        manager.recover_on_startup()   # call once at CLI startup
        record = manager.start(params)
        manager.stop(record.id)
    """

    def __init__(self, freqtrade_bin: str = "freqtrade", proxy_url: str = "") -> None:
        self._freqtrade_bin = freqtrade_bin
        self._proxy_url = proxy_url
        # In-memory map: bot_id → FreqtradeProcess
        self._instances: dict[str, FreqtradeProcess] = {}

    # ---------------------------------------------------------------------------
    # Startup recovery
    # ---------------------------------------------------------------------------

    def recover_on_startup(self) -> None:
        """
        Called once at CLI startup.

        Queries the DB for bots with status 'running'. For each, rebuilds the
        Freqtrade config and restarts the subprocess. Updates status to 'error'
        for any that fail to restart.
        """
        running_bots = list_bots_by_status("running")
        if not running_bots:
            return

        logger.info("Recovering %d previously-running bot(s)...", len(running_bots))
        for bot in running_bots:
            self._recover_one(bot)

    def _recover_one(self, bot: "BotRecord") -> None:
        """Rebuild config and restart a single bot subprocess."""
        try:
            port = FreqtradeProcess.alloc_port()
            ft_password = decrypt(bot.enc_ft_password)
            api_key = decrypt(bot.enc_api_key)
            secret = decrypt(bot.enc_secret)
            passphrase = decrypt(bot.enc_passphrase) if bot.enc_passphrase else None
            params = json.loads(bot.config_json)

            config = build_freqtrade_config(
                bot_id=bot.id,
                exchange=bot.exchange,
                strategy=bot.strategy,
                params=params,
                api_key=api_key,
                secret=secret,
                port=port,
                ft_password=ft_password,
                dry_run=bot.dry_run,
                sandbox=bot.sandbox,
                passphrase=passphrase,
                proxy_url=self._proxy_url,
            )

            process = FreqtradeProcess(
                bot_id=bot.id,
                port=port,
                ft_password=ft_password,
                freqtrade_bin=self._freqtrade_bin,
                proxy_url=self._proxy_url,
                on_error=self._make_error_callback(bot.id),
            )
            process.start(config)
            self._instances[bot.id] = process
            update_bot_port(bot.id, port)
            logger.info("Recovered bot %s on port %d", bot.id[:8], port)
        except Exception as exc:
            logger.error("Failed to recover bot %s: %s", bot.id[:8], exc)
            update_bot_status(bot.id, "error", str(exc))

    # ---------------------------------------------------------------------------
    # Start
    # ---------------------------------------------------------------------------

    def start(self, params: CreateBotParams) -> BotRecord:
        """
        Create and start a new bot.

        Validates strategy parameters, writes the bot record to the DB,
        spawns the Freqtrade subprocess, and updates the status to 'running'.

        Raises:
            ValueError: If strategy parameters are invalid.
            RuntimeError: If the Freqtrade subprocess fails to start.
            RuntimeError: If the maximum number of running bots is reached.
        """
        # Validate strategy params
        validate_params(params.strategy, params.params)

        # Check running bot limit
        running_count = len(list_bots_by_status("running"))
        if running_count >= MAX_RUNNING_BOTS:
            raise RuntimeError(
                f"Maximum number of concurrent bots ({MAX_RUNNING_BOTS}) reached. "
                "Stop an existing bot first."
            )

        bot_id = str(uuid.uuid4())
        port = FreqtradeProcess.alloc_port()
        ft_password = secrets.token_urlsafe(24)

        # Encrypt credentials before writing to DB
        enc_api_key = encrypt(params.api_key)
        enc_secret = encrypt(params.secret)
        enc_passphrase = encrypt(params.passphrase) if params.passphrase else None
        enc_ft_password = encrypt(ft_password)

        # Insert bot record with status 'stopped' (updated to 'running' after start)
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        record = BotRecord(
            id=bot_id,
            exchange=params.exchange,
            strategy=params.strategy,
            status="stopped",
            config_json=json.dumps(params.params),
            enc_api_key=enc_api_key,
            enc_secret=enc_secret,
            enc_passphrase=enc_passphrase,
            enc_ft_password=enc_ft_password,
            dry_run=params.dry_run,
            sandbox=params.sandbox,
            port=port,
            created_at=now,
        )
        insert_bot(record)

        # Build Freqtrade config in memory
        config = build_freqtrade_config(
            bot_id=bot_id,
            exchange=params.exchange,
            strategy=params.strategy,
            params=params.params,
            api_key=params.api_key,
            secret=params.secret,
            port=port,
            ft_password=ft_password,
            dry_run=params.dry_run,
            sandbox=params.sandbox,
            passphrase=params.passphrase,
            proxy_url=self._proxy_url,
        )

        # Spawn the subprocess
        process = FreqtradeProcess(
            bot_id=bot_id,
            port=port,
            ft_password=ft_password,
            freqtrade_bin=self._freqtrade_bin,
            proxy_url=self._proxy_url,
            on_error=self._make_error_callback(bot_id),
        )

        try:
            process.start(config)
        except Exception as exc:
            last_lines = "\n".join(process.get_last_output_lines())
            update_bot_status(bot_id, "error", str(exc))
            raise RuntimeError(
                f"Freqtrade failed to start: {exc}\n\nLast output:\n{last_lines}"
            ) from exc

        self._instances[bot_id] = process
        update_bot_status(bot_id, "running")
        update_bot_port(bot_id, port)

        result = get_bot(bot_id)
        assert result is not None
        return result

    # ---------------------------------------------------------------------------
    # Stop
    # ---------------------------------------------------------------------------

    def stop(self, bot_id: str) -> BotRecord:
        """
        Stop a running bot.

        Raises:
            ValueError: If the bot is not found.
        """
        record = self._get_or_raise(bot_id)
        process = self._instances.pop(bot_id, None)
        if process:
            process.stop()
        update_bot_status(bot_id, "stopped")
        result = get_bot(bot_id)
        assert result is not None
        return result

    # ---------------------------------------------------------------------------
    # Restart
    # ---------------------------------------------------------------------------

    def restart(self, bot_id: str) -> BotRecord:
        """
        Restart a bot (stop if running, then start again with stored params).

        Raises:
            ValueError: If the bot is not found.
            RuntimeError: If the Freqtrade subprocess fails to start.
        """
        record = self._get_or_raise(bot_id)

        # Stop existing process if running
        process = self._instances.pop(bot_id, None)
        if process:
            process.stop()

        # Allocate a new port
        port = FreqtradeProcess.alloc_port()
        ft_password = decrypt(record.enc_ft_password)
        api_key = decrypt(record.enc_api_key)
        secret = decrypt(record.enc_secret)
        passphrase = decrypt(record.enc_passphrase) if record.enc_passphrase else None
        params = json.loads(record.config_json)

        config = build_freqtrade_config(
            bot_id=bot_id,
            exchange=record.exchange,
            strategy=record.strategy,
            params=params,
            api_key=api_key,
            secret=secret,
            port=port,
            ft_password=ft_password,
            dry_run=record.dry_run,
            sandbox=record.sandbox,
            passphrase=passphrase,
            proxy_url=self._proxy_url,
        )

        new_process = FreqtradeProcess(
            bot_id=bot_id,
            port=port,
            ft_password=ft_password,
            freqtrade_bin=self._freqtrade_bin,
            proxy_url=self._proxy_url,
            on_error=self._make_error_callback(bot_id),
        )

        try:
            new_process.start(config)
        except Exception as exc:
            last_lines = "\n".join(new_process.get_last_output_lines())
            update_bot_status(bot_id, "error", str(exc))
            raise RuntimeError(
                f"Freqtrade failed to restart: {exc}\n\nLast output:\n{last_lines}"
            ) from exc

        self._instances[bot_id] = new_process
        update_bot_status(bot_id, "running")
        update_bot_port(bot_id, port)

        result = get_bot(bot_id)
        assert result is not None
        return result

    # ---------------------------------------------------------------------------
    # Delete
    # ---------------------------------------------------------------------------

    def delete(self, bot_id: str) -> None:
        """
        Stop and permanently delete a bot.

        Raises:
            ValueError: If the bot is not found.
        """
        self._get_or_raise(bot_id)
        process = self._instances.pop(bot_id, None)
        if process:
            process.stop()
        delete_bot(bot_id)

    # ---------------------------------------------------------------------------
    # Query methods
    # ---------------------------------------------------------------------------

    def list_bots(self) -> list[BotRecord]:
        """Return all bot records from the DB."""
        return db_list_bots()

    def get_status(self, bot_id: str) -> BotRecord:
        """
        Return the DB record for *bot_id*.

        Raises:
            ValueError: If the bot is not found.
        """
        return self._get_or_raise(bot_id)

    def get_profit(self, bot_id: str) -> dict[str, Any]:
        """
        Return profit summary for a running bot.

        Raises:
            ValueError: If the bot is not found.
            RuntimeError: If the bot is not running.
        """
        record = self._get_or_raise(bot_id)
        process = self._instances.get(bot_id)
        if not process or not process.is_running():
            raise RuntimeError("Bot is not running. Start the bot first.")
        try:
            data = process.api.get_profit()
            return {
                "bot_id": bot_id,
                "profit_total": data.get("profit_all_percent", 0.0),
                "profit_realized": data.get("profit_closed_percent", 0.0),
                "trade_count": data.get("trade_count", 0),
            }
        except Exception as exc:
            raise RuntimeError(f"Failed to retrieve data: {exc}") from exc

    def get_open_trades(self, bot_id: str) -> list[dict[str, Any]]:
        """
        Return open trades for a running bot.

        Raises:
            ValueError: If the bot is not found.
            RuntimeError: If the bot is not running or the API call fails.
        """
        self._get_or_raise(bot_id)
        process = self._instances.get(bot_id)
        if not process or not process.is_running():
            raise RuntimeError("Bot is not running. Start the bot first.")
        try:
            return process.api.get_status()
        except Exception as exc:
            raise RuntimeError(f"Failed to retrieve data: {exc}") from exc

    def force_exit(self, bot_id: str, trade_id: str | int) -> dict[str, Any]:
        """
        Force-exit a trade for a running bot.

        Raises:
            ValueError: If the bot is not found.
            RuntimeError: If the bot is not running or the API call fails.
        """
        self._get_or_raise(bot_id)
        process = self._instances.get(bot_id)
        if not process or not process.is_running():
            raise RuntimeError("Bot is not running. Start the bot first.")
        try:
            return process.api.force_exit(trade_id)
        except Exception as exc:
            raise RuntimeError(f"Force exit failed: {exc}") from exc

    def get_health(self, bot_id: str) -> dict[str, Any]:
        """
        Return health information for a bot.

        Raises:
            ValueError: If the bot is not found.
        """
        record = self._get_or_raise(bot_id)
        process = self._instances.get(bot_id)
        process_running = process is not None and process.is_running()
        api_reachable = False
        last_ts = None

        if process_running:
            api_reachable = process.api.ping()
            if api_reachable:
                try:
                    health = process.api.get_health()
                    last_ts = health.get("last_process_ts")
                except Exception:
                    pass

        return {
            "bot_id": bot_id,
            "process_running": process_running,
            "api_reachable": api_reachable,
            "last_process_ts": last_ts,
        }

    # ---------------------------------------------------------------------------
    # Internal helpers
    # ---------------------------------------------------------------------------

    def _get_or_raise(self, bot_id: str) -> BotRecord:
        record = get_bot(bot_id)
        if record is None:
            raise ValueError(f"Bot not found: {bot_id}")
        return record

    def _make_error_callback(self, bot_id: str):
        """Return an on_error callback that updates the DB status."""
        def on_error(bid: str, reason: str) -> None:
            logger.error("[bot %s] error: %s", bid[:8], reason)
            update_bot_status(bid, "error", reason)
            self._instances.pop(bid, None)
        return on_error


# Module-level singleton — initialised in main.py after config is loaded
bot_manager: Optional[BotManager] = None


def init_bot_manager(freqtrade_bin: str, proxy_url: str = "") -> BotManager:
    """Initialise and return the global BotManager singleton."""
    global bot_manager
    bot_manager = BotManager(freqtrade_bin=freqtrade_bin, proxy_url=proxy_url)
    return bot_manager
