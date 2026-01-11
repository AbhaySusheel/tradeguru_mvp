# backend/models/stock_model.py
"""
StockModel - Unified ML + Technical Engine (high-accuracy mode)

Key updates:
- DEFAULT_COMBINE_WEIGHTS set to ml:0.35, engine:0.65 (your requested weighting)
- analyze_stock() updated to accept force_symbol and never return "UNKNOWN" symbol
- debug logging added
"""

from __future__ import annotations
import json
import math
import logging
from pathlib import Path
from typing import Dict, Any, Optional, List, Union

import numpy as np
import pandas as pd
import joblib
import xgboost as xgb

# utils (paths assume working dir = backend/)
from utils.market import fetch_intraday, compute_features
from utils.score import score_from_features
from utils.buy_confidence_utils import compute_buy_confidence
from utils.atr_utils import compute_atr, compute_volatility_regime
from utils.candle_utils import get_candle_features
from utils.swing_utils import compute_trend_structure

logger = logging.getLogger("stock_model")
logger.setLevel(logging.INFO)
if not logger.handlers:
    ch = logging.StreamHandler()
    ch.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(ch)

# ---------------------------
# Configuration / Defaults
# ---------------------------


# default combination weights (ml lighter, engine heavier as requested)
DEFAULT_COMBINE_WEIGHTS = {
    "ml": 0.35,       # weight for ML probability
    "engine": 0.65    # weight for rule-based engine score
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



    # cache per-symbol models
    _MODEL_CACHE = {}
    _MAX_MODEL_CACHE = 200


    
    def __init__(
        self,
        
        combine_weights: Optional[Dict[str, float]] = None,
        verbose: bool = False,
    ):
        self.verbose = verbose
  
        self.combine_weights = combine_weights or DEFAULT_COMBINE_WEIGHTS
        


        # ML objects
        self.booster: Optional[xgb.Booster] = None
        self.scaler = None
        self.feature_order: List[str] = []
        self.best_iteration: Optional[int] = None
        self.model_quality: Dict[str, float] = {}

        # load on init
        #self._load_model_bundle()
        #self._load_feature_order()


    # ---------------------------
    # ML Prediction
    # ---------------------------
    def _predict_ml_prob(self, feature_dict: Dict[str, float]) -> float:
        """Return ML buy probability 0..1 using loaded booster and scaler."""
        if self.booster is None:
            return float("nan")

        # Prepare vector in feature_order
        if self.feature_order:
            for f in self.feature_order:
                feature_dict.setdefault(f, 0.0)
            X_df = pd.DataFrame([[_safe_float(feature_dict[f]) for f in self.feature_order]],columns=self.feature_order,dtype=float,)
        else:
            # fallback: use whatever keys available sorted
            keys = sorted(feature_dict.keys())
            X_df = pd.DataFrame([[_safe_float(feature_dict.get(k, np.nan)) for k in keys]],columns=keys,dtype=float,)

        # apply scaler if present
        if self.scaler is not None:
            try:
                X_scaled = self.scaler.transform(X_df)
            except Exception as e:
                if self.verbose:
                    logger.warning(f"[StockModel] Scaler transform failed: {e}")
                return float("nan")

        else:
            X_scaled = X_df.values        

        dmat = xgb.DMatrix(X_scaled,feature_names=self.feature_order if self.feature_order else None)
        try:
            if self.best_iteration is not None:
                pred = self.booster.predict(dmat, iteration_range=(0, int(self.best_iteration) + 1))
            else:
                pred = self.booster.predict(dmat)
            p = float(pred[0]) if hasattr(pred, "__len__") else float(pred)
            return max(0.0, min(1.0, p))
        except Exception as e:
            if self.verbose:
                logger.warning(f"[StockModel] ML prediction error: {e}")
            return float("nan")

    # ---------------------------
    # Extra Feature Engineering
    # ---------------------------
    def _augment_features_for_ml(self, df: pd.DataFrame, feats: Dict[str, Any]) -> Dict[str, float]:
        out = dict(feats)
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
            out["rsi_slope_3"] = float((close.tail(3).pct_change().mean()) if len(close) >= 3 else 0.0)
        except Exception:
            out["rsi_slope_3"] = 0.0

        # trend strength via EMAs
        try:
            ema9 = close.ewm(span=9, adjust=False).mean().iloc[-1]
            ema21 = close.ewm(span=21, adjust=False).mean().iloc[-1]
            #out["ema9"] = float(ema9)
            #out["ema21"] = float(ema21)
            out["ema9_21_diff"] = float(ema9 - ema21)
        except Exception:
            out["ema9"] = out["ema21"] = out["ema9_21_diff"] = 0.0

        # swing structure quick one-hot encoding (from utils.swing_utils)
        try:
            swing = compute_trend_structure(df)
            out["swing_score_raw"] = float(swing.get("swing_score", 50))
            out["trend_phase_tag"] = 1 if swing.get("trend_phase") == "uptrend" else (-1 if swing.get("trend_phase") == "downtrend" else 0)
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

        # normalize numeric types for ML
        for k, v in list(out.items()):
            if isinstance(v, (list, dict)):
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
        ml_w = float(w.get("ml", 0.35))
        eng_w = float(w.get("engine", 0.65))
        total = ml_w + eng_w
        if total <= 0:
            total = 1.0
        ml_p = 0.0 if math.isnan(ml_prob) else float(ml_prob)
        eng_p = 0.0 if math.isnan(engine_score) else float(engine_score)
        combined = (ml_w * ml_p + eng_w * eng_p) / total
        return float(max(0.0, min(1.0, combined)))

    
    def _load_symbol_model(self, symbol: str):
        """
        Load ONE ML model per symbol.
        Falls back gracefully if model does not exist.
        """
        symbol = symbol.upper()
        if symbol in self._MODEL_CACHE:
            bundle = self._MODEL_CACHE[symbol]
            self.booster = bundle.get("booster")
            self.scaler = bundle.get("scaler")
            self.feature_order = bundle.get("features", [])
            self.best_iteration = bundle.get("best_iteration")
            self.model_quality = bundle.get("metrics", {})
            return

        model_path = Path(__file__).parent / f"xgb_buyprob_{symbol}.joblib"
        if not model_path.exists():
            self.booster = None
            self.scaler = None
            self.feature_order = []
            self.best_iteration = None
            self.model_quality = {}
            return

        bundle = joblib.load(str(model_path))
        

        self.booster = bundle.get("booster")
        self.scaler = bundle.get("scaler")
        self.feature_order = bundle.get("features", [])
        self.best_iteration = bundle.get("best_iteration")
        self.model_quality = bundle.get("metrics", {})

        self._MODEL_CACHE[symbol] = bundle
        if len(self._MODEL_CACHE) > self._MAX_MODEL_CACHE:
            self._MODEL_CACHE.pop(next(iter(self._MODEL_CACHE)))
    
    def _adaptive_ml_weight(self) -> float:
        """
        Dynamically scale ML weight based on model quality.
        """
        auc = self.model_quality.get("auc", 0.5)
        if auc >= 0.65:
            return 0.45
        if auc >= 0.60:
            return 0.35
        if auc >= 0.55:
            return 0.25
        return 0.10  # weak model → engine dominates
    

    # ---------------------------
    # Public API: analyze_stock
    # ---------------------------
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
        Updated analyze_stock:
        - if DataFrame is passed, use force_symbol to ensure correct naming.
        - always returns symbol correctly as upper-case w/o .NS
        - logs debug information
        """

        symbol = None
        df = None

        # CASE: DataFrame passed
        if isinstance(symbol_or_df, pd.DataFrame):
            if force_symbol is None:
                logger.warning("[analyze_stock] DataFrame provided without force_symbol -> rejecting")
                return {"ok": False, "error": "no_symbol_for_df", "symbol": "UNKNOWN"}
            
            symbol = force_symbol.strip().upper().replace(".NS", "")
            df = symbol_or_df.copy().reset_index(drop=True)
            # 🔥 load per-symbol ML model
            self._load_symbol_model(symbol)
            

        else:
            # CASE: string symbol passed
            symbol = str(symbol_or_df).strip().upper()
            symbol_clean = symbol.replace(".NS", "")
            symbol_ns =  symbol_clean + ".NS"
            self._load_symbol_model(symbol_clean)

            if fetch_if_missing:
                try:
                    df = fetch_intraday(symbol_ns, period="1d", interval="5m")

                    if df is None or len(df) < 2:
                        logger.debug(f"[analyze_stock] intraday failed, fallback to daily for {symbol_ns}")
                        df = fetch_intraday(symbol_ns, period="5d", interval="1d")

                except Exception as e:
                    logger.debug(f"[analyze_stock] fetch exception for {symbol_ns}: {e}")
                    df = None

                if df is None or len(df) < 2:
                    logger.info(f"[analyze_stock] fetch failed or too short for {symbol_ns}")
                    return {"ok": False, "error": "no_data", "symbol": symbol}
            else:
                logger.info(f"[analyze_stock] fetch_if_missing=False and no df provided for {symbol}")
                return {"ok": False, "error": "no_df_provided", "symbol": symbol}

        base_feats = compute_features(df)
        if base_feats is None:
            logger.info(f"[analyze_stock] compute_features failed for {symbol}")
            return {"ok": False, "error": "compute_features_failed", "symbol": symbol}

        ml_input = self._augment_features_for_ml(df, base_feats)
        ml_prob = self._predict_ml_prob(ml_input)
        if math.isnan(ml_prob):
            ml_prob = 0.0

        if ml_only:
            return {"ok": True,"symbol": symbol,"ml_buy_prob": float(round(ml_prob, 4)),"label": _label_from_prob_and_score(ml_prob, ml_prob),}
        try:
            engine_scored = score_from_features([base_feats])
            engine_score = engine_scored[0].get("score", 0.0) if engine_scored else 0.0
        except Exception as e:
            logger.debug(f"[analyze_stock] score_from_features error for {symbol}: {e}")
            engine_score = 0.0

        ml_w = self._adaptive_ml_weight()
        weights = combine_weights or {"ml": ml_w, "engine": 1.0 - ml_w}

        
        combined_score = self.combine_scores(ml_prob, engine_score, weights)

        label = _label_from_prob_and_score(combined_score, combined_score)
        buy_conf = _safe_float(base_feats.get("buy_confidence", compute_buy_confidence(base_feats)))

        entry = float(base_feats.get("last_price", float(df["Close"].iloc[-1])))
        atr_val = float(ml_input.get("atr_val", 0.0))
        if math.isnan(atr_val) or atr_val <= 0:
            sl = entry * 0.99
            targets = [entry * 1.02, entry * 1.04]
        else:
            sl = entry - atr_val
            targets = [entry + atr_val * r for r in (1.5, 2.5, 4.0)]

        logger.info(
            f"[analyze_stock] {symbol} price={entry:.4f} "
            f"intraday_pct={base_feats.get('intraday_pct')} "
            f"ml_prob={ml_prob:.4f} engine={engine_score:.4f} "
            f"combined={combined_score:.4f} buy_conf={buy_conf:.2f}"
        )

        result = {
            "ok": True,
            "symbol": symbol.replace(".NS", "").upper(),
            "last_price": float(entry),
            "ml_buy_prob": float(round(ml_prob, 4)),
            "engine_score": float(round(engine_score, 4)),
            "combined_score": float(round(combined_score, 4)),
            "label": label,
            "buy_confidence": float(round(buy_conf, 4)),
            "trade_plan": {
                "entry": float(entry),
                "sl": float(sl),
                "targets": [float(round(t, 4)) for t in targets],
            },
        }

        if return_raw:
            result["raw"] = {"base_feats": base_feats, "ml_input": ml_input}

        return result

    

# Singleton convenience
_default_engine: Optional[StockModel] = None

def get_default_engine(verbose: bool = False) -> StockModel:
    global _default_engine
    if _default_engine is None:
        _default_engine = StockModel(verbose=verbose)

    return _default_engine

# CLI quick test
if __name__ == "__main__":
    import argparse, pprint
    
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", required=True)
    args = parser.parse_args()
    eng = get_default_engine(verbose=True)
    out = eng.analyze_stock(args.symbol, fetch_if_missing=True)
    pprint.pprint(out, indent=2)
