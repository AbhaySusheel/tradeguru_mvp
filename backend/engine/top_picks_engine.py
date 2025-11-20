# backend/engine/top_picks_engine.py
"""
Top Picks Engine (Final Version)
- Fully uses StockModel (ML + Utils Engine)
- 65% ML + 35% Engine Score
- Fetches live OHLCV from market utils
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


async def analyze_one(symbol: str) -> Dict[str, Any]:
    """
    Async single-symbol analysis:
    - fetch intraday OHLCV
    - run ML + Engine via StockModel
    """
    try:
        df = await asyncio.to_thread(fetch_intraday, symbol, "1d", "5m")
        if df is None or df.empty:
            return {"ok": False, "symbol": symbol, "error": "no_data"}

        result = await asyncio.to_thread(MODEL.analyze_stock, df, False)
        return result

    except Exception as e:
        print(f"[TopPicks] Error for {symbol}: {e}")
        traceback.print_exc()
        return {"ok": False, "symbol": symbol, "error": str(e)}


async def generate_top_picks(symbols: List[str], limit: int = 10) -> List[Dict[str, Any]]:
    """
    Main top-picks generator.
    - Runs 20–50 symbols concurrently
    - Uses combined_score = 65% ML + 35% Engine
    """
    tasks = [analyze_one(sym) for sym in symbols]
    results = await asyncio.gather(*tasks)

    # Keep only successful results
    clean = [r for r in results if r.get("ok")]

    # Sort by combined_score (descending)
    clean.sort(key=lambda x: x.get("combined_score", 0), reverse=True)

    return clean[:limit]
