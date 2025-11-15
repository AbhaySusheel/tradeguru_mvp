# backend/utils/market.py
import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

def fetch_intraday(symbol, period="1d", interval="5m"):
    """Return a DataFrame of intraday bars for symbol."""
    try:
        ticker = yf.Ticker(symbol)
        df = ticker.history(period=period, interval=interval, prepost=False)
        if df.empty:
            return None
        df = df.reset_index()
        return df
    except Exception as e:
        print("fetch_intraday error", symbol, e)
        return None


def compute_rsi(close, period=14):
    delta = close.diff().dropna()
    up = delta.clip(lower=0)
    down = -delta.clip(upper=0)

    ma_up = up.rolling(period).mean()
    ma_down = down.rolling(period).mean()

    rs = ma_up / (ma_down + 1e-9)
    rsi = 100 - (100 / (1 + rs))
    return rsi.iloc[-1] if not rsi.empty else 50


def compute_macd(close):
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    macd_line = ema12 - ema26
    signal = macd_line.ewm(span=9, adjust=False).mean()
    hist = macd_line - signal
    return float(macd_line.iloc[-1]), float(signal.iloc[-1]), float(hist.iloc[-1])


def compute_features(df):
    """Given DataFrame with Open, High, Low, Close, Volume, compute features."""
    if df is None or df.empty:
        return None

    close = df["Close"]
    vol = df["Volume"]

    # === Intraday Change ===
    intraday_pct = (close.iloc[-1] - df["Open"].iloc[0]) / df["Open"].iloc[0] * 100

    # === 5m short & long (same as before) ===
    ma_short = close.rolling(3).mean().iloc[-1]
    ma_long  = close.rolling(12).mean().iloc[-1]

    # === Volume Strength ===
    avg_vol = vol.mean() if vol.mean() > 0 else 1
    vol_ratio = vol.iloc[-1] / avg_vol

    # === RSI ===
    rsi = compute_rsi(close)

    # === MACD ===
    macd, macd_signal, macd_hist = compute_macd(close)
    macd_trend = 1 if macd > macd_signal else 0

    # === Volatility (standard deviation of returns) ===
    volatility = float(close.pct_change().rolling(10).std().iloc[-1] or 0)

    return {
        "intraday_pct": float(round(intraday_pct, 4)),
        "ma_short": float(ma_short),
        "ma_long": float(ma_long),
        "ma_diff": float(ma_short - ma_long),
        "vol_ratio": float(round(vol_ratio, 4)),
        "rsi": float(round(rsi, 2)),
        "macd": macd,
        "macd_signal": macd_signal,
        "macd_hist": macd_hist,
        "macd_trend": macd_trend,
        "volatility": volatility,
        "last_price": float(round(close.iloc[-1], 2))
    }
