# backend/scheduler.py
"""
TradeGuru Async Scheduler - Updated for engine-weighted combined_score
Saves top picks to Firestore, updates all_stocks table and sends notifications.
"""

import os
import time
import sqlite3
import asyncio
import json
import firebase_admin
from firebase_admin import credentials, firestore
from datetime import datetime as dt, timedelta
from apscheduler.schedulers.background import BackgroundScheduler

from engine.top_picks_engine import generate_top_picks
from models.stock_model import get_default_engine
from utils.positions import open_position, close_position, list_open_positions
from utils.notifier import send_push
from utils.market import fetch_intraday, compute_features
from utils.score import score_from_features

# ----------------------- CONFIG -----------------------
DB = os.getenv("DB_PATH", "app.db")
BATCH_SIZE = int(os.getenv("BATCH_SIZE", "40"))
BATCH_DELAY = float(os.getenv("BATCH_DELAY_SEC", "3.0"))
TOP_N = int(os.getenv("TOP_N", "10"))
TOPPICKS_INTERVAL_MIN = int(os.getenv("TOPPICKS_INTERVAL_MIN", "15"))
MONITOR_INTERVAL_MIN = int(os.getenv("MONITOR_INTERVAL_MIN", "2"))
FCM_TEST_TOKEN = os.getenv("TEST_DEVICE_TOKEN", "")
BUY_THRESHOLD = float(os.getenv("BUY_THRESHOLD", "0.70"))   # combined_score >= this -> send BUY push
ALERT_THRESHOLD = float(os.getenv("ALERT_THRESHOLD", "0.60")) # combined_score >= this -> notify as interesting

_PRICE_CACHE = {}
CACHE_TTL = timedelta(seconds=int(os.getenv("PRICE_CACHE_TTL_SEC", "90")))

# ----------------------- FIREBASE INIT -----------------------
if not firebase_admin._apps:
    json_creds = os.getenv("FIREBASE_CREDENTIALS_JSON")
    try:
        if json_creds:
            cred = credentials.Certificate(json.loads(json_creds))
            firebase_admin.initialize_app(cred)
        else:
            cred = credentials.Certificate("firebase_key.json")
            firebase_admin.initialize_app(cred)
        print("✅ Firebase initialized")
    except Exception as e:
        print("❌ Firebase init failed:", e)

db_firestore = firestore.client()

# ----------------------- DB HELPERS -----------------------
def db_conn():
    return sqlite3.connect(DB, check_same_thread=False)

def try_db_write(func, *args, retries=2, **kwargs):
    for attempt in range(1, retries+1):
        try:
            func(*args, **kwargs)
            return True
        except sqlite3.OperationalError as e:
            if "locked" in str(e).lower():
                print(f"⚠️ DB locked, retrying ({attempt}/{retries})...")
                time.sleep(0.1 * attempt)
            else:
                print("❌ DB write error:", e)
                break
    return False

def ensure_all_stocks_table():
    conn = db_conn()
    c = conn.cursor()
    c.execute("""
      CREATE TABLE IF NOT EXISTS all_stocks(
        symbol TEXT PRIMARY KEY, last_price REAL, intraday_pct REAL,
        ma_diff REAL, vol_ratio REAL, rsi REAL, score REAL, ts TEXT
      )
    """)
    conn.commit()
    conn.close()

def upsert_all_stock(s):
    def _write():
        conn = db_conn()
        c = conn.cursor()
        c.execute("""
          INSERT INTO all_stocks(symbol,last_price,intraday_pct,ma_diff,vol_ratio,rsi,score,ts)
          VALUES (?,?,?,?,?,?,?,?)
          ON CONFLICT(symbol) DO UPDATE SET
            last_price=excluded.last_price,
            intraday_pct=excluded.intraday_pct,
            ma_diff=excluded.ma_diff,
            vol_ratio=excluded.vol_ratio,
            rsi=excluded.rsi,
            score=excluded.score,
            ts=excluded.ts
        """, (s['symbol'], s['last_price'], s['intraday_pct'],
              s.get('ma_diff',0), s.get('vol_ratio',0),
              s.get('rsi',50), s['score'], s['ts']))
        conn.commit()
        conn.close()
    success = try_db_write(_write)
    if not success:
        print(f"⚠️ Skipping DB write for {s.get('symbol')} due to locked DB")

# ----------------------- LOAD UNIVERSE -----------------------
def load_universe(csv_path=os.path.join("backend", "tickers.csv")):
    try:
        from nsetools import Nse
        nse = Nse()
        print("🌐 Fetching live NSE symbols via nsetools...")
        all_stock_codes = nse.get_stock_codes()
        universe = []
        if isinstance(all_stock_codes, dict):
            universe = [sym + ".NS" for sym in all_stock_codes.keys() if sym != 'SYMBOL']
        elif isinstance(all_stock_codes, list):
            universe = [sym + ".NS" for sym in all_stock_codes if sym != 'SYMBOL']
        if universe:
            universe = universe[:200]
            print(f"✅ {len(universe)} symbols loaded for top picks")
            return universe
        else:
            raise ValueError("No symbols returned from nsetools")
    except Exception as e:
        print(f"⚠️ Failed fetching live NSE symbols: {e}")
        if not os.path.exists(csv_path):
            print(f"⚠️ tickers.csv missing at {csv_path}")
            return []
        with open(csv_path) as f:
            universe = [line.strip() for line in f if line.strip()]
        universe = universe[:200]
        print(f"✅ Using {len(universe)} symbols from local CSV fallback")
        return universe

