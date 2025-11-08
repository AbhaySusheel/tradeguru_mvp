# backend/routes/positions.py
from fastapi import APIRouter
import sqlite3

router = APIRouter()

@router.get("/positions")
def get_positions():
    conn = sqlite3.connect("app.db")
    c = conn.cursor()
    c.execute("""
        SELECT id, symbol, entry_price, entry_ts, size, status, target_pct, stop_pct, exit_price, exit_ts
        FROM positions
        ORDER BY id DESC
    """)
    rows = c.fetchall()
    conn.close()

    keys = ["id", "symbol", "entry_price", "entry_ts", "size", "status",
            "target_pct", "stop_pct", "exit_price", "exit_ts"]
    return [dict(zip(keys, row)) for row in rows]
