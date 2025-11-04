import pandas as pd
import numpy as np

# --- Helper Functions ---

def ema(series: pd.Series, span: int):
    """Calculate Exponential Moving Average."""
    return series.ewm(span=span, adjust=False).mean()

def rsi(series: pd.Series, period: int = 14):
    """Calculate Relative Strength Index (RSI)."""
    delta = series.diff()
    up = delta.clip(lower=0)
    down = -1 * delta.clip(upper=0)
    ma_up = up.rolling(window=period).mean()
    ma_down = down.rolling(window=period).mean()
    rs = ma_up / (ma_down + 1e-9)
    return 100 - (100 / (1 + rs))

def atr(df: pd.DataFrame, period: int = 14):
    """Calculate Average True Range (ATR)."""
    high = df['High']
    low = df['Low']
    close = df['Close']
    tr1 = high - low
    tr2 = (high - close.shift()).abs()
    tr3 = (low - close.shift()).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    return tr.rolling(period).mean()

def safe_float(val):
    """Safely convert to float (handles scalar or single-element Series)."""
    if isinstance(val, pd.Series):
        return float(val.iloc[0])
    return float(val)

# --- Main Signal Generation Function ---

def generate_signals(df: pd.DataFrame):
    """Generate trading signals based on EMA, RSI, ATR, and Volume."""
    if df is None or df.empty:
        return []

    df = df.copy()
    close = df['Close']

    # Calculate indicators
    df['EMA5'] = ema(close, span=5)
    df['EMA20'] = ema(close, span=20)
    df['RSI14'] = rsi(close, period=14)
    df['ATR14'] = atr(df, period=14)
    df['VolAvg20'] = df['Volume'].rolling(20).mean()

    # Ensure sufficient data points
    if len(df) < 2:
        return []

    signals = []
    last = df.iloc[-1]
    prev = df.iloc[-2]

    # Convert safely
    ema5_prev = safe_float(prev['EMA5'])
    ema20_prev = safe_float(prev['EMA20'])
    ema5_last = safe_float(last['EMA5'])
    ema20_last = safe_float(last['EMA20'])

    # --- EMA Crossover Signals ---
    if (ema5_prev <= ema20_prev) and (ema5_last > ema20_last):
        entry = safe_float(last['Close'])
        sl = entry - safe_float(last['ATR14'])
        tgt = entry + 2 * safe_float(last['ATR14'])
        signals.append({
            'type': 'BUY',
            'reason': 'EMA5 crosses above EMA20',
            'entry': entry, 'sl': sl, 'target': tgt, 'confidence': 0.7
        })

    elif (ema5_prev >= ema20_prev) and (ema5_last < ema20_last):
        entry = safe_float(last['Close'])
        sl = entry + safe_float(last['ATR14'])
        tgt = entry - 2 * safe_float(last['ATR14'])
        signals.append({
            'type': 'SELL',
            'reason': 'EMA5 crosses below EMA20',
            'entry': entry, 'sl': sl, 'target': tgt, 'confidence': 0.7
        })

    # --- RSI & Volume Signals ---
    if (safe_float(last['RSI14']) < 35) and (safe_float(last['Volume']) > 1.5 * safe_float(last['VolAvg20'])):
        entry = safe_float(last['Close'])
        sl = entry - safe_float(last['ATR14'])
        tgt = entry + 1.8 * safe_float(last['ATR14'])
        signals.append({
            'type': 'BUY',
            'reason': 'RSI low + volume spike',
            'entry': entry, 'sl': sl, 'target': tgt, 'confidence': 0.75
        })

    if safe_float(last['RSI14']) > 70:
        entry = safe_float(last['Close'])
        sl = entry + safe_float(last['ATR14'])
        tgt = entry - 1.8 * safe_float(last['ATR14'])
        signals.append({
            'type': 'SELL',
            'reason': 'RSI high',
            'entry': entry, 'sl': sl, 'target': tgt, 'confidence': 0.6
        })

    # --- Keep only strongest signal per type ---
    final = {}
    for s in signals:
        t = s['type']
        if t not in final or s['confidence'] > final[t]['confidence']:
            final[t] = s

    return list(final.values())
