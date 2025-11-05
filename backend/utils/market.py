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

def compute_features(df):
    """Given DataFrame with Open, High, Low, Close, Volume, compute features."""
    if df is None or df.empty:
        return None
    close = df['Close']
    vol = df['Volume']

    # intraday pct: last close vs first open
    intraday_pct = (close.iloc[-1] - df['Open'].iloc[0]) / df['Open'].iloc[0] * 100

    # MA short & long (on close)
    ma_short = close.rolling(3).mean().iloc[-1]   # e.g., 15m if interval=5m
    ma_long  = close.rolling(12).mean().iloc[-1]  # e.g., 60m

    # volume ratio: last bar volume vs average
    avg_vol = vol.mean() if vol.mean() > 0 else 1
    vol_ratio = vol.iloc[-1] / avg_vol

    # RSI (simple)
    delta = close.diff().dropna()
    up = delta.clip(lower=0).rolling(14).mean()
    down = -delta.clip(upper=0).rolling(14).mean()
    rsi = 100 - (100 / (1 + (up / (down + 1e-9))))
    rsi = rsi.iloc[-1] if not rsi.empty else 50

    return {
        "intraday_pct": float(round(intraday_pct, 4)),
        "ma_short": float(round(ma_short, 4)),
        "ma_long": float(round(ma_long, 4)),
        "ma_diff": float(round(ma_short - ma_long, 4)),
        "vol_ratio": float(round(vol_ratio, 4)),
        "rsi": float(round(rsi, 2)),
        "last_price": float(round(close.iloc[-1], 2))
    }
