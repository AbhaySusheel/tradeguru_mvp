import numpy as np
import pandas as pd


# ------------------------------------------------------------
# Helper Functions
# ------------------------------------------------------------
def _body_size(o, c):
    return abs(c - o)


def _upper_wick(h, o, c):
    return h - max(o, c)


def _lower_wick(l, o, c):
    return min(o, c) - l


def _is_bullish(o, c):
    return c > o


def _is_bearish(o, c):
    return o > c


# ------------------------------------------------------------
# Candlestick Detection
# ------------------------------------------------------------
def detect_hammer(o, h, l, c):
    body = _body_size(o, c)
    lower = _lower_wick(l, o, c)
    upper = _upper_wick(h, o, c)

    if body == 0:
        return 0

    if lower > body * 2.5 and upper < body * 0.4:
        return 1
    return 0


def detect_shooting_star(o, h, l, c):
    body = _body_size(o, c)
    lower = _lower_wick(l, o, c)
    upper = _upper_wick(h, o, c)

    if body == 0:
        return 0

    if upper > body * 2.5 and lower < body * 0.4:
        return 1
    return 0


def detect_doji(o, c, threshold=0.002):
    if abs(c - o) <= threshold * max(o, c):
        return 1
    return 0


def detect_bullish_engulfing(prev_o, prev_c, o, c):
    return 1 if _is_bearish(prev_o, prev_c) and _is_bullish(o, c) and c > prev_o and o < prev_c else 0


def detect_bearish_engulfing(prev_o, prev_c, o, c):
    return 1 if _is_bullish(prev_o, prev_c) and _is_bearish(o, c) and o > prev_c and c < prev_o else 0


def detect_inside_bar(prev_h, prev_l, h, l):
    return 1 if h < prev_h and l > prev_l else 0


def detect_morning_star(o1, c1, o2, c2, o3, c3):
    # Bear candle, small candle, bull candle closing above mid of candle 1
    if _is_bearish(o1, c1) and abs(c2 - o2) < abs(c1 - o1) * 0.5 and _is_bullish(o3, c3):
        if c3 > (o1 + c1) / 2:
            return 1
    return 0


def detect_evening_star(o1, c1, o2, c2, o3, c3):
    if _is_bullish(o1, c1) and abs(c2 - o2) < abs(c1 - o1) * 0.5 and _is_bearish(o3, c3):
        if c3 < (o1 + c1) / 2:
            return 1
    return 0


# ------------------------------------------------------------
# Pattern Scoring System (0–100)
# ------------------------------------------------------------
def compute_candle_score(df):
    """
    Computes:
        - pattern flags (1/0)
        - candle pattern strength score (0–100)
    """
    if df is None or len(df) < 3:
        return {
            "candle_pattern_score": 0,
            "pattern_flags": {}
        }

    # Use last 3 candles for multi-candle patterns
    o3, h3, l3, c3 = df.iloc[-1][["Open", "High", "Low", "Close"]]
    o2, h2, l2, c2 = df.iloc[-2][["Open", "High", "Low", "Close"]]
    o1, h1, l1, c1 = df.iloc[-3][["Open", "High", "Low", "Close"]]

    flags = {}

    # 1-Candle Patterns
    flags["hammer"] = detect_hammer(o3, h3, l3, c3)
    flags["shooting_star"] = detect_shooting_star(o3, h3, l3, c3)
    flags["doji"] = detect_doji(o3, c3)

    # 2-Candle Patterns
    flags["bullish_engulfing"] = detect_bullish_engulfing(o2, c2, o3, c3)
    flags["bearish_engulfing"] = detect_bearish_engulfing(o2, c2, o3, c3)
    flags["inside_bar"] = detect_inside_bar(h2, l2, h3, l3)

    # 3-Candle Patterns
    flags["morning_star"] = detect_morning_star(o1, c1, o2, c2, o3, c3)
    flags["evening_star"] = detect_evening_star(o1, c1, o2, c2, o3, c3)

    # --------------------------------------------------------
    # Pattern Strength Calculation (ML-Grade)
    # --------------------------------------------------------
    score = 0

    # Weighting based on reliability in literature
    weights = {
        "hammer": 12,
        "shooting_star": 12,
        "doji": 5,
        "bullish_engulfing": 22,
        "bearish_engulfing": 22,
        "inside_bar": 6,
        "morning_star": 30,
        "evening_star": 30,
    }

    for k, v in flags.items():
        if v == 1:
            score += weights[k]

    score = min(100, score)  # cap

    return {
        "candle_pattern_score": score,
        "pattern_flags": flags
    }
# ------------------------------------------------------------
# Public API Wrapper (Required by market.py)
# ------------------------------------------------------------
def get_candle_features(df):
    """
    Wrapper so market.py can import a clean interface.
    Returns:
        - candle_pattern_score (0–100)
        - pattern_flags (dict of 1/0 signals)
    """
    return compute_candle_score(df)
