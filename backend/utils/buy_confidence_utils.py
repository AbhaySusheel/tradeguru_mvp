def compute_buy_confidence(features: dict) -> float:
    """
    Computes a normalized Buy Confidence Score (0–100)
    Inputs: features dict from compute_features()
    """
    score = 0

    # Candle pattern contribution
    score += 30 * features.get("candle_bull", 0)

    # Volume contribution
    score += 25 * min(features.get("vol_signal", 0), 1)

    # Trend phase contribution
    score += 20 if features.get("trend_phase") == 1 else 0

    # RSI contribution (prefer 50-70 for bullish confidence)
    rsi = features.get("rsi", 50)
    if 50 <= rsi <= 70:
        score += 15
    elif rsi < 50:
        score += 5  # low momentum

    # Breakout score contribution (0–1 scaled to 10)
    score += min(features.get("breakout_score", 0) * 10, 10)

    # Cap at 100
    return min(round(score, 2), 100)

