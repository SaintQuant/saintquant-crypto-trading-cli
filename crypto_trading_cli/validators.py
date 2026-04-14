"""
Strategy parameter validation.

Validates the params dict passed to build_freqtrade_config / BotManager.start().
All strategy-specific and common params are checked here.
"""

from dataclasses import dataclass, field
from typing import Any


def _check_common(params: dict) -> None:
    """Validate common parameters shared by all strategies."""
    invest = params.get("invest_amount")
    if invest is not None and invest != "unlimited":
        if float(invest) <= 0:
            raise ValueError("invest_amount must be > 0")

    max_trades = params.get("max_open_trades")
    if max_trades is not None and int(max_trades) < -1:
        raise ValueError("max_open_trades must be >= -1 (-1 = unlimited)")

    stop_loss = params.get("stop_loss")
    if stop_loss is not None and float(stop_loss) >= 0:
        raise ValueError("stop_loss must be a negative number (e.g. -0.05 for -5%)")

    order_type = params.get("order_type")
    if order_type is not None and order_type not in ("market", "limit"):
        raise ValueError("order_type must be 'market' or 'limit'")

    pair = params.get("pair")
    if pair is not None and (not pair or "/" not in pair):
        raise ValueError("pair must be in format BASE/QUOTE (e.g. BTC/USDT)")


@dataclass
class GridParams:
    pair: str
    grid_spacing: float
    stop_loss: float
    timeframe: str = "5m"
    order_type: str = "market"
    invest_amount: float = 100.0
    max_open_trades: int = 3

    def __post_init__(self) -> None:
        if not self.pair or "/" not in self.pair:
            raise ValueError("pair must be in format BASE/QUOTE (e.g. BTC/USDT)")
        if self.grid_spacing <= 0:
            raise ValueError("grid_spacing must be > 0")
        if self.invest_amount <= 0:
            raise ValueError("invest_amount must be > 0")
        if self.stop_loss >= 0:
            raise ValueError("stop_loss must be negative (e.g. -0.05)")
        if self.order_type not in ("market", "limit"):
            raise ValueError("order_type must be 'market' or 'limit'")


@dataclass
class RSIParams:
    pair: str
    rsi_buy: int
    rsi_sell: int
    stop_loss: float
    timeframe: str = "5m"
    order_type: str = "market"
    invest_amount: float = 100.0
    max_open_trades: int = 3

    def __post_init__(self) -> None:
        if not self.pair or "/" not in self.pair:
            raise ValueError("pair must be in format BASE/QUOTE (e.g. BTC/USDT)")
        if not (0 <= self.rsi_buy <= 100):
            raise ValueError("rsi_buy must be between 0 and 100")
        if not (0 <= self.rsi_sell <= 100):
            raise ValueError("rsi_sell must be between 0 and 100")
        if self.rsi_buy >= self.rsi_sell:
            raise ValueError("rsi_buy must be less than rsi_sell")
        if self.stop_loss >= 0:
            raise ValueError("stop_loss must be negative (e.g. -0.05)")
        if self.order_type not in ("market", "limit"):
            raise ValueError("order_type must be 'market' or 'limit'")


@dataclass
class EMAParams:
    pair: str
    ema_short: int
    ema_long: int
    stop_loss: float
    timeframe: str = "5m"
    order_type: str = "market"
    invest_amount: float = 100.0
    max_open_trades: int = 3

    def __post_init__(self) -> None:
        if not self.pair or "/" not in self.pair:
            raise ValueError("pair must be in format BASE/QUOTE (e.g. BTC/USDT)")
        if self.ema_short <= 0:
            raise ValueError("ema_short must be > 0")
        if self.ema_long <= 0:
            raise ValueError("ema_long must be > 0")
        if self.ema_short >= self.ema_long:
            raise ValueError("ema_short must be less than ema_long")
        if self.stop_loss >= 0:
            raise ValueError("stop_loss must be negative (e.g. -0.05)")
        if self.order_type not in ("market", "limit"):
            raise ValueError("order_type must be 'market' or 'limit'")


def validate_params(strategy: str, params: dict) -> None:
    """
    Validate params for the given strategy.

    Raises:
        ValueError: with a descriptive message if any constraint is violated.
    """
    strategy = strategy.lower()
    # Extract only the fields each dataclass knows about to avoid TypeError
    if strategy == "grid":
        GridParams(
            pair=params.get("pair", ""),
            grid_spacing=float(params.get("grid_spacing", 0)),
            stop_loss=float(params.get("stop_loss", -0.05)),
            timeframe=params.get("timeframe", "5m"),
            order_type=params.get("order_type", "market"),
            invest_amount=float(params.get("invest_amount", 100.0)),
            max_open_trades=int(params.get("max_open_trades", 3)),
        )
    elif strategy == "rsi":
        RSIParams(
            pair=params.get("pair", ""),
            rsi_buy=int(params.get("rsi_buy", 30)),
            rsi_sell=int(params.get("rsi_sell", 70)),
            stop_loss=float(params.get("stop_loss", -0.05)),
            timeframe=params.get("timeframe", "5m"),
            order_type=params.get("order_type", "market"),
            invest_amount=float(params.get("invest_amount", 100.0)),
            max_open_trades=int(params.get("max_open_trades", 3)),
        )
    elif strategy == "ema":
        EMAParams(
            pair=params.get("pair", ""),
            ema_short=int(params.get("ema_short", 9)),
            ema_long=int(params.get("ema_long", 21)),
            stop_loss=float(params.get("stop_loss", -0.05)),
            timeframe=params.get("timeframe", "5m"),
            order_type=params.get("order_type", "market"),
            invest_amount=float(params.get("invest_amount", 100.0)),
            max_open_trades=int(params.get("max_open_trades", 3)),
        )
    else:
        raise ValueError(f"Unknown strategy: '{strategy}'. Supported: grid, rsi, ema")
