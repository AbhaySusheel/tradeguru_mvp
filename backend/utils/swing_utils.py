import numpy as np
import pandas as pd


def detect_swings(df, lookback=5):
    """
    Identify local swing highs/lows.
    """
    highs = df["High"].values
    lows = df["Low"].values

    swing_highs = []
    swing_lows = []

    for i in range(lookback, len(df) - lookback):
        if highs[i] == max(highs[i - lookback: i + lookback + 1]):
            swing_highs.append((i, highs[i]))

        if lows[i] == min(lows[i - lookback: i + lookback + 1]):
            swing_lows.append((i, lows[i]))

    return swing_highs, swing_lows


def classify_trend_structure(swing_highs, swing_lows):
    """
    Given detected swing highs/lows, classify structure:
    - HH (Higher High)
    - HL (Higher Low)
    - LH (Lower High)
    - LL (Lower Low)
    """
    trend_events = []

    # Compare relative to previous swing highs & lows
    for idx in range(1, min(len(swing_highs), len(swing_lows))):
        prev_high = swing_highs[idx - 1][1]
        curr_high = swing_highs[idx][1]

        prev_low = swing_lows[idx - 1][1]
        curr_low = swing_lows[idx][1]

        # Highs
        if curr_high > prev_high:
            trend_events.append("HH")
        else:
            trend_events.append("LH")

        # Lows
        if curr_low > prev_low:
            trend_events.append("HL")
        else:
            trend_events.append("LL")

    return trend_events


def determine_market_phase(events):
    """
    Events → Uptrend / Downtrend / Choppy
    HH + HL → Uptrend
    LH + LL → Downtrend
    Mixed → Choppy
    """
    if not events:
        return "choppy"

    up = events.count("HH") + events.count("HL")
    down = events.count("LH") + events.count("LL")

    if up > down * 1.3:
        return "uptrend"
    elif down > up * 1.3:
        return "downtrend"
    else:
        return "choppy"


def compute_swing_score(events):
    """
    Convert swing structure into 0–100 ML-friendly numeric value.

    Score idea:
    - HH + HL = bullish → +10 each
    - LH + LL = bearish → -10 each
    """
    if not events:
        return 50  # neutral

    score = 50

    for e in events:
        if e in ["HH", "HL"]:
            score += 8
        elif e in ["LH", "LL"]:
            score -= 8

    # Clamp to 0–100
    return max(0, min(100, score))


def compute_trend_structure(df):
    """
    Full wrapper called from compute_features().
    """
    if df is None or len(df) < 20:
        return {
            "trend_events": [],
            "trend_phase": "choppy",
            "swing_score": 50
        }

    swing_highs, swing_lows = detect_swings(df)
    events = classify_trend_structure(swing_highs, swing_lows)
    phase = determine_market_phase(events)
    score = compute_swing_score(events)

    return {
        "trend_events": events[-6:],  # last few only
        "trend_phase": phase,
        "swing_score": score
    }
