# backend/routes/positions.py
import os
import sqlite3
from datetime import datetime as dt
from fastapi import APIRouter, HTTPException, Header, Depends

router = APIRouter()
DB = "app.db"

# Simple API key auth dependency
API_KEY = os.getenv("API_KEY", "")  # set this on Render or in .env

def require_api_key(x_api_key: str | None = Header(None)):
    if not API_KEY:
        # If no API key configured, allow access (useful for local dev)
        return True
    if x_api_key != API_KEY:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")
    return True

# Helper db fn
def db_connect():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn

# List positions (open + closed)
@router.get("/positions", dependencies=[Depends(require_api_key)])
def list_positions():
    conn = db_connect()
    c = conn.cursor()
    c.execute("SELECT id,symbol,entry_price,entry_ts,size,status,target_pct,stop_pct,exit_price,exit_ts FROM positions ORDER BY id DESC")
    rows = c.fetchall()
    result = []
    for r in rows:
        rec = dict(r)
        # add computed fields: unrealized_pct for OPEN, realized_pct for CLOSED
        if rec["status"] == "OPEN":
            cc = conn.cursor()
            cc.execute("SELECT last_price FROM all_stocks WHERE symbol=?", (rec["symbol"],))
            cur = cc.fetchone()
            if cur:
                current = cur[0]
                rec["current_price"] = current
                try:
                    rec["unrealized_pct"] = round((current - rec["entry_price"]) / rec["entry_price"] * 100, 2)
                except Exception:
                    rec["unrealized_pct"] = None
        else:
            if rec["exit_price"] and rec["entry_price"]:
                rec["realized_pct"] = round((rec["exit_price"] - rec["entry_price"]) / rec["entry_price"] * 100, 2)
        result.append(rec)
    conn.close()
    open_positions = [r for r in result if r["status"] == "OPEN"]
    closed_positions = [r for r in result if r["status"] == "CLOSED"]
    return {"open": open_positions, "closed": closed_positions}

# Create (Buy) — frontend calls this to mark a bought stock to monitor
@router.post("/positions", dependencies=[Depends(require_api_key)])
def open_position_api(payload: dict):
    """
    Payload expected:
    { "symbol": "TCS", "price": 1234.5, "size": 1.0, "target_pct": 5.0, "stop_pct": 1.5 }
    price is optional — if not provided backend will use latest last_price from all_stocks
    """
    symbol = payload.get("symbol")
    price = payload.get("price")
    size = float(payload.get("size", 1.0))
    target = float(payload.get("target_pct", 5.0))
    stop = float(payload.get("stop_pct", 1.5))

    if not symbol:
        raise HTTPException(status_code=400, detail="symbol required")

    # get price from all_stocks if not provided
    if price is None:
        conn = db_connect()
        c = conn.cursor()
        c.execute("SELECT last_price FROM all_stocks WHERE symbol=?", (symbol,))
        row = c.fetchone()
        conn.close()
        if row:
            price = row[0]
        else:
            raise HTTPException(status_code=400, detail="price not provided and symbol not found in all_stocks")

    ts = dt.utcnow().isoformat()
    conn = db_connect()
    c = conn.cursor()
    c.execute("INSERT INTO positions(symbol,entry_price,entry_ts,size,status,target_pct,stop_pct) VALUES (?,?,?,?,?,?,?)",
              (symbol, price, ts, size, "OPEN", target, stop))
    conn.commit()
    conn.close()

    # optional: remove it from top_picks view (the top-picks route already excludes open positions)
    return {"status": "ok", "message": f"Position opened for {symbol} @ {price}"}

# Close (Sell) — frontend calls this to close a position
@router.post("/positions/close", dependencies=[Depends(require_api_key)])
def close_position_api(payload: dict):
    """
    Payload: { "symbol": "TCS", "price": 1300.5 }
    If price omitted, current last_price will be used.
    """
    symbol = payload.get("symbol")
    price = payload.get("price")

    if not symbol:
        raise HTTPException(status_code=400, detail="symbol required")

    conn = db_connect()
    c = conn.cursor()

    # fetch entry price of latest open position
    c.execute("SELECT id, entry_price FROM positions WHERE symbol=? AND status='OPEN' ORDER BY id DESC LIMIT 1", (symbol,))
    row = c.fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="No open position for symbol")

    entry_price = row["entry_price"]
    pos_id = row["id"]

    if price is None:
        c.execute("SELECT last_price FROM all_stocks WHERE symbol=?", (symbol,))
        rp = c.fetchone()
        if rp:
            price = rp[0]
        else:
            conn.close()
            raise HTTPException(status_code=400, detail="price not provided and symbol not in all_stocks")

    ts = dt.utcnow().isoformat()
    c.execute("UPDATE positions SET exit_price=?, exit_ts=?, status='CLOSED' WHERE id=?", (price, ts, pos_id))
    conn.commit()
    conn.close()

    pl_pct = None
    try:
        pl_pct = round((price - entry_price) / entry_price * 100, 2)
    except Exception:
        pass

    return {"status": "ok", "message": f"Position closed for {symbol} @ {price}", "realized_pct": pl_pct}
