"""
Application configuration management.

Stores CLI-level settings (Freqtrade binary path, DB path, etc.) in
~/.crypto-cli/config.json with owner-only (600) file permissions.
"""

import json
import logging
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

# Directory and file paths
CONFIG_DIR = Path.home() / ".crypto-cli"
CONFIG_PATH = CONFIG_DIR / "config.json"
DEFAULT_DB_PATH = str(CONFIG_DIR / "bots.db")


@dataclass
class AppConfig:
    """Persisted CLI configuration."""

    freqtrade_bin: str
    """Absolute path to the freqtrade executable."""

    freqtrade_version: str
    """Version string reported by ``freqtrade --version``."""

    db_path: str = DEFAULT_DB_PATH
    """Absolute path to the SQLite bot database."""

    proxy_url: str = ""
    """
    Optional HTTP/HTTPS/SOCKS5 proxy URL, e.g. ``http://127.0.0.1:7890``
    or ``socks5://127.0.0.1:1080``.  Empty string means no proxy.
    """

    created_at: str = ""
    """ISO 8601 timestamp of when the config was first created."""


def load_config() -> AppConfig | None:
    """
    Load and return the :class:`AppConfig` from disk.

    Returns ``None`` if the config file does not exist.
    Raises ``ValueError`` if the file exists but is invalid JSON or missing
    required fields.
    """
    if not CONFIG_PATH.exists():
        return None

    try:
        data = json.loads(CONFIG_PATH.read_text())
    except json.JSONDecodeError as exc:
        raise ValueError(f"Config file is corrupted: {exc}") from exc

    required = {"freqtrade_bin", "freqtrade_version"}
    missing = required - data.keys()
    if missing:
        raise ValueError(f"Config file is missing required fields: {missing}")

    return AppConfig(
        freqtrade_bin=data["freqtrade_bin"],
        freqtrade_version=data["freqtrade_version"],
        db_path=data.get("db_path", DEFAULT_DB_PATH),
        proxy_url=data.get("proxy_url", ""),
        created_at=data.get("created_at", ""),
    )


def save_config(cfg: AppConfig) -> None:
    """
    Write *cfg* to disk as JSON.

    Creates ``~/.crypto-cli/`` if it does not exist and sets file permissions
    to ``0o600`` (owner read/write only) on POSIX systems.
    """
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(asdict(cfg), indent=2))

    # Restrict permissions on POSIX (Linux / macOS)
    if os.name == "posix":
        os.chmod(CONFIG_PATH, 0o600)
        os.chmod(CONFIG_DIR, 0o700)

    logger.debug("Config saved to %s", CONFIG_PATH)
