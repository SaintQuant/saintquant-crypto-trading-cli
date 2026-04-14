"""
Tests for crypto_trading_cli.validators

Property 3: Strategy parameter validation rejects all invalid inputs
  - Any parameter set violating a constraint must raise ValueError
  - Valid boundary values must not raise
"""

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from crypto_trading_cli.validators import EMAParams, GridParams, RSIParams, validate_params


# ---------------------------------------------------------------------------
# Property 3: GridParams — invalid inputs raise ValueError
# ---------------------------------------------------------------------------


@given(grid_count=st.integers(max_value=0))
@settings(max_examples=100)
def test_grid_count_must_be_positive(grid_count: int) -> None:
    with pytest.raises(ValueError, match="grid_count"):
        GridParams(
            pair="BTC/USDT",
            grid_count=grid_count,
            grid_spacing=1.0,
            invest_amount=100.0,
            stop_loss=-0.05,
        )


@given(grid_spacing=st.floats(max_value=0.0, allow_nan=False, allow_infinity=False))
@settings(max_examples=100)
def test_grid_spacing_must_be_positive(grid_spacing: float) -> None:
    with pytest.raises(ValueError, match="grid_spacing"):
        GridParams(
            pair="BTC/USDT",
            grid_count=5,
            grid_spacing=grid_spacing,
            invest_amount=100.0,
            stop_loss=-0.05,
        )


@given(invest_amount=st.floats(max_value=0.0, allow_nan=False, allow_infinity=False))
@settings(max_examples=100)
def test_grid_invest_amount_must_be_positive(invest_amount: float) -> None:
    with pytest.raises(ValueError, match="invest_amount"):
        GridParams(
            pair="BTC/USDT",
            grid_count=5,
            grid_spacing=1.0,
            invest_amount=invest_amount,
            stop_loss=-0.05,
        )


@given(stop_loss=st.floats(min_value=0.0, allow_nan=False, allow_infinity=False))
@settings(max_examples=100)
def test_grid_stop_loss_must_be_negative(stop_loss: float) -> None:
    with pytest.raises(ValueError, match="stop_loss"):
        GridParams(
            pair="BTC/USDT",
            grid_count=5,
            grid_spacing=1.0,
            invest_amount=100.0,
            stop_loss=stop_loss,
        )


# ---------------------------------------------------------------------------
# Property 3: RSIParams — invalid inputs raise ValueError
# ---------------------------------------------------------------------------


@given(rsi_buy=st.integers().filter(lambda x: not (0 <= x <= 100)))
@settings(max_examples=100)
def test_rsi_buy_out_of_range(rsi_buy: int) -> None:
    with pytest.raises(ValueError, match="rsi_buy"):
        RSIParams(timeframe="5m", rsi_buy=rsi_buy, rsi_sell=70, stop_loss=-0.05)


@given(rsi_sell=st.integers().filter(lambda x: not (0 <= x <= 100)))
@settings(max_examples=100)
def test_rsi_sell_out_of_range(rsi_sell: int) -> None:
    with pytest.raises(ValueError, match="rsi_sell"):
        RSIParams(timeframe="5m", rsi_buy=30, rsi_sell=rsi_sell, stop_loss=-0.05)


@given(
    rsi_buy=st.integers(min_value=0, max_value=100),
    rsi_sell=st.integers(min_value=0, max_value=100),
)
@settings(max_examples=200)
def test_rsi_buy_must_be_less_than_sell(rsi_buy: int, rsi_sell: int) -> None:
    if rsi_buy >= rsi_sell:
        with pytest.raises(ValueError):
            RSIParams(timeframe="5m", rsi_buy=rsi_buy, rsi_sell=rsi_sell, stop_loss=-0.05)


@given(stop_loss=st.floats(min_value=0.0, allow_nan=False, allow_infinity=False))
@settings(max_examples=100)
def test_rsi_stop_loss_must_be_negative(stop_loss: float) -> None:
    with pytest.raises(ValueError, match="stop_loss"):
        RSIParams(timeframe="5m", rsi_buy=30, rsi_sell=70, stop_loss=stop_loss)


# ---------------------------------------------------------------------------
# Property 3: EMAParams — invalid inputs raise ValueError
# ---------------------------------------------------------------------------


@given(ema_short=st.integers(max_value=0))
@settings(max_examples=100)
def test_ema_short_must_be_positive(ema_short: int) -> None:
    with pytest.raises(ValueError, match="ema_short"):
        EMAParams(ema_short=ema_short, ema_long=21, timeframe="5m")


@given(ema_long=st.integers(max_value=0))
@settings(max_examples=100)
def test_ema_long_must_be_positive(ema_long: int) -> None:
    with pytest.raises(ValueError, match="ema_long"):
        EMAParams(ema_short=9, ema_long=ema_long, timeframe="5m")


@given(
    ema_short=st.integers(min_value=1, max_value=200),
    ema_long=st.integers(min_value=1, max_value=200),
)
@settings(max_examples=200)
def test_ema_short_must_be_less_than_long(ema_short: int, ema_long: int) -> None:
    if ema_short >= ema_long:
        with pytest.raises(ValueError):
            EMAParams(ema_short=ema_short, ema_long=ema_long, timeframe="5m")


# ---------------------------------------------------------------------------
# Example-based: valid boundary values must not raise
# ---------------------------------------------------------------------------


def test_grid_valid_minimum_values() -> None:
    p = GridParams(pair="BTC/USDT", grid_count=1, grid_spacing=0.001, invest_amount=0.001, stop_loss=-0.001)
    assert p.grid_count == 1


def test_rsi_valid_boundary() -> None:
    p = RSIParams(timeframe="1m", rsi_buy=0, rsi_sell=1, stop_loss=-0.001)
    assert p.rsi_buy == 0
    assert p.rsi_sell == 1


def test_ema_valid_boundary() -> None:
    p = EMAParams(ema_short=1, ema_long=2, timeframe="1m")
    assert p.ema_short == 1


def test_validate_params_unknown_strategy_raises() -> None:
    with pytest.raises(ValueError, match="Unknown strategy"):
        validate_params("unknown", {})


def test_validate_params_grid_valid() -> None:
    validate_params(
        "grid",
        {"pair": "ETH/USDT", "grid_count": 10, "grid_spacing": 0.5, "invest_amount": 50.0, "stop_loss": -0.05},
    )


def test_validate_params_rsi_valid() -> None:
    validate_params("rsi", {"timeframe": "15m", "rsi_buy": 25, "rsi_sell": 75, "stop_loss": -0.08})


def test_validate_params_ema_valid() -> None:
    validate_params("ema", {"ema_short": 9, "ema_long": 21, "timeframe": "1h"})