# ----------------------- SAVE + NOTIFY -----------------------
def save_top_picks_to_firestore(picks, top_n=TOP_N):
    ts_val = dt.utcnow().isoformat()
    docs = []
    for p in picks[:top_n]:
        docs.append({
            "ts": ts_val,
            "symbol": p.get("symbol"),
            "last_price": p.get("last_price"),
            "score": p.get("combined_score", p.get("score")),
            "intraday_pct": p.get("features", {}).get("core", {}).get("intraday_pct")
        })
    try:
        doc_ref = db_firestore.collection("top_picks").document("latest")
        doc_ref.set({"timestamp": ts_val, "data": docs})
        print("✅ Top picks saved to Firestore")
    except Exception as e:
        print("❌ Failed to save top picks to Firestore:", e)

def log_notification(type_, symbol, title, body):
    def _write():
        conn = db_conn()
        c = conn.cursor()
        c.execute("""CREATE TABLE IF NOT EXISTS notifications(
                         id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, type TEXT, symbol TEXT, note TEXT
                       )""")
        ts_val = dt.utcnow().isoformat()
        c.execute("INSERT INTO notifications(ts,type,symbol,note) VALUES (?,?,?,?)",
                  (ts_val, type_, symbol, title + " - " + body))
        conn.commit()
        conn.close()
    try_db_write(_write)

# ----------------------- SCHEDULER LOGIC -----------------------
scheduler = BackgroundScheduler()

async def generate_and_store_top_picks(universe, limit=TOP_N):
    """
    Generate top picks using engine.top_picks_engine.generate_top_picks
    which internally calls StockModel with combine_weights override.
    """
    picks = await generate_top_picks(universe, limit)
    ts_val = dt.utcnow().isoformat()

    # persist in SQLite
    for p in picks:
        # guard: skip invalid
        if not p or not p.get("ok") or not p.get("symbol"):
            continue
        p['ts'] = ts_val
        # numeric coercion with fallbacks
        combined = float(p.get('combined_score', p.get('score', 0.0)) or 0.0)
        last_price = float(p.get('last_price', 0.0) or 0.0)
        intraday_pct = float(p.get('features', {}).get('core', {}).get('intraday_pct', 0.0) or 0.0)

        upsert_all_stock({
            'symbol': p.get('symbol'),
            'last_price': last_price,
            'intraday_pct': intraday_pct,
            'ma_diff': p.get('features', {}).get('core', {}).get('ma_diff', 0.0),
            'vol_ratio': p.get('features', {}).get('core', {}).get('vol_ratio', 0.0),
            'rsi': p.get('features', {}).get('core', {}).get('rsi', 50.0),
            'score': combined,
            'ts': ts_val
        })

    # Save to Firestore
    save_top_picks_to_firestore(picks, top_n=limit)

    # Send notifications for strong picks
    try:
        top0 = picks[0] if picks else None
        if top0 and float(top0.get('combined_score', 0.0)) >= BUY_THRESHOLD:
            title = f"🔥 New BUY top pick: {top0['symbol']}"
            body = f"Score {round(float(top0['combined_score']),4)} | Price {top0['last_price']}"
            log_notification("buy", top0['symbol'], title, body)
            if FCM_TEST_TOKEN:
                send_push(to_token=FCM_TEST_TOKEN, title=title, body=body, data={"symbol": top0['symbol']})
    except Exception as e:
        print("Notification error:", e)

    # notify other notable picks >= ALERT_THRESHOLD
    try:
        for p in picks:
            if float(p.get('combined_score', 0.0)) >= ALERT_THRESHOLD:
                title = f"Interesting pick: {p['symbol']}"
                body = f"Score {round(float(p['combined_score']),4)} | Price {p['last_price']}"
                log_notification("alert", p['symbol'], title, body)
                if FCM_TEST_TOKEN:
                    send_push(to_token=FCM_TEST_TOKEN, title=title, body=body, data={"symbol": p['symbol']})
    except Exception as e:
        print("Batch notification error:", e)

    return picks

async def run_top_picks_once(limit=TOP_N):
    """
    Top-level async entry used by routes and scheduler wrapper.
    """
    universe = load_universe()
    if not universe:
        print("⚠️ No universe available for top picks")
        return None

    # cap to reasonable number for scheduled runs
    universe = universe[: max(len(universe), TOP_N)]
    print(f"🚀 Running Top Picks for {len(universe)} stocks...")
    picks = await generate_and_store_top_picks(universe, limit)
    print("✅ Top picks generation completed.")
    return picks

def run_top_picks_async_wrapper():
    try:
        asyncio.run(run_top_picks_once())
    except Exception as e:
        print("❌ Error running scheduled top picks job:", e)

def start_scheduler():
    if scheduler.running:
        print("⚠️ Scheduler already running.")
        return
    scheduler.add_job(run_top_picks_async_wrapper, 'interval', minutes=TOPPICKS_INTERVAL_MIN)
    # Note: position monitoring implemented elsewhere; keep placeholder or add real monitor
    scheduler.add_job(lambda: None, 'interval', minutes=MONITOR_INTERVAL_MIN)
    scheduler.start()
    print("✅ Scheduler started.")

def shutdown_scheduler():
    scheduler.shutdown(wait=True)
    print("🛑 Scheduler stopped.")

if __name__ == "__main__":
    print("🚀 Scheduler starting (manual run)...")
    start_scheduler()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        shutdown_scheduler()
