# backend/utils/score.py
import math

def normalize(x, minv, maxv):
    if maxv == minv:
        return 0.5
    return (x - minv) / (maxv - minv)


def score_from_features(features_list):
    # Normalized fields
    intraday_vals = [f["intraday_pct"] for f in features_list]
    vol_vals      = [f["vol_ratio"] for f in features_list]
    volatilities  = [f["volatility"] for f in features_list]

    # min/max
    min_intr, max_intr = min(intraday_vals), max(intraday_vals)
    min_vol, max_vol   = min(vol_vals), max(vol_vals)
    min_vlt, max_vlt   = min(volatilities), max(volatilities)

    scored = []

    for f in features_list:
        s_intr = normalize(f["intraday_pct"], min_intr, max_intr)
        s_vol  = normalize(f["vol_ratio"], min_vol, max_vol)
        s_vlt  = 1 - normalize(f["volatility"], min_vlt, max_vlt)  # lower volatility = higher score

        # 1) MACD confirmation
        s_macd = 1 if f["macd_trend"] == 1 else 0

        # 2) MA trend
        s_trend = 1 if f["ma_diff"] > 0 else 0

        # 3) RSI mid-range (40–60 is best)
        if f["rsi"] < 40 or f["rsi"] > 70:
            s_rsi = 0.2  # penalize overbought or oversold
        else:
            s_rsi = 1 - abs(f["rsi"] - 50) / 20

        # === Weighted score ===
        score = (
            0.30 * s_intr +
            0.25 * s_vol +
            0.15 * s_macd +
            0.10 * s_rsi +
            0.10 * s_trend +
            0.10 * s_vlt
        )

        scored.append({**f, "score": round(score, 4)})

    scored_sorted = sorted(scored, key=lambda x: x["score"], reverse=True)
    return scored_sorted
