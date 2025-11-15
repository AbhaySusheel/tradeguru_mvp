# backend/utils/score.py
import math

def normalize(x, minv, maxv):
    if maxv == minv:
        return 0.5
    return (x - minv) / (maxv - minv)

def score_from_features(features_list):
    # features_list: list of dicts each containing computed features
    if not features_list:
        return []

    # build lists (guard against missing keys)
    intraday_vals = [f.get("intraday_pct", 0.0) for f in features_list]
    vol_strength_vals = [f.get("vol_strength", 0.0) for f in features_list]
    vol_z_vals = [f.get("vol_zscore", 0.0) for f in features_list]
    volatilities = [f.get("volatility", 0.0) for f in features_list]

    min_intr, max_intr = min(intraday_vals), max(intraday_vals)
    min_vols, max_vols = min(vol_strength_vals), max(vol_strength_vals)
    min_vz, max_vz = min(vol_z_vals), max(vol_z_vals)
    min_vlt, max_vlt = min(volatilities), max(volatilities)

    scored = []
    for f in features_list:
        # HARD FILTER: skip extremely low-volume moves (noise)
        vol_strength = f.get("vol_strength", 0.0)
        if vol_strength < 0.5:
            # mark with very low score and still include for logging; skip adding to final list if you prefer
            scored.append({**f, "score": 0.0})
            continue

        s_intr = normalize(f.get("intraday_pct", 0.0), min_intr, max_intr)
        s_vol  = normalize(vol_strength, min_vols, max_vols)
        s_vz   = normalize(f.get("vol_zscore", 0.0), min_vz, max_vz)
        s_vlt  = 1 - normalize(f.get("volatility", 0.0), min_vlt, max_vlt)  # lower volatility better

        # MACD confirmation and MA trend
        s_macd = 1 if f.get("macd_trend", 0) == 1 else 0
        s_trend = 1 if f.get("ma_diff", 0) > 0 else 0

        # RSI mid-range scoring (better near 50, penalize >70)
        rsi = f.get("rsi", 50)
        if rsi > 70:
            s_rsi = 0.2
        else:
            s_rsi = 1 - abs(rsi - 50) / 50

        # volume boost if very strong
        vol_boost = 0.05 if vol_strength >= 2.0 else 0.0

        # Weighted score (tune these weights later)
        score = (
            0.30 * s_intr +      # momentum
            0.25 * s_vol +       # raw vol strength
            0.10 * s_vz +        # vol zscore fine tuning
            0.15 * s_macd +      # macd confirmation
            0.10 * s_rsi +       # rsi stability
            0.05 * s_trend +     # ma trend
            0.05 * s_vlt         # lower volatility preferred
        ) + vol_boost

        scored.append({**f, "score": round(score, 4)})

    # sort desc
    scored_sorted = sorted(scored, key=lambda x: x.get("score", 0.0), reverse=True)
    return scored_sorted
