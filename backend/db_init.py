# backend/db_init.py
import sqlite3

DB = "app.db"
conn = sqlite3.connect(DB)
c = conn.cursor()

# all_stocks keeps latest snapshot per symbol
c.execute("""
CREATE TABLE IF NOT EXISTS all_stocks (
  symbol TEXT PRIMARY KEY,
  last_price REAL,
  intraday_pct REAL,
  ma_diff REAL,
  vol_ratio REAL,
  rsi REAL,
  score REAL,
  ts TEXT
);
""")

# top_picks history (if not present)
c.execute("""
CREATE TABLE IF NOT EXISTS top_picks (
  ts TEXT,
  symbol TEXT,
  last_price REAL,
  score REAL,
  intraday_pct REAL
);
""")

# positions table already exists but ensure schema (OPEN/CLOSED)
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

# notifications history (optional)
c.execute("""
CREATE TABLE IF NOT EXISTS notifications (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts TEXT,
  type TEXT,
  symbol TEXT,
  title TEXT,
  body TEXT
);
""")

c.execute("""
CREATE TABLE IF NOT EXISTS notifications (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts TEXT,
  type TEXT,
  symbol TEXT,
  note TEXT
);
""")

# Add a helper table to track last warning per position (simpler)
c.execute("""
CREATE TABLE IF NOT EXISTS notification_cooldown (
  symbol TEXT PRIMARY KEY,
  last_warn_ts TEXT
);
""")


conn.commit()
conn.close()
print("DB initialized")
