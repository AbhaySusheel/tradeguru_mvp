# backend/models/stock_model.py
"""
StockModel - Unified ML + Technical Engine (high-accuracy mode)

Features:
- Loads joblib model bundle saved by train_xgboost_v3.py (expects keys: 'booster','scaler','features','best_iteration' optional)
- Loads model_features_v3.json (exact feature order)
- Accepts either a pre-fetched DataFrame or fetches intraday via utils.market.fetch_intraday
- Uses market.compute_features() then augments with many ML-specific features (rolling returns, vol, ATR%, wick ratios, price-percentile, RSI slope, etc.)
- Predicts ML buy probability and composes a final combined score with engine score.
- Public API: StockModel.analyze_stock(symbol_or_df, fetch_if_missing=True, combine_weights=None)
"""

from __future__ import annotations
import json
import math
from pathlib import Path
from typing import Dict, Any, Optional, List, Tuple, Union

import numpy as np
import pandas as pd
import joblib
import xgboost as xgb

# import utils (adjust path if needed)
from utils.market import fetch_intraday, compute_features
from utils.score import score_from_features
from utils.buy_confidence_utils import compute_buy_confidence
from utils.atr_utils import compute_atr, compute_volatility_regime
from utils.candle_utils import get_candle_features
from utils.swing_utils import compute_trend_structure

# ---------------------------
# Configuration / Defaults
# ---------------------------
DEFAULT_MODEL_PATH = str(Path(__file__).parent / "xgb_buyprob_model_v3.joblib")
DEFAULT_FEATURES_PATH = str(Path(__file__).parent / "model_features_v3.json")

# default combination weights (ml heavier for accuracy)
DEFAULT_COMBINE_WEIGHTS = {
    "ml": 0.65,       # weight for ML probability
    "engine": 0.35    # weight for your rule-based engine score
}

# ---------------------------
# Helpers
# ---------------------------
def _safe_float(x, default=float("nan")):
    try:
        if x is None:
            return default
        return float(x)
    except Exception:
        return default

def _label_from_prob_and_score(p: float, score: float) -> str:
    """Return BUY / HOLD / SELL label using thresholds tuned for accuracy."""
    # Use prob primary, fallback to engine score
    if math.isnan(p):
        val = score
    else:
        val = (p + score) / 2.0
    if val >= 0.7:
        return "BUY"
    if val >= 0.45:
        return "HOLD"
    return "SELL"

def _percentile_rank(series: pd.Series, value: float) -> float:
    try:
        arr = series.dropna().values
        if len(arr) == 0:
            return 0.5
        return float((arr <= value).sum() / len(arr))
    except Exception:
        return 0.5

