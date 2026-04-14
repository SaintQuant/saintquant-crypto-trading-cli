"""
Freqtrade subprocess manager.

FreqtradeProcess wraps subprocess.Popen and a background threading.Thread
that monitors stdout for readiness markers, credential errors, and unexpected
process exits.

Security note: The Freqtrade config JSON (which contains exchange credentials)
is written to a temporary file, passed to the subprocess, and deleted
immediately after the process reads it — regardless of whether startup
succeeds or fails.
"""

import json
import logging
import os
import shutil
import signal
import socket
import subprocess
import tempfile
import threading
from pathlib import Path
from typing import Any, Callable, Optional

from crypto_trading_cli.ft_api_client import FtApiClient

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_START_TIMEOUT_SECS = 90

# Log lines containing any of these strings indicate the bot is ready
_READY_MARKERS = (
    "bot heartbeat",
    "rpc manager is ready",
    "api server ready",
    "starting freqtrade",
    "freqtrade is ready",
)

# Log lines containing any of these strings indicate invalid credentials
_INVALID_KEY_KEYWORDS = (
    "invalid api_key",
    "authentication failed",
    "invalid key",
    "api key",
    "unauthorized",
)

# Log lines containing any of these strings indicate a fatal startup error
_FATAL_KEYWORDS = (
    "strategy not found",
    "no module named",
    "importerror",
    "syntaxerror",
    "configuration error",
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _find_freqtrade_bin(configured_path: str | None = None) -> str:
    """
    Locate the freqtrade executable.

    Checks (in order):
      1. The path stored in AppConfig (if provided)
      2. Common install locations
      3. System PATH via shutil.which
    """
    candidates = [
        configured_path,
        str(Path.home() / ".local" / "bin" / "freqtrade"),
        "/usr/local/bin/freqtrade",
        "/usr/bin/freqtrade",
    ]
    for path in candidates:
        if path and os.path.isfile(path) and os.access(path, os.X_OK):
            return path

    # Fall back to PATH lookup
    found = shutil.which("freqtrade")
    if found:
        return found

    return "freqtrade"  # last resort — will fail with a clear OS error


# ---------------------------------------------------------------------------
# FreqtradeProcess
# ---------------------------------------------------------------------------


class FreqtradeProcess:
    """
    Manages a single Freqtrade subprocess.

    Usage::

        process = FreqtradeProcess(
            bot_id="abc123...",
            port=38291,
            ft_password="random_password",
            freqtrade_bin="/path/to/freqtrade",
            on_error=lambda bot_id, reason: ...,
        )
        process.start(config_dict)   # blocks until ready or raises
        process.stop()               # SIGTERM → wait → SIGKILL
    """

    def __init__(
        self,
        bot_id: str,
        port: int,
        ft_password: str,
        freqtrade_bin: str = "freqtrade",
        proxy_url: str = "",
        on_error: Optional[Callable[[str, str], None]] = None,
    ) -> None:
        self.bot_id = bot_id
        self.port = port
        self._ft_password = ft_password
        self._freqtrade_bin = freqtrade_bin
        self._proxy_url = proxy_url
        self.on_error = on_error

        self._process: Optional[subprocess.Popen] = None
        self._watcher_thread: Optional[threading.Thread] = None
        self._ready_event = threading.Event()
        self._output_lines: list[str] = []
        self._output_lock = threading.Lock()

        self.api = FtApiClient(
            base_url=f"http://127.0.0.1:{port}/api/v1",
            username="freqtrade",
            password=ft_password,
            proxy_url=proxy_url,
        )

    @staticmethod
    def alloc_port() -> int:
        """
        Allocate a free local TCP port using OS ephemeral port assignment.

        Binds to port 0, reads the assigned port, then closes the socket.
        There is a small TOCTOU window between close and Freqtrade binding,
        which is acceptable for a local single-user tool.
        """
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0))
            return s.getsockname()[1]

    def start(self, config: dict[str, Any]) -> None:
        """
        Start the Freqtrade subprocess.

        Writes *config* to a temporary file, spawns the subprocess, waits up
        to 90 seconds for a readiness marker, then deletes the temp file.

        Raises:
            RuntimeError: If the process exits before becoming ready, or if
                          the 90-second timeout expires.
        """
        tmp_path: Optional[str] = None
        try:
            # Write config to a temp file (credentials are in this file)
            fd, tmp_path = tempfile.mkstemp(
                suffix=".json",
                prefix=f"ft_{self.bot_id[:8]}_",
            )
            with os.fdopen(fd, "w") as f:
                json.dump(config, f)

            logger.info(
                "[bot %s] launching freqtrade on port %d",
                self.bot_id[:8],
                self.port,
            )

            # Inject proxy into subprocess environment if configured
            env = os.environ.copy()
            if self._proxy_url:
                env["HTTP_PROXY"] = self._proxy_url
                env["HTTPS_PROXY"] = self._proxy_url
                env["http_proxy"] = self._proxy_url
                env["https_proxy"] = self._proxy_url
                # Ensure local API calls never go through the proxy
                no_proxy = "127.0.0.1,localhost"
                env["NO_PROXY"] = no_proxy
                env["no_proxy"] = no_proxy

            self._process = subprocess.Popen(
                [self._freqtrade_bin, "trade", "--config", tmp_path],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=False,
                env=env,
            )

            # Start background watcher thread
            self._ready_event.clear()
            self._output_lines.clear()
            self._watcher_thread = threading.Thread(
                target=self._watch_output,
                daemon=True,
                name=f"ft-watcher-{self.bot_id[:8]}",
            )
            self._watcher_thread.start()

            # Wait for readiness
            self._wait_for_ready()

        finally:
            # Always delete the temp config file — credentials must not persist
            if tmp_path and os.path.exists(tmp_path):
                try:
                    os.unlink(tmp_path)
                    logger.debug("[bot %s] temp config deleted", self.bot_id[:8])
                except OSError as exc:
                    logger.warning(
                        "[bot %s] failed to delete temp config: %s",
                        self.bot_id[:8],
                        exc,
                    )

    def _wait_for_ready(self) -> None:
        """Block until the ready event fires or the timeout expires."""
        if self._ready_event.wait(timeout=_START_TIMEOUT_SECS):
            logger.info("[bot %s] ready on port %d", self.bot_id[:8], self.port)
            return

        # Timeout — check if process is still alive
        if self._process and self._process.poll() is not None:
            with self._output_lock:
                last_lines = "\n".join(self._output_lines[-15:])
            raise RuntimeError(
                f"Freqtrade exited unexpectedly during startup:\n{last_lines}"
            )

        # Process alive but no readiness marker — try pinging the API
        logger.warning(
            "[bot %s] readiness marker not found within %ds, probing API...",
            self.bot_id[:8],
            _START_TIMEOUT_SECS,
        )
        for _ in range(30):
            import time
            time.sleep(1)
            if self.api.ping():
                logger.info("[bot %s] API responded — treating as ready", self.bot_id[:8])
                return

        with self._output_lock:
            last_lines = "\n".join(self._output_lines[-15:])
        raise RuntimeError(
            f"Freqtrade API did not become ready after {_START_TIMEOUT_SECS + 30}s:\n{last_lines}"
        )

    def stop(self) -> None:
        """
        Stop the Freqtrade subprocess gracefully.

        Sends SIGTERM, waits up to 10 seconds, then sends SIGKILL if the
        process has not exited.
        """
        if self._process and self._process.poll() is None:
            logger.info("[bot %s] sending SIGTERM", self.bot_id[:8])
            self._process.send_signal(signal.SIGTERM)
            try:
                self._process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                logger.warning("[bot %s] SIGTERM timeout — sending SIGKILL", self.bot_id[:8])
                self._process.kill()
                self._process.wait()

        if self._watcher_thread and self._watcher_thread.is_alive():
            self._watcher_thread.join(timeout=5)

        logger.info("[bot %s] stopped", self.bot_id[:8])

    def is_running(self) -> bool:
        """Return True if the subprocess is alive."""
        return self._process is not None and self._process.poll() is None

    def get_last_output_lines(self, n: int = 15) -> list[str]:
        """Return the last *n* lines of subprocess stdout."""
        with self._output_lock:
            return list(self._output_lines[-n:])

    # ---------------------------------------------------------------------------
    # Background watcher thread
    # ---------------------------------------------------------------------------

    def _watch_output(self) -> None:
        """
        Read subprocess stdout line-by-line in a background thread.

        - Sets ``_ready_event`` when a readiness marker is detected.
        - Calls ``on_error`` when invalid-credential keywords are detected.
        - Calls ``on_error`` when the process exits unexpectedly.
        - Logs all output at DEBUG level.
        """
        if not self._process or not self._process.stdout:
            return

        try:
            for line_bytes in self._process.stdout:
                line = line_bytes.decode(errors="replace").rstrip()
                logger.debug("[bot %s] %s", self.bot_id[:8], line)

                with self._output_lock:
                    self._output_lines.append(line)
                    # Keep a rolling buffer of the last 200 lines
                    if len(self._output_lines) > 200:
                        self._output_lines.pop(0)

                ll = line.lower()

                # Readiness detection
                if any(marker in ll for marker in _READY_MARKERS):
                    self._ready_event.set()

                # Invalid credentials detection
                if any(kw in ll for kw in _INVALID_KEY_KEYWORDS):
                    logger.error(
                        "[bot %s] invalid exchange credentials detected",
                        self.bot_id[:8],
                    )
                    self._ready_event.set()  # unblock start() so it can raise
                    if self.on_error:
                        self.on_error(self.bot_id, "invalid exchange credentials")
                    return

                # Fatal startup error
                if any(kw in ll for kw in _FATAL_KEYWORDS):
                    if self._process.poll() is not None:
                        self._ready_event.set()
                        if self.on_error:
                            with self._output_lock:
                                last = "\n".join(self._output_lines[-15:])
                            self.on_error(self.bot_id, f"fatal startup error:\n{last}")
                        return

        except Exception as exc:
            logger.exception("[bot %s] watcher error: %s", self.bot_id[:8], exc)
        finally:
            # Process has exited — check return code
            if self._process:
                rc = self._process.poll()
                if rc is not None and rc != 0:
                    logger.error(
                        "[bot %s] process exited with code %d",
                        self.bot_id[:8],
                        rc,
                    )
                    self._ready_event.set()  # unblock any waiting start()
                    if self.on_error:
                        self.on_error(self.bot_id, f"process exited with code {rc}")
