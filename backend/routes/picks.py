# backend/routes/picks.py

import os
import math
import asyncio
import logging
from datetime import datetime as dt
from fastapi import APIRouter, HTTPException, BackgroundTasks

from scheduler import load_universe, run_top_picks_once
from models.stock_model import get_default_engine
from data.top_picks_cache import get_top_picks_cache


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
async def top_picks():
    cached = get_top_picks_cache()

    if not cached["data"]:
        raise HTTPException(
            status_code=503,
            detail="Top picks not ready yet"
        )

    return clean_for_json({
        "status": "success",
        "interval": cached.get("interval", "5m"),
        "timestamp": cached.get("timestamp"),
        "returned": len(cached["data"]),
        "top_picks": cached["data"]
    })

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
