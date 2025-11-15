# backend/utils/score.py
import math

def normalize(x, minv, maxv):
    if maxv == minv:
        return 0.5
    return (x - minv) / (maxv - minv)

def score_from_features(features_list):
    """
    Compute weighted score for each stock including buy_confidence.
    Tuned weights to balance momentum, volume, volatility, SR, and buy_confidence.
    """
    if not features_list:
        return []

    # Extract feature lists for normalization
    intraday_vals     = [f.get("intraday_pct", 0.0) for f in features_list]
    vol_strength_vals = [f.get("vol_strength", 0.0) for f in features_list]
    vol_z_vals        = [f.get("vol_zscore", 0.0) for f in features_list]
    volatilities      = [f.get("volatility", 0.0) for f in features_list]
    sr_vals           = [f.get("sr_score", 0.0) for f in features_list]
    buy_conf_vals     = [f.get("buy_confidence", 0.5) for f in features_list]

    # Min/max for normalization
    min_intr, max_intr = min(intraday_vals), max(intraday_vals)
    min_vols, max_vols = min(vol_strength_vals), max(vol_strength_vals)
    min_vz, max_vz    = min(vol_z_vals), max(vol_z_vals)
    min_vlt, max_vlt  = min(volatilities), max(volatilities)
    min_sr, max_sr    = min(sr_vals), max(sr_vals)
    min_bc, max_bc    = min(buy_conf_vals), max(buy_conf_vals)

    scored = []
    for f in features_list:
        vol_strength = f.get("vol_strength", 0.0)
        if vol_strength < 0.5:
            scored.append({**f, "score": 0.0})
            continue

        # Normalized components
        s_intr  = normalize(f.get("intraday_pct", 0.0), min_intr, max_intr)
        s_vol   = normalize(vol_strength, min_vols, max_vols)
        s_vz    = normalize(f.get("vol_zscore", 0.0), min_vz, max_vz)
        s_vlt   = 1 - normalize(f.get("volatility", 0.0), min_vlt, max_vlt)
        s_sr    = normalize(f.get("sr_score", 0.0), min_sr, max_sr)
        s_macd  = 1 if f.get("macd_trend", 0) == 1 else 0
        s_trend = 1 if f.get("ma_diff", 0) > 0 else 0

        # RSI mid-range scoring
        rsi = f.get("rsi", 50)
        s_rsi = 0.2 if rsi > 70 else 1 - abs(rsi - 50) / 50

        # Buy confidence normalized
        buy_conf = f.get("buy_confidence", 0.5)
        s_bc = normalize(buy_conf, min_bc, max_bc)

        # Volume boost
        vol_boost = 0.05 if vol_strength >= 2.0 else 0.0

        # Weighted score (tuned)
        score = (
            0.22 * s_intr +       # momentum
            0.18 * s_vol +        # volume strength
            0.07 * s_vz +         # volume z-score fine tuning
            0.10 * s_macd +       # MACD trend confirmation
            0.06 * s_rsi +        # RSI stability
            0.05 * s_trend +      # MA trend
            0.09 * s_vlt +        # lower volatility preferred
            0.09 * s_sr +         # support/resistance score
            0.14 * s_bc           # BUY CONFIDENCE weighted higher
        ) + vol_boost

        scored.append({**f, "score": round(score, 4)})

    # Sort descending
    scored_sorted = sorted(scored, key=lambda x: x.get("score", 0.0), reverse=True)
    return scored_sorted
