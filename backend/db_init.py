import os
import json
import sqlite3
import firebase_admin
from firebase_admin import credentials, firestore, initialize_app

# -----------------------------
# ✅ FIRESTORE GLOBAL INITIALIZATION
# -----------------------------
# Initialize Firestore client globally (only once)
if not firebase_admin._apps:
    cred_json = os.getenv("FIREBASE_KEY_JSON")
    if cred_json:
        cred = credentials.Certificate(json.loads(cred_json))
        print("✅ Firebase initialized from FIREBASE_KEY_JSON environment variable")
    else:
        print("⚠️ FIREBASE_KEY_JSON not found, using Application Default Credentials")
        cred = credentials.ApplicationDefault()
    initialize_app(cred)
else:
    print("✅ Firebase already initialized")

db_firestore = firestore.client()


# -----------------------------
# ✅ SQLITE DATABASE INITIALIZATION
# -----------------------------
def init_db():
    conn = sqlite3.connect("app.db")
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
    )
    """)

    # top_picks history (snapshot of latest picks)
    c.execute("""
    CREATE TABLE IF NOT EXISTS top_picks (
      ts TEXT,
      symbol TEXT,
      last_price REAL,
      score REAL,
      intraday_pct REAL
    )
    """)

    # positions (OPEN/CLOSED trades)
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
    )
    """)

    # notifications (push/log messages)
    c.execute("""
    CREATE TABLE IF NOT EXISTS notifications (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      ts TEXT,
      type TEXT,
      symbol TEXT,
      title TEXT,
      body TEXT
    )
    """)

    # helper to prevent repeated alerts
    c.execute("""
    CREATE TABLE IF NOT EXISTS notification_cooldown (
      symbol TEXT PRIMARY KEY,
      last_warn_ts TEXT
    )
    """)

    conn.commit()
    conn.close()
    print("✅ Database initialized successfully.")


if __name__ == "__main__":
    init_db()
