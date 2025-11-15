import numpy as np
import pandas as pd

# ============================================================
# ADVANCED VOLUME MODEL (Recommended for ML)
# ============================================================

def compute_volume_features(vol_series):
    """
    Compute advanced volume metrics using z-scores, rolling windows,
    and anomaly detection.
    
    Returns dict with:
        - vol_mean_20
        - vol_std_20
        - vol_zscore
        - vol_surge      (1 if volume spike, else 0)
        - vol_trend_5    (short-term trend)
        - vol_trend_20   (long-term trend)
        - vol_spike_ratio (vol_now / max last 20)
    """

    vol = np.array(vol_series, dtype=float)
    n = len(vol)

    if n < 5:
        return {
            "vol_mean_20": float(np.mean(vol)),
            "vol_std_20": float(np.std(vol)),
            "vol_zscore": 0.0,
            "vol_surge": 0,
            "vol_trend_5": 0.0,
            "vol_trend_20": 0.0,
            "vol_spike_ratio": 1.0
        }

    # -----------------------------
    # 20-bar rolling stats
    # -----------------------------
    last20 = vol[-20:] if n >= 20 else vol
    vol_mean_20 = float(np.mean(last20))
    vol_std_20 = float(np.std(last20)) if np.std(last20) > 0 else 1.0

    vol_now = vol[-1]

    # Z-score of current volume
    vol_zscore = float((vol_now - vol_mean_20) / vol_std_20)

    # -----------------------------
    # Volume Spike (Anomaly Detection)
    # -----------------------------
    vol_surge = 1 if vol_now > (vol_mean_20 + 2 * vol_std_20) else 0

    # -----------------------------
    # Volume Trend (Slope) short & long
    # -----------------------------
    def compute_slope(arr):
        xs = np.arange(len(arr))
        # simple linear regression slope
        m = np.polyfit(xs, arr, 1)[0]
        return float(m)

    # short trend (5 bars)
    vol_trend_5 = compute_slope(vol[-5:]) if n >= 5 else 0.0

    # long trend (20 bars)
    vol_trend_20 = compute_slope(last20)

    # -----------------------------
    # Spike ratio (how strong current vol is)
    # -----------------------------
    vol_spike_ratio = float(vol_now / (np.max(last20) + 1e-9))

    return {
        "vol_mean_20": vol_mean_20,
        "vol_std_20": vol_std_20,
        "vol_zscore": round(vol_zscore, 4),
        "vol_surge": vol_surge,
        "vol_trend_5": round(vol_trend_5, 6),
        "vol_trend_20": round(vol_trend_20, 6),
        "vol_spike_ratio": round(vol_spike_ratio, 4)
    }


# ============================================================
# Combined Signal Score (Optional)
# ============================================================
def compute_volume_signal(vol_features):
    """
    Create a combined volume signal score for ML or scoring.
    Weighted mixture of:
        - zscore
        - spike ratio
        - surge flag
        - trend

    Returns score between 0 and 1
    """

    z = max(min(vol_features["vol_zscore"] / 5, 1.0), 0.0)   # normalize
    spike = vol_features["vol_spike_ratio"]
    surge = 1.0 if vol_features["vol_surge"] == 1 else 0.0
    t5 = vol_features["vol_trend_5"]
    t20 = vol_features["vol_trend_20"]

    # normalize trends (center around 0)
    t5_norm = max(min((t5 * 200), 1.0), -1.0)
    t20_norm = max(min((t20 * 50), 1.0), -1.0)

    # weighted mix
    score = (
        0.35 * z +
        0.30 * spike +
        0.20 * surge +
        0.10 * max(t5_norm, 0) +
        0.05 * max(t20_norm, 0)
    )

    return float(round(max(min(score, 1.0), 0.0), 4))
