# backend/routes/picks.py
import os
import math
import sqlite3
import asyncio
from datetime import datetime as dt
from fastapi import APIRouter, HTTPException, BackgroundTasks

from scheduler import load_universe, run_top_picks_once
from utils.notifier import send_push
from firebase_admin import firestore
from google.cloud.firestore_v1.base_document import DocumentSnapshot
from google.api_core.exceptions import DeadlineExceeded
from google.auth.exceptions import DefaultCredentialsError

from models.stock_model import get_default_engine

ROUTE_BATCH_SIZE = int(os.getenv("BATCH_SIZE", "20"))
SYMBOL_TIMEOUT_SEC = float(os.getenv("SYMBOL_TIMEOUT_SEC", "10.0"))
MAX_SYMBOLS = int(os.getenv("MAX_SYMBOLS", "50"))
DEFAULT_LIMIT = int(os.getenv("TOP_N", "10"))

router = APIRouter()

try:
    DB_FIRESTORE = firestore.client()
except Exception:
    DB_FIRESTORE = None

def _clean_number(x):
    if isinstance(x, float):
        if math.isnan(x) or math.isinf(x):
            return 0.0
        return x
    return x

def clean_for_json(obj):
    if isinstance(obj, float):
        return _clean_number(obj)
    if isinstance(obj, list):
        return [clean_for_json(i) for i in obj]
    if isinstance(obj, dict):
        return {k: clean_for_json(v) for k, v in obj.items()}
    return obj

_engine_singleton = None

def get_engine(verbose: bool = False):
    global _engine_singleton
    if _engine_singleton is None:
        _engine_singleton = get_default_engine(verbose=verbose)
    return _engine_singleton

async def _analyze_symbol_async(symbol: str, semaphore: asyncio.Semaphore, timeout: float = SYMBOL_TIMEOUT_SEC):
    engine = get_engine()
    # expecting symbol maybe 'TCS' or 'TCS.NS'
    sym = str(symbol).strip().upper()
    fetch_sym = sym if sym.endswith(".NS") else sym + ".NS"

    # combine weights: ml 35% + engine 65%
    combine_weights = {"ml": 0.35, "engine": 0.65}

    async with semaphore:
        try:
            loop = asyncio.get_running_loop()
            # fetch df then call analyze_stock with df and force_symbol
            from utils.market import fetch_intraday
            df = await asyncio.to_thread(fetch_intraday, fetch_sym, "1d", "5m")
            if df is None or df.empty:
                print(f"⚠️ No data for {sym}")
                return None
            # call analyze_stock in threadpool with combine_weights and force_symbol
            def run():
                return engine.analyze_stock(df, False, False, combine_weights, False, sym.replace(".NS", ""))
            result = await asyncio.wait_for(loop.run_in_executor(None, run), timeout=timeout)
            if not result or not result.get("ok"):
                return None
            # normalize numeric fields
            result["combined_score"] = float(result.get("combined_score") or 0.0)
            result["ml_buy_prob"] = float(result.get("ml_buy_prob") or 0.0)
            result["engine_score"] = float(result.get("engine_score") or 0.0)
            result["buy_confidence"] = float(result.get("buy_confidence") or 0.0)
            result["last_price"] = float(result.get("last_price") or 0.0)
            # ensure proper symbol naming
            result["symbol"] = str(result.get("symbol")).upper().replace(".NS", "")
            return result
        except asyncio.TimeoutError:
            print(f"⚠️ Timeout analyzing {symbol}")
            return None
        except Exception as e:
            print(f"❌ Error analyzing {symbol}: {e}")
            return None

