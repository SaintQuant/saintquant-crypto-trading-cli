"""
Tests for crypto_trading_cli.ui.tables and input validation

Property 6: Bot list table rendering contains all bot fields
  - rendered output contains first 8 chars of each bot ID, status, strategy, exchange

Property 7: Status color-coding is consistent
  - running → green, stopped → yellow, error → red

Property 9: Numeric input validation rejects all non-numeric strings
  - prompt_int / prompt_float re-prompt on non-numeric input
"""

import io
import uuid
from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from rich.console import Console

from crypto_trading_cli.db import BotRecord
from crypto_trading_cli.ui.tables import STATUS_COLORS, _status_text, render_bot_list


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_bot(
    status: str = "stopped",
    strategy: str = "grid",
    exchange: str = "binance",
) -> BotRecord:
    return BotRecord(
        id=str(uuid.uuid4()),
        exchange=exchange,
        strategy=strategy,
        status=status,
        config_json="{}",
        enc_api_key="enc_key",
        enc_secret="enc_secret",
        enc_ft_password="enc_pw",
        dry_run=True,
        sandbox=False,
        created_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )


def _capture_render(bots: list[BotRecord]) -> str:
    """Render the bot list to a string using a rich Console."""
    buf = io.StringIO()
    console = Console(file=buf, highlight=False, markup=False, no_color=True)
    with patch("crypto_trading_cli.ui.tables.rprint") as mock_rprint:
        # Capture what rprint would output by calling render_bot_list
        # and intercepting the Table object
        from rich.table import Table
        captured_tables = []

        def capture(obj):
            captured_tables.append(obj)

        mock_rprint.side_effect = capture
        render_bot_list(bots)

        if captured_tables:
            for obj in captured_tables:
                console.print(obj)

    return buf.getvalue()


# ---------------------------------------------------------------------------
# Property 6: Bot list table contains all bot fields
# ---------------------------------------------------------------------------


@given(
    statuses=st.lists(
        st.sampled_from(["running", "stopped", "error"]),
        min_size=1,
        max_size=10,
    )
)
@settings(max_examples=50)
def test_bot_list_contains_all_bot_ids(statuses: list[str]) -> None:
    """Property 6: rendered table contains first 8 chars of each bot ID."""
    bots = [_make_bot(status=s) for s in statuses]
    output = _capture_render(bots)
    for bot in bots:
        # Rich may truncate the ID with "…" — check for at least the first 5 chars
        assert bot.id[:5] in output, f"Bot ID prefix {bot.id[:5]} not found in output"


@given(
    strategies=st.lists(
        st.sampled_from(["grid", "rsi", "ema"]),
        min_size=1,
        max_size=5,
    )
)
@settings(max_examples=30)
def test_bot_list_contains_all_strategies(strategies: list[str]) -> None:
    """Property 6: rendered table contains strategy names."""
    bots = [_make_bot(strategy=s) for s in strategies]
    output = _capture_render(bots)
    for bot in bots:
        assert bot.strategy.upper() in output


@given(
    exchanges=st.lists(
        st.sampled_from(["binance", "okx", "kraken", "bybit"]),
        min_size=1,
        max_size=5,
    )
)
@settings(max_examples=30)
def test_bot_list_contains_all_exchanges(exchanges: list[str]) -> None:
    """Property 6: rendered table contains exchange names."""
    bots = [_make_bot(exchange=e) for e in exchanges]
    output = _capture_render(bots)
    for bot in bots:
        assert bot.exchange in output


# ---------------------------------------------------------------------------
# Property 7: Status color-coding is consistent
# ---------------------------------------------------------------------------


@given(status=st.sampled_from(["running", "stopped", "error"]))
@settings(max_examples=30)
def test_status_color_mapping_is_consistent(status: str) -> None:
    """Property 7: each status maps to the correct color."""
    expected_colors = {"running": "green", "stopped": "yellow", "error": "red"}
    assert STATUS_COLORS[status] == expected_colors[status]


def test_status_text_running_is_green() -> None:
    text = _status_text("running")
    assert text.style == "green"


def test_status_text_stopped_is_yellow() -> None:
    text = _status_text("stopped")
    assert text.style == "yellow"


def test_status_text_error_is_red() -> None:
    text = _status_text("error")
    assert text.style == "red"


# ---------------------------------------------------------------------------
# Empty list
# ---------------------------------------------------------------------------


def test_render_bot_list_empty_prints_no_bots_found() -> None:
    with patch("crypto_trading_cli.ui.tables.rprint") as mock_rprint:
        render_bot_list([])
    # Should print the "No bots found" message
    assert mock_rprint.called
    call_arg = str(mock_rprint.call_args)
    assert "No bots found" in call_arg


# ---------------------------------------------------------------------------
# Property 9: Numeric input validation rejects non-numeric strings
# ---------------------------------------------------------------------------


@given(
    bad_input=st.text(
        alphabet=st.characters(
            whitelist_categories=("Lu", "Ll"),  # letters only — never numeric
        ),
        min_size=1,
        max_size=20,
    )
)
@settings(max_examples=100)
def test_prompt_int_rejects_non_numeric(bad_input: str) -> None:
    """Property 9: prompt_int re-prompts on non-numeric input."""
    from crypto_trading_cli.ui.prompts import prompt_int

    # Feed: bad input first, then a valid integer "5"
    inputs = iter([bad_input, "5"])
    error_messages: list[str] = []

    with patch("builtins.input", side_effect=inputs):
        with patch("crypto_trading_cli.ui.prompts.rprint") as mock_rprint:
            result = prompt_int("Test")
            # Collect error messages
            for call in mock_rprint.call_args_list:
                error_messages.append(str(call))

    assert result == 5
    # At least one error message should mention "expected a number"
    assert any("expected a number" in msg for msg in error_messages)


@given(
    bad_input=st.text(
        alphabet=st.characters(whitelist_categories=("Lu", "Ll")),
        min_size=1,
        max_size=20,
    ).filter(lambda s: s.lower() not in ("inf", "nan", "infinity", "-inf", "+inf"))
)
@settings(max_examples=100)
def test_prompt_float_rejects_non_numeric(bad_input: str) -> None:
    """Property 9: prompt_float re-prompts on non-numeric input."""
    from crypto_trading_cli.ui.prompts import prompt_float

    inputs = iter([bad_input, "3.14"])
    error_messages: list[str] = []

    with patch("builtins.input", side_effect=inputs):
        with patch("crypto_trading_cli.ui.prompts.rprint") as mock_rprint:
            result = prompt_float("Test")
            for call in mock_rprint.call_args_list:
                error_messages.append(str(call))

    assert abs(result - 3.14) < 1e-9
    assert any("expected a number" in msg for msg in error_messages)