# ---------------------------
# StockModel Class
# ---------------------------
class StockModel:
    def __init__(
        self,
        model_bundle_path: Optional[str] = None,
        model_features_path: Optional[str] = None,
        combine_weights: Optional[Dict[str, float]] = None,
        verbose: bool = False,
    ):
        self.verbose = verbose
        self.model_bundle_path = model_bundle_path or DEFAULT_MODEL_PATH
        self.model_features_path = model_features_path or DEFAULT_FEATURES_PATH
        self.combine_weights = combine_weights or DEFAULT_COMBINE_WEIGHTS

        # ML objects
        self.booster: Optional[xgb.Booster] = None
        self.scaler = None
        self.feature_order: List[str] = []
        self.best_iteration: Optional[int] = None

        # load on init
        self._load_model_bundle()
        self._load_feature_order()

    # ---------------------------
    # Loading utilities
    # ---------------------------
    def _load_model_bundle(self):
        p = Path(self.model_bundle_path)
        if not p.exists():
            if self.verbose:
                print(f"[StockModel] Model bundle {p} not found, ML disabled.")
            return
        bundle = joblib.load(str(p))
        # train script stored dict with keys: 'booster','scaler','features','best_iteration'
        self.booster = bundle.get("booster", None)
        self.scaler = bundle.get("scaler", None)
        # If saved directly as a Booster rather than inside dict:
        if isinstance(bundle, xgb.Booster):
            self.booster = bundle
        self.best_iteration = bundle.get("best_iteration", None) if isinstance(bundle, dict) else None
        if self.verbose:
            print(f"[StockModel] Loaded model bundle from {p} - booster: {self.booster is not None}")

    def _load_feature_order(self):
        p = Path(self.model_features_path)
        if not p.exists():
            if self.verbose:
                print(f"[StockModel] Feature order {p} not found, falling back to model-bundle features if present.")
            return
        try:
            d = json.loads(p.read_text(encoding="utf8"))
            if isinstance(d, dict) and "features" in d:
                self.feature_order = list(d["features"])
            elif isinstance(d, list):
                self.feature_order = list(d)
            else:
                # try to interpret keys as features
                self.feature_order = list(d.get("features", [])) if isinstance(d, dict) else []
            if self.verbose:
                print(f"[StockModel] Loaded {len(self.feature_order)} model features from {p}")
        except Exception as e:
            if self.verbose:
                print(f"[StockModel] Failed to load feature order: {e}")
            self.feature_order = []

    # ---------------------------
    # ML Prediction
    # ---------------------------
    def _predict_ml_prob(self, feature_dict: Dict[str, float]) -> float:
        """Return ML buy probability 0..1 using loaded booster and scaler."""
        if self.booster is None:
            return float("nan")

        # Prepare vector in feature_order
        if self.feature_order:
            X = np.array([[ _safe_float(feature_dict.get(f, np.nan)) for f in self.feature_order ]], dtype=float)
        else:
            # fallback: use whatever keys available sorted
            keys = sorted(feature_dict.keys())
            X = np.array([[ _safe_float(feature_dict.get(k, np.nan)) for k in keys ]], dtype=float)

        # apply scaler if present
        if self.scaler is not None:
            try:
                X = self.scaler.transform(X)
            except Exception:
                # ignore scaler errors
                pass

        dmat = xgb.DMatrix(X, feature_names=self.feature_order if self.feature_order else None)
        try:
            if self.best_iteration is not None:
                pred = self.booster.predict(dmat, iteration_range=(0, int(self.best_iteration) + 1))
            else:
                pred = self.booster.predict(dmat)
            p = float(pred[0]) if hasattr(pred, "__len__") else float(pred)
            # clamp
            return max(0.0, min(1.0, p))
        except Exception as e:
            if self.verbose:
                print(f"[StockModel] ML prediction error: {e}")
            # fallback nan
            return float("nan")

    # ---------------------------
    # Extra Feature Engineering (Option B - high accuracy)
    # ---------------------------
    def _augment_features_for_ml(self, df: pd.DataFrame, feats: Dict[str, Any]) -> Dict[str, float]:
        """
        Starting from compute_features() output (feats) augment with additional features ML likes:
        - returns (last, 1/3/5/10)
        - rolling std of returns
        - close relative to 52/75 lookback highs/lows
        - ATR normalized by price
        - candle body ratio & wick ratios
        - RSI slope, MACD hist
        - volume delta features
        - price percentile across lookback
        """
        out = dict(feats)  # copy existing
        # safe guards
        if df is None or df.empty:
            return out

        close = df["Close"].astype(float)
        high = df["High"].astype(float)
        low = df["Low"].astype(float)
        vol = df["Volume"].astype(float)

        # returns
        out["ret_1"]  = float(close.pct_change(1).iloc[-1] if len(close) > 1 else 0.0)
        out["ret_3"]  = float(close.pct_change(3).iloc[-1] if len(close) > 3 else 0.0)
        out["ret_5"]  = float(close.pct_change(5).iloc[-1] if len(close) > 5 else 0.0)
        out["ret_10"] = float(close.pct_change(10).iloc[-1] if len(close) > 10 else 0.0)

        # rolling vol of returns
        ret = close.pct_change().fillna(0)
        out["ret_std_5"]  = float(ret.rolling(5).std().iloc[-1] if len(ret) >= 5 else ret.std())
        out["ret_std_10"] = float(ret.rolling(10).std().iloc[-1] if len(ret) >= 10 else ret.std())

        # price percentile in lookbacks
        for lb in (10, 20, 50, 75, 120):
            try:
                out[f"price_pct_{lb}"] = _percentile_rank(close.tail(lb), float(close.iloc[-1]))
            except Exception:
                out[f"price_pct_{lb}"] = 0.5

        # range features
        out["intraday_range"] = float((high.iloc[-1] - low.iloc[-1]) / (close.iloc[-1] + 1e-9))
        out["hl_range_10mean"] = float((high - low).rolling(10).mean().iloc[-1] if len(close) >= 10 else (high - low).mean())

        # ATR pct if possible (use util compute_atr)
        try:
            atr_val = compute_atr(df, period=14)
            out["atr_val"] = _safe_float(atr_val, 0.0)
            out["atr_pct_calc"] = out["atr_val"] / (close.iloc[-1] + 1e-9)
        except Exception:
            out["atr_val"] = 0.0
            out["atr_pct_calc"] = 0.0

        # wick/body ratios last candle
        o = float(df["Open"].iloc[-1])
        c = float(df["Close"].iloc[-1])
        h = float(df["High"].iloc[-1])
        l = float(df["Low"].iloc[-1])
        body = abs(c - o) + 1e-9
        out["body_size"] = float(body)
        out["upper_wick_ratio"] = float((h - max(o, c)) / body)
        out["lower_wick_ratio"] = float((min(o, c) - l) / body)

        # mean volume relative to last
        out["vol_mean_20"] = float(vol.tail(20).mean()) if len(vol) >= 1 else float(vol.mean())
        out["vol_last_over_mean20"] = float(vol.iloc[-1] / (out["vol_mean_20"] + 1e-9))

        # volume momentum
        out["vol_mom_3"] = float(vol.pct_change(3).iloc[-1] if len(vol) >= 3 else 0.0)
        out["vol_mom_10"] = float(vol.pct_change(10).iloc[-1] if len(vol) >= 10 else 0.0)

        # RSI slope
        try:
            rsi_series = pd.Series([feats.get("rsi", 50)])  # fallback
            # rebuild small RSI series from close if possible
            # approximate RSI slope using small window of price returns:
            out["rsi_slope_3"] = float((close.tail(3).pct_change().mean()) if len(close) >= 3 else 0.0)
        except Exception:
            out["rsi_slope_3"] = 0.0

        # trend strength via EMAs
        try:
            ema9 = close.ewm(span=9, adjust=False).mean().iloc[-1]
            ema21 = close.ewm(span=21, adjust=False).mean().iloc[-1]
            out["ema9"] = float(ema9)
            out["ema21"] = float(ema21)
            out["ema9_21_diff"] = float(ema9 - ema21)
        except Exception:
            out["ema9"] = out["ema21"] = out["ema9_21_diff"] = 0.0

        # swing structure quick one-hot encoding (from utils.swing_utils)
        try:
            swing = compute_trend_structure(df)
            out["swing_score_raw"] = float(swing.get("swing_score", 50))
            out["trend_phase_tag"] = 1 if swing.get("trend_phase") == "uptrend" else ( -1 if swing.get("trend_phase") == "downtrend" else 0)
        except Exception:
            out["swing_score_raw"] = 50.0
            out["trend_phase_tag"] = 0

        # candle numeric summary from utils
        try:
            candle = get_candle_features(df)
            out["candle_pattern_score"] = float(candle.get("candle_pattern_score", 0.0))
            out["candle_bull"] = int(candle.get("candle_bull", 0))
            out["candle_bear"] = int(candle.get("candle_bear", 0))
        except Exception:
            out["candle_pattern_score"] = 0.0
            out["candle_bull"] = 0
            out["candle_bear"] = 0

        # risk features
        try:
            vr = compute_volatility_regime(df)
            out["atr_pct_util"] = float(vr.get("atr_pct", 0.0))
            out["vol_regime_tag"] = int(vr.get("vol_regime", 1))
        except Exception:
            out["atr_pct_util"] = 0.0
            out["vol_regime_tag"] = 1

        # normalize/ensure numeric types for ML
        for k, v in list(out.items()):
            if isinstance(v, (list, dict)):
                # skip complex structures; ML expects flat numeric features
                out.pop(k, None)
            else:
                try:
                    out[k] = float(v)
                except Exception:
                    out[k] = float("nan")
        return out

    # ---------------------------
    # Combine ML + Engine
    # ---------------------------
    def combine_scores(self, ml_prob: float, engine_score: float, weights: Optional[Dict[str, float]] = None) -> float:
        w = weights or self.combine_weights
        ml_w = w.get("ml", 0.65)
        eng_w = w.get("engine", 0.35)
        total = ml_w + eng_w
        if total <= 0:
            total = 1.0
        ml_p = 0.0 if math.isnan(ml_prob) else float(ml_prob)
        eng_p = 0.0 if math.isnan(engine_score) else float(engine_score)
        combined = (ml_w * ml_p + eng_w * eng_p) / total
        # clamp
        return float(max(0.0, min(1.0, combined)))

    # ---------------------------
    # Public API: analyze_stock
    # ---------------------------
   def analyze_stock(
        self,
        symbol_or_df: Union[str, pd.DataFrame],
        fetch_if_missing: bool = True,
        ml_only: bool = False,
        combine_weights: Optional[Dict[str, float]] = None,
        return_raw: bool = False,
        force_symbol: Optional[str] = None
    ) -> Dict[str, Any]:
    """
    Updated version:
    - You can pass DataFrame + force_symbol="TCS"
    - Prevents UNKNOWN symbol issues
    """
    df = None

    # -------------------------
    # CASE 1: DataFrame passed
    # -------------------------
    if isinstance(symbol_or_df, pd.DataFrame):
        if force_symbol is None:
            return {"ok": False, "error": "no_symbol_for_df", "symbol": "UNKNOWN"}

        symbol = force_symbol.strip().upper()
        df = symbol_or_df.copy().reset_index(drop=True)

    else:
        # -------------------------
        # CASE 2: Symbol string passed
        # -------------------------
        symbol = str(symbol_or_df).strip().upper()

        if not symbol.endswith(".NS"):
            symbol_ns = symbol + ".NS"
        else:
            symbol_ns = symbol

        if fetch_if_missing:
            df = fetch_intraday(symbol_ns, period="1d", interval="5m")
            if df is None or len(df) < 10:
                return {"ok": False, "error": "fetch_failed", "symbol": symbol}
        else:
            return {"ok": False, "error": "no_df_provided", "symbol": symbol}

    # ------------------------------------
    # Base feature extraction
    # ------------------------------------
    base_feats = compute_features(df)
    if base_feats is None:
        return {"ok": False, "error": "compute_features_failed", "symbol": symbol}

    # ------------------------------------
    # ML part
    # ------------------------------------
    ml_input = self._augment_features_for_ml(df, base_feats)
    ml_prob = self._predict_ml_prob(ml_input)

    # ------------------------------------
    # Engine score
    # ------------------------------------
    try:
        engine_scored = score_from_features([base_feats])
        engine_score = engine_scored[0].get("score", 0.0) if engine_scored else 0.0
    except:
        engine_score = 0.0

    # ------------------------------------
    # Combined score
    # ------------------------------------
    combined_score = self.combine_scores(
        ml_prob,
        engine_score,
        combine_weights or self.combine_weights
    )

    label = _label_from_prob_and_score(ml_prob, combined_score)

    # ------------------------------------
    # Trade plan
    # ------------------------------------
    entry = float(base_feats.get("last_price", float(df["Close"].iloc[-1])))
    atr_val = float(ml_input.get("atr_val", 0.0))

    if math.isnan(atr_val) or atr_val <= 0:
        sl = entry * 0.99
        targets = [entry * 1.02, entry * 1.04]
    else:
        sl = entry - atr_val
        targets = [entry + atr_val * r for r in (1.5, 2.5, 4.0)]

    # Final structured output
    result = {
        "ok": True,
        "symbol": symbol.replace(".NS", "").upper(),
        "last_price": float(entry),
        "ml_buy_prob": float(round(ml_prob, 4)),
        "engine_score": float(round(engine_score, 4)),
        "combined_score": float(round(combined_score, 4)),
        "label": label,
        "buy_confidence": float(round(base_feats.get("buy_confidence", 0), 4)),
        "trade_plan": {
            "entry": float(entry),
            "sl": float(sl),
            "targets": [float(round(t, 4)) for t in targets]
        }
    }

    return result


# ---------------------------
# Convenience single-instance for app usage
# ---------------------------
_default_engine: Optional[StockModel] = None

def get_default_engine(model_bundle_path: Optional[str] = None, features_path: Optional[str] = None, verbose: bool = False) -> StockModel:
    global _default_engine
    if _default_engine is None:
        _default_engine = StockModel(model_bundle_path=model_bundle_path, model_features_path=features_path, verbose=verbose)
    return _default_engine

# ---------------------------
# CLI quick test (not executed on import)
# ---------------------------
if __name__ == "__main__":
    import argparse, pprint
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--model", default=DEFAULT_MODEL_PATH)
    parser.add_argument("--features", default=DEFAULT_FEATURES_PATH)
    args = parser.parse_args()
    eng = get_default_engine(model_bundle_path=args.model, features_path=args.features, verbose=True)
    out = eng.analyze_stock(args.symbol, fetch_if_missing=True, return_raw=False)
    pprint.pprint(out, indent=2)
