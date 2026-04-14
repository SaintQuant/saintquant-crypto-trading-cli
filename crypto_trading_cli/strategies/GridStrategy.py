"""
Grid Strategy
=============
Buys near the lower bound of a rolling price range and sells near the upper bound.
Suitable for sideways / oscillating markets.

Parameters are passed via the Freqtrade config ``strategy_params`` key:
  - grid_spacing (float): grid interval as a percentage (default 1.0)
  - stop_loss    (float): stop-loss fraction, must be negative (default -0.05)
  - timeframe    (str):   candle timeframe (default "5m")
"""

import pandas as pd
import pandas_ta as pta
from freqtrade.strategy import IStrategy


class GridStrategy(IStrategy):
    INTERFACE_VERSION = 3

    # Default parameters — overridden by strategy_params at runtime
    grid_spacing: float = 1.0   # grid interval as a percentage
    stoploss: float = -0.05
    minimal_roi = {"0": 100}
    timeframe = "5m"
    can_short = False
    startup_candle_count = 50   # rolling(20) needs enough history

    def bot_start(self, **kwargs) -> None:
        """Read user-supplied parameters from the Freqtrade config strategy_params dict."""
        p = self.config.get("strategy_params", {})
        if "grid_spacing" in p:
            self.grid_spacing = float(p["grid_spacing"])
        if "stop_loss" in p:
            sl = float(p["stop_loss"])
            self.stoploss = sl if sl < 0 else -sl
        if "timeframe" in p:
            self.timeframe = p["timeframe"]

    def populate_indicators(self, dataframe: pd.DataFrame, metadata: dict) -> pd.DataFrame:
        close = dataframe["close"]
        dataframe["grid_upper"] = close.rolling(20).max()
        dataframe["grid_lower"] = close.rolling(20).min()
        dataframe["grid_mid"] = (dataframe["grid_upper"] + dataframe["grid_lower"]) / 2
        # ATR for filtering low-volatility periods
        dataframe["atr"] = pta.atr(
            dataframe["high"], dataframe["low"], dataframe["close"], length=14
        )
        return dataframe

    def populate_entry_trend(self, dataframe: pd.DataFrame, metadata: dict) -> pd.DataFrame:
        spacing = self.grid_spacing / 100
        dataframe.loc[
            (dataframe["close"] <= dataframe["grid_lower"] * (1 + spacing))
            & (dataframe["volume"] > 0)
            & (dataframe["grid_upper"].notna())
            & (dataframe["grid_lower"].notna()),
            "enter_long",
        ] = 1
        return dataframe

    def populate_exit_trend(self, dataframe: pd.DataFrame, metadata: dict) -> pd.DataFrame:
        spacing = self.grid_spacing / 100
        dataframe.loc[
            (dataframe["close"] >= dataframe["grid_upper"] * (1 - spacing))
            & (dataframe["volume"] > 0)
            & (dataframe["grid_upper"].notna()),
            "exit_long",
        ] = 1
        return dataframe
