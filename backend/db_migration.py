# backend/db_migration.py
import sqlite3
from datetime import datetime as dt
import os

DB = os.getenv("DB_PATH", "app.db")

def db_conn():
    return sqlite3.connect(DB, check_same_thread=False)

def add_missing_columns():
    conn = db_conn()
    c = conn.cursor()
    # Add columns only if they don't exist
    c.execute("PRAGMA table_info(positions)")
    existing_cols = [col[1] for col in c.fetchall()]
    
    if 'predicted_max' not in existing_cols:
        c.execute("ALTER TABLE positions ADD COLUMN predicted_max REAL")
    if 'profit_alerts_sent' not in existing_cols:
        c.execute("ALTER TABLE positions ADD COLUMN profit_alerts_sent TEXT DEFAULT ''")
    if 'stop_alerts_sent' not in existing_cols:
        c.execute("ALTER TABLE positions ADD COLUMN stop_alerts_sent TEXT DEFAULT ''")
    if 'soft_stop_pct' not in existing_cols:
        c.execute("ALTER TABLE positions ADD COLUMN soft_stop_pct REAL DEFAULT 3.0")
    if 'hard_stop_pct' not in existing_cols:
        c.execute("ALTER TABLE positions ADD COLUMN hard_stop_pct REAL DEFAULT 5.0")
    
    conn.commit()
    conn.close()
    print("✅ DB migration completed")

if __name__ == "__main__":
    add_missing_columns()
