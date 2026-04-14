"""
Local SQLite database layer.

All bot state is persisted in ~/.crypto-cli/bots.db using the Python standard
library sqlite3 module. No ORM is used — the schema is simple and fixed.
"""

import logging
import os
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

_CREATE_BOTS_TABLE = """
CREATE TABLE IF NOT EXISTS bots (
    id              TEXT PRIMARY KEY,
    exchange        TEXT NOT NULL,
    strategy        TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'stopped',
    config_json     TEXT NOT NULL,
    enc_api_key     TEXT NOT NULL,
    enc_secret      TEXT NOT NULL,
    enc_passphrase  TEXT,
    enc_ft_password TEXT NOT NULL,
    dry_run         INTEGER NOT NULL DEFAULT 0,
    sandbox         INTEGER NOT NULL DEFAULT 0,
    port            INTEGER,
    error_msg       TEXT,
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);
"""

_CREATE_STATUS_INDEX = """
CREATE INDEX IF NOT EXISTS idx_bots_status ON bots(status);
"""

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class BotRecord:
    """In-memory representation of a bot row."""

    id: str
    exchange: str
    strategy: str
    status: str
    config_json: str
    enc_api_key: str
    enc_secret: str
    enc_ft_password: str
    dry_run: bool
    sandbox: bool
    enc_passphrase: Optional[str] = None
    port: Optional[int] = None
    error_msg: Optional[str] = None
    created_at: str = ""


# ---------------------------------------------------------------------------
# Connection helper
# ---------------------------------------------------------------------------

_db_path: Optional[str] = None


def set_db_path(path: str) -> None:
    """Configure the database file path (called once during startup)."""
    global _db_path
    _db_path = path


def _connect() -> sqlite3.Connection:
    if not _db_path:
        raise RuntimeError("DB path not configured. Call set_db_path() first.")
    conn = sqlite3.connect(_db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def init_db(db_path: str) -> None:
    """
    Initialise the database at *db_path*.

    Creates the file and applies the schema if it does not already exist.
    Sets file permissions to ``0o600`` on POSIX systems.
    """
    set_db_path(db_path)
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)

    with _connect() as conn:
        conn.execute(_CREATE_BOTS_TABLE)
        conn.execute(_CREATE_STATUS_INDEX)
        conn.commit()

    if os.name == "posix":
        os.chmod(db_path, 0o600)

    logger.debug("Database initialised at %s", db_path)


def insert_bot(bot: BotRecord) -> None:
    """Insert a new bot record into the database."""
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO bots (
                id, exchange, strategy, status, config_json,
                enc_api_key, enc_secret, enc_passphrase, enc_ft_password,
                dry_run, sandbox, port, error_msg, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                bot.id,
                bot.exchange,
                bot.strategy,
                bot.status,
                bot.config_json,
                bot.enc_api_key,
                bot.enc_secret,
                bot.enc_passphrase,
                bot.enc_ft_password,
                int(bot.dry_run),
                int(bot.sandbox),
                bot.port,
                bot.error_msg,
                bot.created_at,
            ),
        )
        conn.commit()


def get_bot(bot_id: str) -> Optional[BotRecord]:
    """Return the bot record for *bot_id*, or ``None`` if not found."""
    with _connect() as conn:
        row = conn.execute("SELECT * FROM bots WHERE id = ?", (bot_id,)).fetchone()
    return _row_to_record(row) if row else None


def update_bot_status(
    bot_id: str,
    status: str,
    error_msg: Optional[str] = None,
) -> None:
    """Update the status (and optional error message) of a bot."""
    with _connect() as conn:
        conn.execute(
            "UPDATE bots SET status = ?, error_msg = ? WHERE id = ?",
            (status, error_msg, bot_id),
        )
        conn.commit()


def update_bot_port(bot_id: str, port: int) -> None:
    """Update the port of a running bot (used after restart)."""
    with _connect() as conn:
        conn.execute("UPDATE bots SET port = ? WHERE id = ?", (port, bot_id))
        conn.commit()


def list_bots() -> list[BotRecord]:
    """Return all bot records ordered by creation time (newest first)."""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM bots ORDER BY created_at DESC"
        ).fetchall()
    return [_row_to_record(r) for r in rows]


def list_bots_by_status(status: str) -> list[BotRecord]:
    """Return all bot records with the given *status*."""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM bots WHERE status = ? ORDER BY created_at DESC",
            (status,),
        ).fetchall()
    return [_row_to_record(r) for r in rows]


def delete_bot(bot_id: str) -> None:
    """Delete the bot record for *bot_id*."""
    with _connect() as conn:
        conn.execute("DELETE FROM bots WHERE id = ?", (bot_id,))
        conn.commit()


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _row_to_record(row: sqlite3.Row) -> BotRecord:
    return BotRecord(
        id=row["id"],
        exchange=row["exchange"],
        strategy=row["strategy"],
        status=row["status"],
        config_json=row["config_json"],
        enc_api_key=row["enc_api_key"],
        enc_secret=row["enc_secret"],
        enc_passphrase=row["enc_passphrase"],
        enc_ft_password=row["enc_ft_password"],
        dry_run=bool(row["dry_run"]),
        sandbox=bool(row["sandbox"]),
        port=row["port"],
        error_msg=row["error_msg"],
        created_at=row["created_at"],
    )
