# backend/utils/positions.py
import sqlite3
from datetime import datetime as dt

DB = "app.db"

def ensure_positions_table():
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("""
    CREATE TABLE IF NOT EXISTS positions (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      symbol TEXT,
      entry_price REAL,
      entry_ts TEXT,
      size REAL,
      status TEXT,
      target_pct REAL,
      stop_pct REAL,
      exit_price REAL,
      exit_ts TEXT
    );
    """)
    conn.commit()
    conn.close()

def open_position(symbol, entry_price, size=1.0, target_pct=5.0, stop_pct=1.5):
    ensure_positions_table()
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    ts = dt.utcnow().isoformat()
    c.execute(
        "INSERT INTO positions(symbol,entry_price,entry_ts,size,status,target_pct,stop_pct) VALUES (?,?,?,?,?,?,?)",
        (symbol, entry_price, ts, size, "OPEN", target_pct, stop_pct)
    )
    conn.commit()
    conn.close()

def close_position(symbol, exit_price):
    ensure_positions_table()
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    ts = dt.utcnow().isoformat()
    # closes all open positions for symbol (you can adapt to close by id later)
    c.execute("UPDATE positions SET exit_price=?, exit_ts=?, status='CLOSED' WHERE symbol=? AND status='OPEN'",
              (exit_price, ts, symbol))
    conn.commit()
    conn.close()

def list_open_positions():
    ensure_positions_table()
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("SELECT id, symbol, entry_price, entry_ts, size, target_pct, stop_pct FROM positions WHERE status='OPEN'")
    rows = c.fetchall()
    conn.close()
    # rows: list of tuples (id, symbol, entry_price, entry_ts, size, target_pct, stop_pct)
    return rows
