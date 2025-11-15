# backend/utils/market.py
import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from utils.volume_utils import compute_volume_features, compute_volume_signal


# -----------------------
# Config
SR_LOOKBACK = 75      # number of candles to analyze for advanced S/R
CLUSTER_TOLERANCE = 0.01  # 1% clustering tolerance
MIN_SWING_SEPARATION = 2  # minimal index separation to consider distinct swings
# -----------------------

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
    return float(rsi.iloc[-1]) if not rsi.empty else 50.0

def compute_macd(close):
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    macd_line = ema12 - ema26
    signal = macd_line.ewm(span=9, adjust=False).mean()
    hist = macd_line - signal
    return float(macd_line.iloc[-1]), float(signal.iloc[-1]), float(hist.iloc[-1])

# -----------------------
# Advanced S/R helpers
# -----------------------
def find_swings(series):
    """Return indices of local swing highs and lows (simple 3-point method)."""
    highs = []
    lows = []
    n = len(series)
    if n < 3:
        return highs, lows
    vals = series.values
    for i in range(1, n-1):
        if vals[i] > vals[i-1] and vals[i] > vals[i+1]:
            highs.append(i)
        elif vals[i] < vals[i-1] and vals[i] < vals[i+1]:
            lows.append(i)
    # Optional: enforce minimal separation (dedupe very close swings)
    highs = _filter_close_indices(highs, MIN_SWING_SEPARATION)
    lows = _filter_close_indices(lows, MIN_SWING_SEPARATION)
    return highs, lows

def _filter_close_indices(indices, min_sep):
    if not indices:
        return []
    filtered = [indices[0]]
    for idx in indices[1:]:
        if idx - filtered[-1] >= min_sep:
            filtered.append(idx)
    return filtered

def cluster_levels(prices, tol=CLUSTER_TOLERANCE):
    """
    Cluster price levels into zones using a tolerance band (pct).
    Returns list of clusters as dicts { 'center': float, 'members': [prices], 'count': int } ordered by count desc.
    """
    if not prices:
        return []
    arr = np.array(sorted(prices))
    clusters = []
    current = [arr[0]]
    for p in arr[1:]:
        if abs(p - np.mean(current)) <= tol * np.mean(current):
            current.append(p)
        else:
            clusters.append(current)
            current = [p]
    clusters.append(current)
    # build cluster descriptors
    cluster_info = []
    for c in clusters:
        cluster_info.append({
            "center": float(np.mean(c)),
            "count": len(c),
            "members": [float(x) for x in c]
        })
    # sort by count descending, then by center
    cluster_info.sort(key=lambda x: (-x["count"], x["center"]))
    return cluster_info

def compute_volume_zscore(vol_series):
    v = np.array(vol_series)
    if len(v) < 2:
        return np.zeros_like(v)
    mu = v.mean()
    sd = v.std() if v.std() > 0 else 1.0
    return (v - mu) / sd

def compute_sr_zones(df):
    """
    Given a DataFrame (with High, Low, Close, Volume), compute advanced S/R zones.
    Returns:
      support_zones: list of dicts {center, count, strength}
      resistance_zones: same
    """
    n = min(len(df), SR_LOOKBACK)
    recent = df.tail(n).copy().reset_index(drop=True)
    close = recent['Close']
    high = recent['High']
    low = recent['Low']
    vol = recent['Volume']

    # find swing points on close
    high_ids, low_ids = find_swings(close)

    # collect swing prices and associated volumes (use High for highs, Low for lows)
    swing_high_prices = [float(high.iloc[i]) for i in high_ids]
    swing_high_vols = [float(vol.iloc[i]) for i in high_ids]
    swing_low_prices = [float(low.iloc[i]) for i in low_ids]
    swing_low_vols = [float(vol.iloc[i]) for i in low_ids]

    # cluster swing points to identify zones
    resistance_clusters = cluster_levels(swing_high_prices, tol=CLUSTER_TOLERANCE)
    support_clusters = cluster_levels(swing_low_prices, tol=CLUSTER_TOLERANCE)

    # compute volume-weighted strength for clusters
    # map each swing member to its vol zscore
    vol_z = compute_volume_zscore(vol)
    def cluster_strength(cluster, swing_prices, swing_vols):
        # for each member price in cluster, find matching swings from swing_prices (approx)
        members = []
        strength = 0.0
        count = 0
        center = cluster['center']
        for p, v in zip(swing_prices, swing_vols):
            if abs(p - center) <= CLUSTER_TOLERANCE * center:
                count += 1
                strength += v
                members.append(p)
        # strength normalized by count and recent avg vol
        return {
            "center": float(center),
            "count": count,
            "raw_strength": float(strength),
            "members": members
        }

    res_zones = [cluster_strength(c, swing_high_prices, swing_high_vols) for c in resistance_clusters]
    sup_zones = [cluster_strength(c, swing_low_prices, swing_low_vols) for c in support_clusters]

    # normalize strengths (avoid zero division)
    all_strengths = [z["raw_strength"] for z in res_zones + sup_zones if z["raw_strength"] > 0]
    if all_strengths:
        max_s = max(all_strengths)
    else:
        max_s = 1.0

    # assign normalized strength score [0..1]
    def normalize_zone(z):
        z['strength'] = float(z['raw_strength'] / (max_s + 1e-9))
        return z

    res_zones = [normalize_zone(z) for z in res_zones]
    sup_zones = [normalize_zone(z) for z in sup_zones]

    return sup_zones, res_zones

