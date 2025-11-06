# backend/routes/picks.py
from fastapi import APIRouter
import sqlite3

router = APIRouter()

@router.get("/top-picks")
def top_picks(limit: int = 10):
    conn = sqlite3.connect("app.db")
    c = conn.cursor()
    c.execute("SELECT symbol,last_price,score,intraday_pct,ts FROM top_picks ORDER BY ts DESC LIMIT ?", (limit,))
    rows = c.fetchall()
    conn.close()
    return [{"symbol": r[0], "price": r[1], "score": r[2], "change": r[3], "ts": r[4]} for r in rows]

@router.get("/positions")
def get_positions():
    conn = sqlite3.connect("app.db")
    c = conn.cursor()
    c.execute("SELECT id,symbol,entry_price,entry_ts,status,target_pct,stop_pct,exit_price,exit_ts FROM positions ORDER BY id DESC")
    rows = c.fetchall()
    conn.close()
    cols = ["id","symbol","entry_price","entry_ts","status","target_pct","stop_pct","exit_price","exit_ts"]
    return [dict(zip(cols,row)) for row in rows]