@router.get("/top-picks")
async def top_picks(limit: int = DEFAULT_LIMIT, max_symbols: int = MAX_SYMBOLS, batch_size: int = ROUTE_BATCH_SIZE, timeout_sec: float = SYMBOL_TIMEOUT_SEC):
    limit = int(limit) if limit else DEFAULT_LIMIT
    if limit <= 0:
        raise HTTPException(status_code=400, detail="limit must be > 0")
    batch_size = int(batch_size) if batch_size > 0 else ROUTE_BATCH_SIZE
    timeout_sec = float(timeout_sec) if timeout_sec > 0 else SYMBOL_TIMEOUT_SEC
    max_symbols = int(max_symbols) if max_symbols > 0 else MAX_SYMBOLS

    universe = load_universe()
    if not universe:
        raise HTTPException(status_code=503, detail="Universe unavailable")

    universe = universe[:max_symbols]
    sem = asyncio.Semaphore(batch_size)

    tasks = [_analyze_symbol_async(sym, sem, timeout_sec) for sym in universe]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    valid = []
    for r in results:
        if isinstance(r, Exception):
            print("Analysis exception:", r)
            continue
        if r and r.get("ok"):
            valid.append(r)

    if not valid:
        raise HTTPException(status_code=502, detail="No valid analysis results")

    valid_sorted = sorted(valid, key=lambda x: x.get("combined_score", 0.0), reverse=True)
    top = valid_sorted[:limit]
    ts = dt.utcnow().isoformat()

    response_picks = []
    for t in top:
        item = {
            "symbol": t.get("symbol"),
            "last_price": _clean_number(t.get("last_price", 0.0)),
            "combined_score": _clean_number(t.get("combined_score", 0.0)),
            "ml_buy_prob": _clean_number(t.get("ml_buy_prob", 0.0)),
            "engine_score": _clean_number(t.get("engine_score", 0.0)),
            "buy_confidence": _clean_number(t.get("buy_confidence", 0.0)),
            "trade_plan": t.get("trade_plan", {}),
            "features": t.get("features", {}).get("core", {}),
            "explanation": t.get("explanation", "")
        }
        response_picks.append(clean_for_json(item))

    return {
        "status": "success",
        "timestamp": ts,
        "universe_count": len(universe),
        "returned": len(response_picks),
        "top_picks": response_picks
    }

@router.get("/top-picks/cached")
async def top_picks_cached(limit: int = DEFAULT_LIMIT):
    if DB_FIRESTORE is None:
        raise HTTPException(status_code=503, detail="Firestore client not initialized")
    try:
        doc_ref = DB_FIRESTORE.collection("top_picks").document("latest")
        doc: DocumentSnapshot = await asyncio.to_thread(doc_ref.get, None)
        if not doc.exists:
            return {"status": "ok", "top_picks": [], "message": "No cached top picks found"}
        data = doc.to_dict().get("data", [])[:limit]
        return {"status": "ok", "top_picks": clean_for_json(data)}
    except DeadlineExceeded:
        raise HTTPException(status_code=504, detail="Firestore read timeout")
    except DefaultCredentialsError as e:
        raise HTTPException(status_code=500, detail=f"Firestore auth error: {e}")
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Failed to read cached top picks: {e}")

# preserved buy/sell/update endpoints unchanged...
@router.post("/buy")
def buy_stock(payload: dict):
    symbol = payload.get("symbol")
    price = payload.get("price")
    size = payload.get("size", 1.0)
    target = payload.get("target", 5.0)
    stop = payload.get("stop", 1.5)
    if not symbol or not price:
        raise HTTPException(status_code=400, detail="symbol and price required")
    ts = dt.utcnow().isoformat()
    conn = sqlite3.connect("app.db")
    c = conn.cursor()
    c.execute("INSERT INTO positions(symbol,entry_price,entry_ts,size,status,target_pct,stop_pct) VALUES (?,?,?,?,?,?,?)",
              (symbol, price, ts, size, "OPEN", target, stop))
    conn.commit()
    conn.close()
    return {"status": "ok", "message": "Position opened"}

@router.post("/sell")
def sell_stock(payload: dict):
    symbol = payload.get("symbol")
    price = payload.get("price")
    if not symbol or not price:
        raise HTTPException(status_code=400, detail="symbol and price required")
    ts = dt.utcnow().isoformat()
    conn = sqlite3.connect("app.db")
    c = conn.cursor()
    c.execute("SELECT entry_price FROM positions WHERE symbol=? AND status='OPEN' ORDER BY id DESC LIMIT 1", (symbol,))
    row = c.fetchone()
    entry_price = row[0] if row else None
    c.execute("UPDATE positions SET exit_price=?,exit_ts=?,status='CLOSED' WHERE symbol=? AND status='OPEN'",
              (price, ts, symbol))
    conn.commit()
    conn.close()
    return {"status": "ok", "message": "Position closed"}

@router.get("/update-top-picks")
async def update_top_picks(token: str, background_tasks: BackgroundTasks):
    CRON_SECRET = os.getenv("CRON_SECRET", "my_secret_token")
    if token != CRON_SECRET:
        raise HTTPException(status_code=401, detail="Invalid token")
    try:
        background_tasks.add_task(run_top_picks_once)
        return {"status": "ok", "message": "Top picks update STARTED successfully in background."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to start task: {e}")
