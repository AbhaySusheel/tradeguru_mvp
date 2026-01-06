# backend/routes/picks.py

import os
import math
import asyncio
import logging
from datetime import datetime as dt
from fastapi import APIRouter, HTTPException, BackgroundTasks

from scheduler import load_universe, run_top_picks_once
from models.stock_model import get_default_engine

# ---------------- CONFIG ----------------
ROUTE_BATCH_SIZE = int(os.getenv("BATCH_SIZE", "20"))
SYMBOL_TIMEOUT_SEC = float(os.getenv("SYMBOL_TIMEOUT_SEC", "12.0"))
MAX_SYMBOLS = int(os.getenv("MAX_SYMBOLS", "200"))
DEFAULT_LIMIT = int(os.getenv("TOP_N", "10"))

router = APIRouter()

logger = logging.getLogger("routes.picks")
logger.setLevel(logging.INFO)
if not logger.handlers:
    ch = logging.StreamHandler()
    ch.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(ch)

# ---------------- HELPERS ----------------

def _clean_number(x):
    if isinstance(x, float):
        if math.isnan(x) or math.isinf(x):
            return 0.0
        return float(x)
    return x

def clean_for_json(obj):
    if isinstance(obj, float):
        return _clean_number(obj)
    if isinstance(obj, list):
        return [clean_for_json(i) for i in obj]
    if isinstance(obj, dict):
        return {k: clean_for_json(v) for k, v in obj.items()}
    return obj

# ---------------- ENGINE SINGLETON ----------------

_engine_singleton = None

def get_engine(verbose: bool = False):
    global _engine_singleton
    if _engine_singleton is None:
        _engine_singleton = get_default_engine(verbose=verbose)
    return _engine_singleton

# ---------------- CORE ANALYSIS ----------------

async def _analyze_symbol_async(
    symbol: str,
    semaphore: asyncio.Semaphore,
    timeout: float
):
    engine = get_engine()

    async with semaphore:
        try:
            combine_weights = {"ml": 0.35, "engine": 0.65}

            loop = asyncio.get_running_loop()
            task = loop.run_in_executor(
                None,
                engine.analyze_stock,
                symbol,        # symbol
                True,          # fetch_if_missing
                False,         # ml_only
                combine_weights,
                False          # return_raw
            )

            result = await asyncio.wait_for(task, timeout=timeout)

            if not result or not result.get("ok"):
                return None

            # normalize numbers
            for k in [
                "combined_score",
                "ml_buy_prob",
                "engine_score",
                "buy_confidence",
                "last_price"
            ]:
                result[k] = float(result.get(k) or 0.0)

            return result

        except asyncio.TimeoutError:
            logger.warning(f"⏱ Timeout: {symbol}")
            return None
        except Exception as e:
            logger.error(f"❌ Error analyzing {symbol}: {e}")
            return None

# ---------------- ROUTES ----------------

@router.get("/top-picks")
async def top_picks(
    limit: int = DEFAULT_LIMIT,
    max_symbols: int = MAX_SYMBOLS,
    batch_size: int = ROUTE_BATCH_SIZE,
    timeout_sec: float = SYMBOL_TIMEOUT_SEC,
):
    limit = int(limit)
    max_symbols = int(max_symbols)
    batch_size = int(batch_size)
    timeout_sec = float(timeout_sec)

    if limit <= 0:
        raise HTTPException(status_code=400, detail="limit must be > 0")

    universe = load_universe()
    if not universe:
        raise HTTPException(status_code=503, detail="Universe unavailable")

    universe = universe[:max_symbols]

    logger.info(f"🔍 Analyzing {len(universe)} symbols")

    semaphore = asyncio.Semaphore(batch_size)
    tasks = [
        asyncio.create_task(
        _analyze_symbol_async(sym, semaphore, timeout_sec)
        )
        for sym in universe
    ]

    

    valid = []

    for coro in asyncio.as_completed(tasks):
        try:
            r = await coro
            if r and r.get("ok"):
                valid.append(r)
                if len(valid) >= limit * 2:
                    break

        except Exception as e:
            logger.warning(f"Analysis exception: {e}")    

    for task in tasks:
        if not task.done():
            task.cancel()


    if not valid:
        raise HTTPException(status_code=502, detail="No valid analysis results")

    valid.sort(key=lambda x: x.get("combined_score", 0.0), reverse=True)
    top = valid[:limit]

    response = []
    for t in top:
        response.append(clean_for_json({
            "symbol": t["symbol"],
            "last_price": t["last_price"],
            "combined_score": t["combined_score"],
            "ml_buy_prob": t["ml_buy_prob"],
            "engine_score": t["engine_score"],
            "buy_confidence": t["buy_confidence"],
            "trade_plan": t.get("trade_plan", {})
        }))

    return {
        "status": "success",
        "timestamp": dt.utcnow().isoformat(),
        "universe_count": len(universe),
        "returned": len(response),
        "top_picks": response
    }

@router.get("/update-top-picks")
async def update_top_picks(
    token: str,
    background_tasks: BackgroundTasks
):
    CRON_SECRET = os.getenv("CRON_SECRET", "my_secret_token")
    if token != CRON_SECRET:
        raise HTTPException(status_code=401, detail="Invalid token")

    background_tasks.add_task(run_top_picks_once)
    return {
        "status": "ok",
        "message": "Top picks update started"
    }
