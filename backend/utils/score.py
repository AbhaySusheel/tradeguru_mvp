# backend/utils/score.py
import math

def normalize(x, minv, maxv):
    if maxv == minv:
        return 0.5
    return (x - minv) / (maxv - minv)

def score_from_features(features_list):
    # features_list: list of dicts each containing computed features
    # We'll normalize across the batch for intraday_pct and vol_ratio.
    intraday = [f["intraday_pct"] for f in features_list]
    volrat   = [f["vol_ratio"] for f in features_list]

    min_intr, max_intr = min(intraday), max(intraday)
    min_vol, max_vol   = min(volrat), max(volrat)

    scored = []
    for f in features_list:
        s_intr = normalize(f["intraday_pct"], min_intr, max_intr)
        s_vol  = normalize(f["vol_ratio"], min_vol, max_vol)
        # trend: positive ma_diff favored
        s_trend = 1 if f["ma_diff"] > 0 else 0
        # rsi: prefer middle range (30-70). Score highest ~50.
        s_rsi = 1 - (abs(f["rsi"] - 50) / 50)
        # weighted sum
        score = 0.5 * s_intr + 0.25 * s_vol + 0.15 * s_trend + 0.10 * s_rsi
        scored.append({**f, "score": round(score, 4)})
    # sort desc
    scored_sorted = sorted(scored, key=lambda x: x["score"], reverse=True)
    return scored_sorted
