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
import logging
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

logger = logging.getLogger("scheduler")
logger.setLevel(logging.INFO)
if not logger.handlers:
    ch = logging.StreamHandler()
    ch.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(ch)

# ----------------------- CONFIG -----------------------
DB = os.getenv("DB_PATH", "app.db")
BATCH_SIZE = int(os.getenv("BATCH_SIZE", "40"))
BATCH_DELAY = float(os.getenv("BATCH_DELAY_SEC", "3.0"))
TOP_N = int(os.getenv("TOP_N", "10"))
TOPPICKS_INTERVAL_MIN = int(os.getenv("TOPPICKS_INTERVAL_MIN", "15"))
MONITOR_INTERVAL_MIN = int(os.getenv("MONITOR_INTERVAL_MIN", "2"))
FCM_TEST_TOKEN = os.getenv("TEST_DEVICE_TOKEN", "")
BUY_THRESHOLD = float(os.getenv("BUY_THRESHOLD", "0.70"))   # combined_score >= this -> BUY push
ALERT_THRESHOLD = float(os.getenv("ALERT_THRESHOLD", "0.60")) # combined_score >= this -> alert

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
        logger.info("✅ Firebase initialized")
    except Exception as e:
        logger.error("❌ Firebase init failed: %s", e)

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
                logger.warning("⚠️ DB locked, retrying (%s/%s)...", attempt, retries)
                time.sleep(0.1 * attempt)
            else:
                logger.error("❌ DB write error: %s", e)
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
        logger.warning("⚠️ Skipping DB write for %s due to locked DB", s.get('symbol'))

def load_universe(csv_path=os.path.join(os.path.dirname(__file__), "universe_final_with_liquidity.csv")):
    """
    Loads and sorts stocks by Liquidity DESCENDING.
    CSV columns: Symbol,Liquidity
    Returns list of symbols with .NS appended.
    """
    if not os.path.exists(csv_path):
        print(f"❌ Universe CSV not found at: {csv_path}")
        return []

    rows = []
    with open(csv_path, "r") as f:
        next(f)  # skip header
        for line in f:
            parts = line.strip().split(",")
            if len(parts) < 2:
                continue

            sym = parts[0].strip()
            try:
                liquidity = float(parts[1])
            except:
                continue

            if sym:
                rows.append((sym, liquidity))

    # ✅ Sort by liquidity (highest first)
    rows.sort(key=lambda x: x[1], reverse=True)

    # return ONLY the symbols with .NS
    symbols = [r[0] + ".NS" for r in rows]

    print(f"✅ Loaded {len(symbols)} symbols (sorted by liquidity)")
    return symbols


# ----------------------- SAVE + NOTIFY -----------------------
def save_top_picks_to_firestore(picks, top_n=TOP_N):
    ts_val = dt.utcnow().isoformat()
    docs = []
    for p in picks[:top_n]:
        docs.append({
            "ts": ts_val,
            "symbol": p.get("symbol"),
            "last_price": p.get("last_price"),
            "score": p.get("score"),
            "intraday_pct": p.get("intraday_pct")
        })
    try:
        doc_ref = db_firestore.collection("top_picks").document("latest")
        doc_ref.set({"timestamp": ts_val, "data": docs})
        logger.info("✅ Top picks saved to Firestore")
    except Exception as e:
        logger.error("❌ Failed to save top picks to Firestore: %s", e)

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
    Generate top picks, save to DB/Firestore, and optionally notify.
    """
    picks = await generate_top_picks(universe, limit)
    ts_val = dt.utcnow().isoformat()

    for p in picks:
        p['ts'] = ts_val
        p['score'] = float(p.get('combined_score', 0.0))
        p['last_price'] = float(p.get('last_price', 0.0))
        p['intraday_pct'] = float(p.get('features', {}).get('core', {}).get('intraday_pct', 0.0)) if isinstance(p.get('features', {}), dict) else 0.0
        upsert_all_stock({
            'symbol': p.get('symbol'),
            'last_price': p['last_price'],
            'intraday_pct': p['intraday_pct'],
            'ma_diff': p.get('features', {}).get('core', {}).get('ma_diff', 0.0),
            'vol_ratio': p.get('features', {}).get('core', {}).get('vol_ratio', 0.0),
            'rsi': p.get('features', {}).get('core', {}).get('rsi', 50.0),
            'score': p['score'],
            'ts': ts_val
        })

    # Save cached top picks to Firestore
    try:
        save_top_picks_to_firestore(picks, top_n=limit)
    except Exception as e:
        logger.error("Firestore save failed: %s", e)

    # Notify highest pick if above BUY_THRESHOLD
    try:
        top0 = picks[0] if picks else None
        if top0 and top0.get('combined_score', 0.0) >= BUY_THRESHOLD:
            title = f"🔥 New BUY top pick: {top0['symbol']}"
            body = f"Score {round(top0['combined_score'],4)} | Price {top0['last_price']}"
            log_notification("buy", top0['symbol'], title, body)
            if FCM_TEST_TOKEN:
                send_push(to_token=FCM_TEST_TOKEN, title=title, body=body, data={"symbol": top0['symbol']})
    except Exception as e:
        logger.error("Notification error: %s", e)

    # Notify other notable picks >= ALERT_THRESHOLD
    try:
        for p in picks:
            if p.get('combined_score', 0.0) >= ALERT_THRESHOLD:
                title = f"Interesting pick: {p['symbol']}"
                body = f"Score {round(p['combined_score'],4)} | Price {p['last_price']}"
                log_notification("alert", p['symbol'], title, body)
                if FCM_TEST_TOKEN:
                    send_push(to_token=FCM_TEST_TOKEN, title=title, body=body, data={"symbol": p['symbol']})
    except Exception as e:
        logger.error("Batch notification error: %s", e)

    return picks

async def run_top_picks_once(limit=TOP_N):
    """
    Top-level async entry used by routes and scheduler wrapper.
    """
    universe = load_universe()
    if not universe:
        logger.warning("⚠️ No universe available for top picks")
        return None

    universe = universe[:70]

    logger.info(f"🚀 Running Top Picks for {len(universe)} stocks...")
    picks = await generate_and_store_top_picks(universe, limit)
    logger.info("✅ Top picks generation completed.")
    return picks

def run_top_picks_async_wrapper():
    try:
        asyncio.run(run_top_picks_once())
    except Exception as e:
        logger.error("❌ Error running scheduled top picks job: %s", e)

def start_scheduler():
    if scheduler.running:
        logger.warning("⚠️ Scheduler already running.")
        return
    scheduler.add_job(run_top_picks_async_wrapper, 'interval', minutes=TOPPICKS_INTERVAL_MIN)
    scheduler.start()
    logger.info("✅ Scheduler started.")

def shutdown_scheduler():
    scheduler.shutdown(wait=True)
    logger.info("🛑 Scheduler stopped.")

if __name__ == "__main__":
    logger.info("🚀 Scheduler starting (manual run)...")
    start_scheduler()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        shutdown_scheduler()
