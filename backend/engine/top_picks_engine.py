# backend/engine/top_picks_engine.py
"""
Top Picks Engine (Final Version)
- Fully uses StockModel (ML + Utils Engine)
- combined_score = ml*0.35 + engine*0.65
- Fetches live OHLCV from utils.market
- Async concurrency for speed
- Returns clean sorted picks
"""

import asyncio
import traceback
from typing import List, Dict, Any

from models.stock_model import get_default_engine
from utils.market import fetch_intraday

# Shared model instance
MODEL = get_default_engine(verbose=False)

# override weights: ml 35% engine 65%
COMBINE_WEIGHTS = {"ml": 0.35, "engine": 0.65}


async def analyze_one(symbol: str) -> Dict[str, Any]:
    """
    Async single-symbol analysis:
    - fetch intraday OHLCV (symbol should be either 'TCS' or 'TCS.NS' or similar)
    - run ML + Engine via StockModel using combine_weights override and force_symbol
    """
    try:
        # ensure symbol string
        sym = str(symbol).strip().upper()
        # require .NS for fetch_intraday; keep force_symbol without .NS for readability/storage
        fetch_sym = sym if sym.endswith(".NS") else sym + ".NS"
        df = await asyncio.to_thread(fetch_intraday, fetch_sym, "1d", "5m")
        if df is None or df.empty:
            return {"ok": False, "symbol": sym.replace(".NS", ""), "error": "no_data"}

        # run model on DataFrame in threadpool, pass combine_weights and force_symbol
        # signature: analyze_stock(symbol_or_df, fetch_if_missing=True, ml_only=False, combine_weights=None, return_raw=False, force_symbol=None)
        coro = lambda: MODEL.analyze_stock(df, False, False, COMBINE_WEIGHTS, False, sym.replace(".NS", ""))
        result = await asyncio.to_thread(coro)

        # ensure result normalized
        if not result or not result.get("ok"):
            return {"ok": False, "symbol": sym.replace(".NS", ""), "error": result.get("error", "analysis_failed") if isinstance(result, dict) else "analysis_failed"}

        # make sure symbol normalized in result
        result["symbol"] = str(result.get("symbol", sym.replace(".NS", ""))).upper()

        return result

    except Exception as e:
        print(f"[TopPicks] Error for {symbol}: {e}")
        traceback.print_exc()
        return {"ok": False, "symbol": str(symbol).upper().replace(".NS", ""), "error": str(e)}


async def generate_top_picks(symbols: List[str], limit: int = 10) -> List[Dict[str, Any]]:
    """
    Main top-picks generator.
    - Runs many symbols concurrently (limited by event loop / HTTP function caller)
    - Uses combined_score = 35% ML + 65% Engine (via COMBINE_WEIGHTS)
    """
    if not symbols:
        return []

    tasks = [analyze_one(sym) for sym in symbols]
    results = await asyncio.gather(*tasks, return_exceptions=False)

    # Keep only successful results
    clean = [r for r in results if isinstance(r, dict) and r.get("ok")]

    # Sort by combined_score (descending)
    clean.sort(key=lambda x: x.get("combined_score", 0.0), reverse=True)

    return clean[:limit]
