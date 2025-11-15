# ============================================================
# ATR + VOLATILITY REGIME MODEL
# ============================================================

import numpy as np
import pandas as pd


def compute_atr(df, period=14):
    """Classic Wilder’s ATR calculation."""
    if df is None or len(df) < period + 1:
        return None

    high = df["High"]
    low = df["Low"]
    close = df["Close"]

    # True Range
    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()

    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

    atr = tr.rolling(period).mean()

    return float(atr.iloc[-1])


def compute_volatility_regime(df):
    """
    Uses ATR% and normalized ATR to classify volatility regime:
    - 0 = Low Volatility
    - 1 = Normal Volatility
    - 2 = High Volatility
    - 3 = Extreme Volatility
    """
    if df is None or len(df) < 20:
        return {
            "atr": 0,
            "atr_pct": 0,
            "vol_regime": 1
        }

    atr = compute_atr(df, period=14)

    last_price = float(df["Close"].iloc[-1])

    # ATR as % of price
    atr_pct = (atr / last_price) * 100 if last_price != 0 else 0

    # Regime classification thresholds
    if atr_pct < 1.2:
        regime = 0  # low vol
    elif atr_pct < 2.5:
        regime = 1  # normal vol
    elif atr_pct < 4.5:
        regime = 2  # high vol
    else:
        regime = 3  # extreme vol

    return {
        "atr": round(atr, 4),
        "atr_pct": round(atr_pct, 4),
        "vol_regime": regime
    }
