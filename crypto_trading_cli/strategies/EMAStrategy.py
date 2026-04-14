"""
EMA Crossover Strategy
======================
Buys when the short EMA crosses above the long EMA (golden cross) and sells
when it crosses below (death cross). Follows medium-to-long-term trends.

Parameters are passed via the Freqtrade config ``strategy_params`` key:
  - ema_short (int): short EMA period, must be > 0 and < ema_long (default 9)
  - ema_long  (int): long EMA period, must be > ema_short (default 21)
  - stop_loss (float): stop-loss fraction, must be negative (default -0.10)
  - timeframe (str):   candle timeframe (default "5m")
"""

import pandas as pd
import pandas_ta as pta
from freqtrade.strategy import IStrategy


class EMAStrategy(IStrategy):
    INTERFACE_VERSION = 3

    # Default parameters — overridden by strategy_params at runtime
    ema_short: int = 9
    ema_long: int = 21
    stoploss: float = -0.10
    minimal_roi = {"0": 100}
    timeframe = "5m"
    can_short = False
    startup_candle_count = 50   # ensure EMA(21) is stable from the start

    def bot_start(self, **kwargs) -> None:
        """Read user-supplied parameters from the Freqtrade config strategy_params dict."""
        p = self.config.get("strategy_params", {})
        if "ema_short" in p:
            self.ema_short = int(p["ema_short"])
        if "ema_long" in p:
            self.ema_long = int(p["ema_long"])
            # startup_candle_count must be at least 2× ema_long for stability
            self.startup_candle_count = max(50, self.ema_long * 2)
        if "stop_loss" in p:
            sl = float(p["stop_loss"])
            self.stoploss = sl if sl < 0 else -sl
        if "timeframe" in p:
            self.timeframe = p["timeframe"]

    def populate_indicators(self, dataframe: pd.DataFrame, metadata: dict) -> pd.DataFrame:
        dataframe["ema_short"] = pta.ema(dataframe["close"], length=self.ema_short)
        dataframe["ema_long"] = pta.ema(dataframe["close"], length=self.ema_long)
        return dataframe

    def populate_entry_trend(self, dataframe: pd.DataFrame, metadata: dict) -> pd.DataFrame:
        # Golden cross: short EMA crosses above long EMA
        dataframe.loc[
            (dataframe["ema_short"] > dataframe["ema_long"])
            & (dataframe["ema_short"].shift(1) <= dataframe["ema_long"].shift(1))
            & (dataframe["volume"] > 0),
            "enter_long",
        ] = 1
        return dataframe

    def populate_exit_trend(self, dataframe: pd.DataFrame, metadata: dict) -> pd.DataFrame:
        # Death cross: short EMA crosses below long EMA
        dataframe.loc[
            (dataframe["ema_short"] < dataframe["ema_long"])
            & (dataframe["ema_short"].shift(1) >= dataframe["ema_long"].shift(1))
            & (dataframe["volume"] > 0),
            "exit_long",
        ] = 1
        return dataframe