def compute_breakout_bounce_scores(last_price, support_zones, resistance_zones, recent_close, rsi):
    """
    Compute breakout_score (0..1) and bounce_score (0..1) using zones and recent price action.
    - breakout_score high when price clears resistance with volume/confirmation.
    - bounce_score high when price bounces off support with momentum.
    """
    breakout_score = 0.0
    bounce_score = 0.0

    # Resistance breakout: check strongest resistance zone
    if resistance_zones:
        strongest_res = resistance_zones[0]['center']
        # breakout if price above zone
        if last_price > strongest_res * 1.01:  # 1% clear
            breakout_score = 1.0
        elif last_price > strongest_res:
            breakout_score = 0.6
        else:
            # price close to resistance but not broken
            breakout_score = 0.0

    # Support bounce: check strongest support zone
    if support_zones:
        strongest_sup = support_zones[0]['center']
        # if price is within 1% above support and RSI increasing, mark bounce
        if strongest_sup <= last_price <= strongest_sup * 1.01:
            # if RSI < 60 and rising (we don't have slope here — use RSI threshold)
            bounce_score = 0.8 if rsi < 60 else 0.5
        elif strongest_sup * 0.99 <= last_price < strongest_sup:
            # just below support (rare) — weak
            bounce_score = 0.2

    # combine zone strength as multiplier (if zones carry strong strength)
    if resistance_zones:
        res_strength = resistance_zones[0].get('strength', 0.0)
        breakout_score *= (0.5 + 0.5 * res_strength)  # between 0.5..1.0 multiplier
    if support_zones:
        sup_strength = support_zones[0].get('strength', 0.0)
        bounce_score *= (0.5 + 0.5 * sup_strength)

    # clip
    breakout_score = float(min(max(breakout_score, 0.0), 1.0))
    bounce_score = float(min(max(bounce_score, 0.0), 1.0))

    # sr_score is combination: breakout favored more
    sr_score = float(round(0.65 * breakout_score + 0.35 * bounce_score, 4))
    return breakout_score, bounce_score, sr_score

# -----------------------
# Main feature computation
# -----------------------
def compute_features(df):
    """Given DataFrame with Open, High, Low, Close, Volume, compute features."""
    if df is None or df.empty:
        return None

    # Ensure numeric cols exist
    for col in ['Open', 'High', 'Low', 'Close', 'Volume']:
        if col not in df.columns:
            return None

    close = df["Close"]
    vol = df["Volume"]

    # === Intraday Change ===
    intraday_pct = (close.iloc[-1] - df["Open"].iloc[0]) / df["Open"].iloc[0] * 100

    # === 5m short & long (same as before) ===
    ma_short = close.rolling(3).mean().iloc[-1] if len(close) >= 3 else float(close.iloc[-1])
    ma_long  = close.rolling(12).mean().iloc[-1] if len(close) >= 12 else float(close.iloc[-1])

    # ============================================================
    # === ADVANCED VOLUME MODEL (Option B – ML Optimized)
    # ============================================================
    vol_features = compute_volume_features(vol)
    vol_signal = compute_volume_signal(vol_features)

    # Extract for convenience (still keep your old fields for compatibility)
    vol_mean_20  = vol_features["vol_mean_20"]
    vol_std_20   = vol_features["vol_std_20"]
    vol_zscore   = vol_features["vol_zscore"]
    vol_surge    = vol_features["vol_surge"]
    vol_trend_5  = vol_features["vol_trend_5"]
    vol_trend_20 = vol_features["vol_trend_20"]
    vol_spike_ratio = vol_features["vol_spike_ratio"]

    vol_now = float(vol.iloc[-1])
    vol_ratio = vol_now / (vol.mean() + 1e-9)
    vol_strength = vol_now / (vol_mean_20 + 1e-9)

    # === RSI ===
    rsi = compute_rsi(close)

    # === MACD ===
    macd, macd_signal, macd_hist = compute_macd(close)
    macd_trend = 1 if macd > macd_signal else 0

    # === Volatility (standard deviation of returns) ===
    volatility = float(close.pct_change().rolling(10).std().iloc[-1] or 0)

    # === Advanced S/R (uses last SR_LOOKBACK candles) ===
    sup_zones, res_zones = compute_sr_zones(df)

    last_price = float(close.iloc[-1])
    breakout_score, bounce_score, sr_score = compute_breakout_bounce_scores(
        last_price, sup_zones, res_zones, close.tail(10), rsi
    )

    # ============================================================
    # RETURN FINAL FEATURE DICT
    # ============================================================
    return {
        "intraday_pct": float(round(intraday_pct, 4)),
        "ma_short": float(ma_short),
        "ma_long": float(ma_long),
        "ma_diff": float(ma_short - ma_long),

        # === Old + New Volume Features ===
        "vol_ratio": float(round(vol_ratio, 4)),
        "vol_strength": float(round(vol_strength, 4)),
        "vol_20_mean": vol_mean_20,
        "vol_20_std": vol_std_20,
        "vol_zscore": vol_zscore,
        "vol_surge": vol_surge,               # 1 = abnormal volume
        "vol_trend_5": vol_trend_5,           # short-term volume trend
        "vol_trend_20": vol_trend_20,         # long-term volume trend
        "vol_spike_ratio": vol_spike_ratio,   # 1 = highest in 20 bars
        "vol_signal": vol_signal,             # final ML volume signal (0–1)

        # === Momentum Indicators ===
        "rsi": float(round(rsi, 2)),
        "macd": macd,
        "macd_signal": macd_signal,
        "macd_hist": macd_hist,
        "macd_trend": macd_trend,
        "volatility": volatility,

        # === S/R ===
        "sr_support_zones": sup_zones,
        "sr_resistance_zones": res_zones,
        "breakout_score": breakout_score,
        "bounce_score": bounce_score,
        "sr_score": sr_score,

        "last_price": float(round(last_price, 2))
    }
