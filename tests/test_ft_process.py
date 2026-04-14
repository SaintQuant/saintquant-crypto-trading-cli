"""
Tests for crypto_trading_cli.ft_process

Property 4 (port uniqueness): N sequential alloc_port() calls return distinct
  ports all in the range 1024–65535.

Property 4 (Temp_Config deletion): After start() completes (success or failure),
  no temp config file written during that call exists on disk.
"""

import json
import os
import subprocess
import tempfile
import threading
import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from crypto_trading_cli.ft_process import FreqtradeProcess


# ---------------------------------------------------------------------------
# Property 5: Port allocation — uniqueness and valid range
# ---------------------------------------------------------------------------


@given(n=st.integers(min_value=2, max_value=20))
@settings(max_examples=30)
def test_alloc_port_uniqueness(n: int) -> None:
    """N sequential alloc_port() calls must return distinct ports."""
    ports = [FreqtradeProcess.alloc_port() for _ in range(n)]
    assert len(ports) == len(set(ports)), f"Duplicate ports found: {ports}"


def test_alloc_port_valid_range() -> None:
    port = FreqtradeProcess.alloc_port()
    assert isinstance(port, int)
    assert 1024 <= port <= 65535, f"Port {port} out of valid range"


def test_alloc_port_returns_int() -> None:
    assert isinstance(FreqtradeProcess.alloc_port(), int)


# ---------------------------------------------------------------------------
# Property 4: Temp_Config is deleted after start() — success path
# ---------------------------------------------------------------------------


def test_temp_config_deleted_on_successful_start(tmp_path) -> None:
    """
    After a successful start(), the temp config file must not exist on disk.
    We mock subprocess.Popen and the watcher thread to simulate a ready bot.
    """
    created_tmp_paths: list[str] = []

    # Capture the temp file path before it's deleted
    original_mkstemp = tempfile.mkstemp

    def capturing_mkstemp(**kwargs):
        fd, path = original_mkstemp(**kwargs)
        created_tmp_paths.append(path)
        return fd, path

    mock_process = MagicMock()
    mock_process.poll.return_value = None  # process is alive
    mock_process.stdout = iter([b"bot heartbeat\n"])  # triggers ready marker

    process = FreqtradeProcess(
        bot_id=str(uuid.uuid4()),
        port=FreqtradeProcess.alloc_port(),
        ft_password="test_pw",
        freqtrade_bin="echo",  # harmless command
    )

    # Patch Popen to return our mock and mkstemp to capture the path
    with patch("crypto_trading_cli.ft_process.subprocess.Popen", return_value=mock_process):
        with patch("crypto_trading_cli.ft_process.tempfile.mkstemp", side_effect=capturing_mkstemp):
            # The watcher thread will set ready_event via the mock stdout
            # We need to ensure the ready_event gets set
            def set_ready(*args, **kwargs):
                process._ready_event.set()

            process._watch_output = set_ready  # override watcher

            try:
                process.start({"test": "config"})
            except Exception:
                pass  # we only care about file deletion

    for path in created_tmp_paths:
        assert not os.path.exists(path), f"Temp config still exists: {path}"


def test_temp_config_deleted_on_failed_start(tmp_path) -> None:
    """
    After a failed start() (process exits immediately), the temp config file
    must not exist on disk.
    """
    created_tmp_paths: list[str] = []
    original_mkstemp = tempfile.mkstemp

    def capturing_mkstemp(**kwargs):
        fd, path = original_mkstemp(**kwargs)
        created_tmp_paths.append(path)
        return fd, path

    mock_process = MagicMock()
    mock_process.poll.return_value = 1  # process exited with error
    mock_process.stdout = iter([b"configuration error\n"])

    process = FreqtradeProcess(
        bot_id=str(uuid.uuid4()),
        port=FreqtradeProcess.alloc_port(),
        ft_password="test_pw",
        freqtrade_bin="false",  # exits immediately with code 1
    )

    def set_ready_and_fail(*args, **kwargs):
        process._ready_event.set()

    process._watch_output = set_ready_and_fail

    with patch("crypto_trading_cli.ft_process.subprocess.Popen", return_value=mock_process):
        with patch("crypto_trading_cli.ft_process.tempfile.mkstemp", side_effect=capturing_mkstemp):
            try:
                process.start({"test": "config"})
            except Exception:
                pass

    for path in created_tmp_paths:
        assert not os.path.exists(path), f"Temp config still exists after failure: {path}"


# ---------------------------------------------------------------------------
# Example-based: is_running()
# ---------------------------------------------------------------------------


def test_is_running_false_when_no_process() -> None:
    process = FreqtradeProcess(
        bot_id=str(uuid.uuid4()),
        port=FreqtradeProcess.alloc_port(),
        ft_password="pw",
    )
    assert process.is_running() is False


def test_is_running_false_after_process_exits() -> None:
    mock_process = MagicMock()
    mock_process.poll.return_value = 0  # exited

    process = FreqtradeProcess(
        bot_id=str(uuid.uuid4()),
        port=FreqtradeProcess.alloc_port(),
        ft_password="pw",
    )
    process._process = mock_process
    assert process.is_running() is False


def test_is_running_true_when_process_alive() -> None:
    mock_process = MagicMock()
    mock_process.poll.return_value = None  # still running

    process = FreqtradeProcess(
        bot_id=str(uuid.uuid4()),
        port=FreqtradeProcess.alloc_port(),
        ft_password="pw",
    )
    process._process = mock_process
    assert process.is_running() is True
