# backend/routes/buy_stock.py
"""
Buy Stock API
- Inserts a new position into the database
- Automatically triggers monitoring for profit/loss notifications
"""

import sqlite3
import asyncio
import logging
from fastapi import APIRouter, HTTPException, Request
from datetime import datetime as dt

from scheduler import db_conn, try_db_write

router = APIRouter()
logger = logging.getLogger("buy_stock")
logger.setLevel(logging.INFO)
if not logger.handlers:
    ch = logging.StreamHandler()
    ch.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(ch)

# Default stop-loss percentages
DEFAULT_SOFT_STOP = 3.0   # 3%
DEFAULT_HARD_STOP = 7.0   # 7%

@router.post("/buy")
async def buy_stock(request: Request):
    """
    Request JSON example:
    {
        "symbol": "RELIANCE",
        "entry_price": 2500,
        "predicted_max": 2700
    }
    """
    data = await request.json()
    symbol = data.get("symbol")
    entry_price = data.get("entry_price")
    predicted_max = data.get("predicted_max", None)

    if not symbol or entry_price is None:
        raise HTTPException(status_code=400, detail="symbol and entry_price required")

    symbol_ns = symbol if symbol.endswith(".NS") else symbol + ".NS"
    ts_val = dt.utcnow().isoformat()

    # Insert into DB
    def insert_position():
        conn = db_conn()
        c = conn.cursor()
        c.execute("""CREATE TABLE IF NOT EXISTS positions(
                     id INTEGER PRIMARY KEY AUTOINCREMENT,
                     symbol TEXT,
                     entry_price REAL,
                     predicted_max REAL,
                     status TEXT,
                     soft_stop_pct REAL,
                     hard_stop_pct REAL,
                     profit_alerts_sent TEXT,
                     stop_alerts_sent TEXT,
                     created_at TEXT
                     )""")
        c.execute("""INSERT INTO positions(
                     symbol, entry_price, predicted_max, status, soft_stop_pct, hard_stop_pct,
                     profit_alerts_sent, stop_alerts_sent, created_at
                     ) VALUES(?,?,?,?,?,?,?,?,?)""",
                  (symbol_ns, entry_price, predicted_max, "OPEN",
                   DEFAULT_SOFT_STOP, DEFAULT_HARD_STOP, "", "", ts_val))
        conn.commit()
        conn.close()

    success = try_db_write(insert_position)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to insert position")

    logger.info(f"✅ Added new position: {symbol_ns} @ {entry_price}")

    # Trigger immediate monitoring for this stock safely
    async def monitor_new_position():
        from scheduler import monitor_position
        await monitor_position((symbol_ns, entry_price, predicted_max, "OPEN", DEFAULT_SOFT_STOP, DEFAULT_HARD_STOP, "", ""))

    asyncio.create_task(monitor_new_position())

    return {"ok": True, "symbol": symbol_ns, "entry_price": entry_price, "status": "OPEN"}
