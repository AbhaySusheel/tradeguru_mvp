import os
import json
import joblib
import warnings
import numpy as np
import pandas as pd
import xgboost as xgb

from pathlib import Path
from tqdm import tqdm
from sklearn.preprocessing import StandardScaler
from sklearn.model_selection import train_test_split
from sklearn.metrics import roc_auc_score

warnings.filterwarnings("ignore")

# ---------------- CONFIG ----------------
DATA_PATH = "../data/nse_normalize_2024_to_now.csv"
UNIVERSE_PATH = "../universe_final_with_liquidity.csv"
MODEL_DIR = Path(__file__).parent

MIN_ROWS = 60            # force train
FUTURE_DAYS = 5
RETURN_THRESHOLD = 0.02  # 2%

# ---------------- FEATURES ----------------
FEATURES = [
    "ret_1", "ret_3", "ret_5",
    "vol_5", "vol_10",
    "range_pct",
    "close_vs_sma20",
    "volume_ratio"
]

# ---------------- FEATURE ENGINEERING ----------------
def make_features(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()

    df["ret_1"] = df["Close"].pct_change(1)
    df["ret_3"] = df["Close"].pct_change(3)
    df["ret_5"] = df["Close"].pct_change(5)

    df["vol_5"] = df["Close"].pct_change().rolling(5).std()
    df["vol_10"] = df["Close"].pct_change().rolling(10).std()

    df["range_pct"] = (df["High"] - df["Low"]) / df["Close"]

    df["sma20"] = df["Close"].rolling(20).mean()
    df["close_vs_sma20"] = (df["Close"] - df["sma20"]) / df["Close"]

    df["volume_ratio"] = df["Volume"] / df["Volume"].rolling(20).mean()

    return df.dropna()

def make_label(df: pd.DataFrame) -> pd.Series:
    future = df["Close"].shift(-FUTURE_DAYS)
    ret = (future - df["Close"]) / df["Close"]
    return (ret > RETURN_THRESHOLD).astype(int)

# ---------------- TRAIN SINGLE SYMBOL ----------------
def train_symbol(symbol: str, df: pd.DataFrame):
    if len(df) < MIN_ROWS:
        return None

    df_feat = make_features(df)
    y = make_label(df_feat)

    df_feat = df_feat.iloc[:-FUTURE_DAYS]
    y = y.iloc[:-FUTURE_DAYS]

    if len(y.unique()) < 2:
        # force at least 1 positive
        y.iloc[-1] = 1 - y.iloc[-1]

    X = df_feat[FEATURES]

    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)

    X_train, X_val, y_train, y_val = train_test_split(
        X_scaled, y, test_size=0.25, shuffle=False
    )

    dtrain = xgb.DMatrix(X_train, label=y_train, feature_names=list(FEATURES))
    dval = xgb.DMatrix(X_val, label=y_val, feature_names=list(FEATURES))

    params = {
        "objective": "binary:logistic",
        "eval_metric": "auc",
        "max_depth": 4,
        "eta": 0.05,
        "subsample": 0.9,
        "colsample_bytree": 0.9,
        "seed": 42,
    }

    booster = xgb.train(
        params,
        dtrain,
        num_boost_round=300,
        evals=[(dval, "val")],
        early_stopping_rounds=25,
        verbose_eval=False,
    )

    # quality metric (DO NOT REJECT)
    try:
        auc = roc_auc_score(y_val, booster.predict(dval))
    except:
        auc = 0.5

    return {
        "booster": booster,
        "scaler": scaler,
        "features": FEATURES,
        "best_iteration": booster.best_iteration,
        "metrics": {
            "auc": float(auc),
            "rows": int(len(df)),
            "buy_ratio": float(y.mean())
        }
    }

# ---------------- MAIN ----------------
def main():
    print("📥 Loading universe & data...")

    universe = pd.read_csv(UNIVERSE_PATH)["Symbol"].astype(str).unique()
    data = pd.read_csv(DATA_PATH)

    trained = 0

    for sym in tqdm(universe, desc="🚀 Training PRO models"):
        sdf = data[data["Symbol"] == sym]
        if sdf.empty:
            continue

        bundle = train_symbol(sym, sdf)
        if bundle is None:
            continue

        joblib.dump(
            bundle,
            MODEL_DIR / f"xgb_buyprob_{sym}.joblib"
        )
        trained += 1

    print("\n✅ TRAINING COMPLETE")
    print(f"📦 Models trained : {trained}")
    print(f"📁 Saved in       : {MODEL_DIR}")

if __name__ == "__main__":
    main()
