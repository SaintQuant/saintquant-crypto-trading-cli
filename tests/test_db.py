"""
Tests for crypto_trading_cli.db

Property 8: Bot DB round-trip preserves all fields
  - insert_bot(record) then get_bot(id) returns a record with identical values
"""

import tempfile
import uuid
from datetime import datetime, timezone

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

import crypto_trading_cli.db as db_module
from crypto_trading_cli.db import (
    BotRecord,
    delete_bot,
    get_bot,
    init_db,
    insert_bot,
    list_bots,
    list_bots_by_status,
    update_bot_port,
    update_bot_status,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def tmp_db(tmp_path):
    """Provide a fresh temporary database for each test."""
    db_path = str(tmp_path / "test_bots.db")
    init_db(db_path)
    yield db_path
    # Cleanup is handled by tmp_path fixture


def _make_record(**overrides) -> BotRecord:
    """Create a minimal valid BotRecord for testing."""
    defaults = dict(
        id=str(uuid.uuid4()),
        exchange="binance",
        strategy="grid",
        status="stopped",
        config_json='{"pair": "BTC/USDT"}',
        enc_api_key="enc_key_abc",
        enc_secret="enc_secret_xyz",
        enc_ft_password="enc_ft_pass",
        dry_run=True,
        sandbox=False,
        enc_passphrase=None,
        port=None,
        error_msg=None,
        created_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )
    defaults.update(overrides)
    return BotRecord(**defaults)


# ---------------------------------------------------------------------------
# Property 8: DB round-trip preserves all fields
# ---------------------------------------------------------------------------

_text = st.text(min_size=1, max_size=64, alphabet=st.characters(whitelist_categories=("Lu", "Ll", "Nd")))
_opt_text = st.one_of(st.none(), _text)
_opt_int = st.one_of(st.none(), st.integers(min_value=1024, max_value=65535))


@given(
    exchange=st.sampled_from(["binance", "okx", "kraken", "bybit", "coinbaseadvanced", "bitget"]),
    strategy=st.sampled_from(["grid", "rsi", "ema"]),
    status=st.sampled_from(["stopped", "running", "error"]),
    enc_api_key=_text,
    enc_secret=_text,
    enc_passphrase=_opt_text,
    enc_ft_password=_text,
    dry_run=st.booleans(),
    sandbox=st.booleans(),
    port=_opt_int,
    error_msg=_opt_text,
)
@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_db_roundtrip_preserves_all_fields(
    tmp_db,
    exchange,
    strategy,
    status,
    enc_api_key,
    enc_secret,
    enc_passphrase,
    enc_ft_password,
    dry_run,
    sandbox,
    port,
    error_msg,
) -> None:
    """Property 8: insert then get returns identical field values."""
    record = _make_record(
        exchange=exchange,
        strategy=strategy,
        status=status,
        enc_api_key=enc_api_key,
        enc_secret=enc_secret,
        enc_passphrase=enc_passphrase,
        enc_ft_password=enc_ft_password,
        dry_run=dry_run,
        sandbox=sandbox,
        port=port,
        error_msg=error_msg,
    )
    insert_bot(record)
    retrieved = get_bot(record.id)

    assert retrieved is not None
    assert retrieved.id == record.id
    assert retrieved.exchange == record.exchange
    assert retrieved.strategy == record.strategy
    assert retrieved.status == record.status
    assert retrieved.config_json == record.config_json
    assert retrieved.enc_api_key == record.enc_api_key
    assert retrieved.enc_secret == record.enc_secret
    assert retrieved.enc_passphrase == record.enc_passphrase
    assert retrieved.enc_ft_password == record.enc_ft_password
    assert retrieved.dry_run == record.dry_run
    assert retrieved.sandbox == record.sandbox
    assert retrieved.port == record.port
    assert retrieved.error_msg == record.error_msg


# ---------------------------------------------------------------------------
# Example-based CRUD tests
# ---------------------------------------------------------------------------


def test_get_bot_returns_none_for_unknown_id(tmp_db) -> None:
    assert get_bot("nonexistent-id") is None


def test_insert_and_get(tmp_db) -> None:
    rec = _make_record()
    insert_bot(rec)
    result = get_bot(rec.id)
    assert result is not None
    assert result.id == rec.id


def test_update_bot_status(tmp_db) -> None:
    rec = _make_record(status="stopped")
    insert_bot(rec)
    update_bot_status(rec.id, "running")
    assert get_bot(rec.id).status == "running"


def test_update_bot_status_with_error_msg(tmp_db) -> None:
    rec = _make_record(status="stopped")
    insert_bot(rec)
    update_bot_status(rec.id, "error", error_msg="process exited with code 1")
    result = get_bot(rec.id)
    assert result.status == "error"
    assert result.error_msg == "process exited with code 1"


def test_update_bot_port(tmp_db) -> None:
    rec = _make_record(port=None)
    insert_bot(rec)
    update_bot_port(rec.id, 38291)
    assert get_bot(rec.id).port == 38291


def test_delete_bot(tmp_db) -> None:
    rec = _make_record()
    insert_bot(rec)
    delete_bot(rec.id)
    assert get_bot(rec.id) is None


def test_list_bots_empty(tmp_db) -> None:
    assert list_bots() == []


def test_list_bots_returns_all(tmp_db) -> None:
    recs = [_make_record() for _ in range(3)]
    for r in recs:
        insert_bot(r)
    results = list_bots()
    assert len(results) == 3


def test_list_bots_by_status(tmp_db) -> None:
    running = _make_record(status="running")
    stopped = _make_record(status="stopped")
    insert_bot(running)
    insert_bot(stopped)
    assert len(list_bots_by_status("running")) == 1
    assert len(list_bots_by_status("stopped")) == 1
    assert len(list_bots_by_status("error")) == 0


def test_okx_passphrase_stored_and_retrieved(tmp_db) -> None:
    rec = _make_record(exchange="okx", enc_passphrase="enc_passphrase_value")
    insert_bot(rec)
    result = get_bot(rec.id)
    assert result.enc_passphrase == "enc_passphrase_value"
