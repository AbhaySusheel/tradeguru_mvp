import sqlite3

DB = "app.db"

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

print("✅ 'positions' table created successfully in app.db")
