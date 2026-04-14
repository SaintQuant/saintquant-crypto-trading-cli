"""
RSI Strategy
============
Buys when RSI is oversold (below rsi_buy threshold) and sells when overbought
(above rsi_sell threshold). Captures mean-reversion moves.

Parameters are passed via the Freqtrade config ``strategy_params`` key:
  - rsi_buy   (int):   RSI buy threshold, 0–100 (default 30)
  - rsi_sell  (int):   RSI sell threshold, 0–100, must be > rsi_buy (default 70)
  - stop_loss (float): stop-loss fraction, must be negative (default -0.10)
  - timeframe (str):   candle timeframe (default "5m")
"""

import pandas as pd
import pandas_ta as pta
from freqtrade.strategy import IStrategy


class RSIStrategy(IStrategy):
    INTERFACE_VERSION = 3

    # Default parameters — overridden by strategy_params at runtime
    rsi_buy: int = 30
    rsi_sell: int = 70
    stoploss: float = -0.10
    minimal_roi = {"0": 100}
    timeframe = "5m"
    can_short = False
    startup_candle_count = 30   # RSI(14) needs at least 14 candles; 30 for stability

    def bot_start(self, **kwargs) -> None:
        """Read user-supplied parameters from the Freqtrade config strategy_params dict."""
        p = self.config.get("strategy_params", {})
        if "rsi_buy" in p:
            self.rsi_buy = int(p["rsi_buy"])
        if "rsi_sell" in p:
            self.rsi_sell = int(p["rsi_sell"])
        if "stop_loss" in p:
            sl = float(p["stop_loss"])
            self.stoploss = sl if sl < 0 else -sl
        if "timeframe" in p:
            self.timeframe = p["timeframe"]

    def populate_indicators(self, dataframe: pd.DataFrame, metadata: dict) -> pd.DataFrame:
        dataframe["rsi"] = pta.rsi(dataframe["close"], length=14)
        return dataframe

    def populate_entry_trend(self, dataframe: pd.DataFrame, metadata: dict) -> pd.DataFrame:
        dataframe.loc[
            (dataframe["rsi"] < self.rsi_buy) & (dataframe["volume"] > 0),
            "enter_long",
        ] = 1
        return dataframe

    def populate_exit_trend(self, dataframe: pd.DataFrame, metadata: dict) -> pd.DataFrame:
        dataframe.loc[
            (dataframe["rsi"] > self.rsi_sell) & (dataframe["volume"] > 0),
            "exit_long",
        ] = 1
        return dataframe
