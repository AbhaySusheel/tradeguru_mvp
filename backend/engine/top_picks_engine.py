# backend/engine/top_picks_engine.py
"""
Top Picks Engine (Final Version)
- Uses StockModel analyze_stock with force_symbol when passing DataFrame
- combined_score default weights are already ml:0.35, engine:0.65 inside StockModel
- debug logging included
"""

import asyncio
import traceback
import logging
from typing import List, Dict, Any

from models.stock_model import get_default_engine
from utils.market import fetch_intraday

logger = logging.getLogger("top_picks_engine")
logger.setLevel(logging.INFO)
if not logger.handlers:
    ch = logging.StreamHandler()
    ch.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(ch)

# Shared model instance
MODEL = get_default_engine(verbose=False)

async def analyze_one(symbol: str) -> Dict[str, Any]:
    """
    Fetch OHLCV -> pass DataFrame to StockModel.analyze_stock using force_symbol
    This guarantees symbol correctness in result.
    """
    sym_plain = symbol.replace(".NS", "") if symbol.endswith(".NS") else symbol
    try:
        # fetch data in thread
        df = await asyncio.to_thread(fetch_intraday, symbol if symbol.endswith(".NS") else symbol + ".NS", "1d", "5m")
        if df is None or getattr(df, "empty", True):
            logger.debug(f"[analyze_one] No data for {symbol}")
            return {"ok": False, "symbol": sym_plain, "error": "no_data"}
        # call analyze_stock in thread; pass force_symbol to ensure name
        # args: (symbol_or_df, fetch_if_missing, ml_only, combine_weights, return_raw, force_symbol)
        result = await asyncio.to_thread(MODEL.analyze_stock, df, False, False, None, False, sym_plain)
        if result and result.get("ok"):
            return result
        else:
            logger.debug(f"[analyze_one] analyze_stock failed for {symbol}: {result}")
            return {"ok": False, "symbol": sym_plain, "error": "analyze_failed"}
    except Exception as e:
        logger.error(f"[analyze_one] Error for {symbol}: {e}")
        traceback.print_exc()
        return {"ok": False, "symbol": sym_plain, "error": str(e)}

async def generate_top_picks(symbols: List[str], limit: int = 10) -> List[Dict[str, Any]]:
    """
    Run concurrent analyze_one tasks and return top `limit` sorted by combined_score desc.
    """
    # cap concurrency to avoid API rate limit issues - simple gather but caller should control concurrency
    tasks = [analyze_one(sym) for sym in symbols]
    results = await asyncio.gather(*tasks, return_exceptions=False)

    clean = [r for r in results if r.get("ok")]
    # ensure numeric combined_score present
    for r in clean:
        r["combined_score"] = float(r.get("combined_score") or 0.0)

    clean.sort(key=lambda x: x.get("combined_score", 0), reverse=True)
    logger.info(f"[generate_top_picks] Generated {len(clean)} valid picks, returning top {limit}")
    return clean[:limit]
