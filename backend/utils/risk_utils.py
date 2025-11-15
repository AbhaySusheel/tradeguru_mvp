"""
risk_utils.py
--------------
Risk scoring model for TradeGuru.

Inputs expected:
- ATR % (from atr_utils)
- Volume score (from volume_utils)
- Candle strength score (from candle_utils)
- Trend structure (HH, HL, LH, LL from swing_utils)
"""

import numpy as np

def normalize(value, min_v, max_v):
    """Scale value between 0 and 1 safely."""
    if value is None:
        return 0
    try:
        return max(0, min(1, (value - min_v) / (max_v - min_v)))
    except:
        return 0


def compute_trend_risk(trend_tag):
    """
    Trend tags:
    - "HH" strong uptrend → LOW RISK
    - "HL" pullback bullish → LOW–MED
    - "LH" weakening → HIGH
    - "LL" downtrend → VERY HIGH
    """

    mapping = {
        "HH": 0.1,
        "HL": 0.25,
        "LH": 0.65,
        "LL": 0.85
    }

    return mapping.get(trend_tag, 0.5)


def compute_atr_risk(atr_percent):
    """
    ATR % of price:
    < 1% → low volatility (low risk)
    1–3% → medium
    3–5% → high
    > 5% → very high
    """

    if atr_percent is None:
        return 0.5

    if atr_percent < 1:
        return 0.1
    elif atr_percent < 3:
        return 0.35
    elif atr_percent < 5:
        return 0.65
    else:
        return 0.85


def compute_volume_risk(volume_score):
    """
    High volume breakout → low risk  
    Low volume → high risk
    volume_score is already 0–1
    """

    if volume_score is None:
        return 0.5

    # inverse relation
    return 1 - volume_score


def compute_candle_risk(candle_strength):
    """
    candle_strength = 0 to 1
    1 = strong bullish → low risk
    0 = bearish → high risk
    """

    if candle_strength is None:
        return 0.5

    return 1 - candle_strength


def compute_total_risk(features):
    """
    features = {
        'atr_percent': float,
        'volume_score': float,
        'candle_strength': float,
        'trend_tag': 'HH/HL/LH/LL'
    }
    """

    atr_risk = compute_atr_risk(features.get("atr_percent"))
    vol_risk = compute_volume_risk(features.get("volume_score"))
    candle_risk = compute_candle_risk(features.get("candle_strength"))
    trend_risk = compute_trend_risk(features.get("trend_tag"))

    # Weighted score
    total = (
        atr_risk * 0.30 +
        vol_risk * 0.25 +
        candle_risk * 0.20 +
        trend_risk * 0.25
    )

    return round(total, 3)
