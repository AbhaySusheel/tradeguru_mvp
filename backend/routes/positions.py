# backend/routes/positions.py
import os
import sqlite3
from fastapi import APIRouter, HTTPException, Header, Depends

router = APIRouter()
DB = "app.db"

API_KEY = os.getenv("API_KEY", "")

def require_api_key(x_api_key: str | None = Header(None)):
    if not API_KEY:
        return True
    if x_api_key != API_KEY:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")
    return True

def db_connect():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn

@router.get("/positions", dependencies=[Depends(require_api_key)])
def list_positions():
    conn = db_connect()
    c = conn.cursor()

    c.execute("""
        SELECT
            id,
            symbol,
            entry_price,
            predicted_max,
            status,
            soft_stop_pct,
            hard_stop_pct,
            sell_price,
            created_at,
            closed_at
        FROM positions
        ORDER BY id DESC
    """)
    rows = c.fetchall()

    result = []
    for r in rows:
        rec = dict(r)

        if rec["status"] == "OPEN":
            cc = conn.cursor()
            cc.execute("SELECT last_price FROM all_stocks WHERE symbol=?", (rec["symbol"],))
            cur = cc.fetchone()
            if cur:
                current = cur[0]
                rec["current_price"] = current
                rec["unrealized_pct"] = round(
                    (current - rec["entry_price"]) / rec["entry_price"] * 100, 2
                )
        else:
            if rec["sell_price"]:
                rec["realized_pct"] = round(
                    (rec["sell_price"] - rec["entry_price"]) / rec["entry_price"] * 100, 2
                )

        result.append(rec)

    conn.close()
    return {
        "open": [r for r in result if r["status"] == "OPEN"],
        "closed": [r for r in result if r["status"] == "CLOSED"],
    }
