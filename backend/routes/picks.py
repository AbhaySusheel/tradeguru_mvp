# backend/routes/picks.py
import os
import sqlite3
from datetime import datetime as dt
from fastapi import APIRouter, HTTPException
from scheduler import db_conn
from utils.notifier import send_push

router = APIRouter()

EXPO_PUSH_TOKEN = os.getenv("EXPO_PUSH_TOKEN", "")
FCM_TEST_TOKEN = os.getenv("TEST_DEVICE_TOKEN", "")

@router.get("/top-picks")
def top_picks(limit: int = 10):
    """
    Return latest top picks from DB.
    Excludes positions already OPEN.
    Safe: returns data even if scheduler is still running.
    """
    try:
        conn = db_conn()
        c = conn.cursor()
        c.execute("""
            SELECT tp.symbol, tp.last_price, tp.score, tp.intraday_pct, tp.ts
            FROM top_picks tp
            WHERE tp.symbol NOT IN (SELECT symbol FROM all_stocks WHERE 1=0)  -- keep structure safe
            ORDER BY tp.ts DESC, tp.score DESC
            LIMIT ?
        """, (limit,))
        rows = c.fetchall()
        conn.close()

        picks = [
            {
                "symbol": r[0],
                "price": r[1],
                "score": r[2],
                "change": r[3],
                "ts": r[4]
            }
            for r in rows
        ]
        return {"top_picks": picks}

    except Exception as e:
        print("⚠️ Error fetching top picks:", e)
        return {"top_picks": []}

@router.get("/all-stocks")
def all_stocks(search: str = "", limit: int = 100, offset: int = 0):
    conn = sqlite3.connect("app.db")
    c = conn.cursor()
    if search:
        q = f"%{search.upper()}%"
        c.execute("SELECT symbol,last_price,score,intraday_pct,ts FROM all_stocks WHERE symbol LIKE ? ORDER BY score DESC LIMIT ? OFFSET ?",
                  (q, limit, offset))
    else:
        c.execute("SELECT symbol,last_price,score,intraday_pct,ts FROM all_stocks ORDER BY score DESC LIMIT ? OFFSET ?", (limit, offset))
    rows = c.fetchall()
    conn.close()
    return [{"symbol": r[0], "price": r[1], "score": r[2], "change": r[3], "ts": r[4]} for r in rows]


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

    title = f"Bought {symbol}"
    body = f"Opened @ ₹{price:.2f} | Target {target}% Stop {stop}%"
    if FCM_TEST_TOKEN:
        send_push(FCM_TEST_TOKEN, title, body)
    if EXPO_PUSH_TOKEN:
        send_push(EXPO_PUSH_TOKEN, title, body)

    

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

    pl_text = ""
    if entry_price:
        pl_pct = (price - entry_price) / entry_price * 100
        pl_text = f" Realized P/L: {pl_pct:.2f}%"

    title = f"Sold {symbol}"
    body = f"Closed @ ₹{price:.2f}.{pl_text}"
    if FCM_TEST_TOKEN:
        send_push(FCM_TEST_TOKEN, title, body)
    if EXPO_PUSH_TOKEN:
        send_push(EXPO_PUSH_TOKEN, title, body)

    return {"status": "ok", "message": "Position closed"}
