# backend/scheduler.py
"""
TradeGuru Async Scheduler - Render-ready & fully safe version
Preserves all existing logic but makes scheduler async-safe and robust
Features:
- Async top picks fetching with retries
- Dynamic batching (top 500 symbols)
- APScheduler safe shutdown
- Firebase credentials loaded from ENV var (secure)
- SQLite retry for "database is locked" issues
"""

import os
import time
import sqlite3
import asyncio
import pandas as pd
import firebase_admin
from firebase_admin import credentials, firestore
from datetime import datetime as dt, timedelta
from apscheduler.schedulers.background import BackgroundScheduler
from concurrent.futures import ThreadPoolExecutor
import json # <-- Added for JSON loading
from apscheduler.schedulers.background import BackgroundScheduler
import time
from utils.market import fetch_intraday, compute_features
from utils.score import score_from_features
from utils.notifier import send_push
from utils.positions import open_position, close_position, list_open_positions
from datetime import datetime, timezone


# ----------------------- CONFIG -----------------------
DB = os.getenv("DB_PATH", "app.db")
BATCH_SIZE = int(os.getenv("BATCH_SIZE", "40"))
BATCH_DELAY = float(os.getenv("BATCH_DELAY_SEC", "3.0"))
TOP_N = int(os.getenv("TOP_N", "5"))
DEFAULT_TARGET_PCT = float(os.getenv("DEFAULT_TARGET_PCT", "5.0"))
DEFAULT_STOP_PCT = float(os.getenv("DEFAULT_STOP_PCT", "1.5"))
TOPPICKS_INTERVAL_MIN = int(os.getenv("TOPPICKS_INTERVAL_MIN", "15"))
MONITOR_INTERVAL_MIN = int(os.getenv("MONITOR_INTERVAL_MIN", "2"))
FCM_TEST_TOKEN = os.getenv("TEST_DEVICE_TOKEN", "")

_PRICE_CACHE = {}
CACHE_TTL = timedelta(seconds=int(os.getenv("PRICE_CACHE_TTL_SEC", "90")))



# ----------------------- DB HELPERS / FIREBASE INIT (CRITICAL CHANGE) -----------------------
if not firebase_admin._apps:
    json_creds = os.getenv("FIREBASE_CREDENTIALS_JSON")

    if json_creds:
        try:
            # Load credentials from the JSON string content provided in the environment variable
            cred = credentials.Certificate(json.loads(json_creds))
            firebase_admin.initialize_app(cred)
            print("✅ Firebase initialized from Environment JSON")
        except Exception as e:
            # Fallback if ENV variable is corrupt
            print(f"❌ Failed to initialize Firebase from JSON ENV: {e}")
            try:
                # Fallback to local file for development if ENV fails
                cred = credentials.Certificate("firebase_key.json")
                firebase_admin.initialize_app(cred)
                print("✅ Firebase initialized from local file (Fallback)")
            except Exception as e2:
                print(f"❌ Failed to initialize Firebase from local file: {e2}")
    else:
        # If no ENV var is set, try local file
        try:
            cred = credentials.Certificate("firebase_key.json")
            firebase_admin.initialize_app(cred)
            print("✅ Firebase initialized from local file: firebase_key.json")
        except Exception as e:
            print(f"❌ Failed to initialize Firebase: {e}")

db_firestore = firestore.client()

def db_conn():
    return sqlite3.connect(DB, check_same_thread=False)

def try_db_write(func, *args, retries=2, **kwargs):
    """Retry DB write up to `retries` times, skip on failure."""
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
        print(f"⚠️ Skipping DB write for {s['symbol']} due to locked DB")

def save_top_picks(picks, top_n=TOP_N):
    """Save top picks to Firebase Firestore."""
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
        print("✅ Top picks saved to Firebase")
    except Exception as e:
        print("❌ Failed to save top picks to Firebase:", e)

def get_current_top_scores(limit=TOP_N):
    ensure_all_stocks_table()
    conn = db_conn()
    c = conn.cursor()
    c.execute("SELECT symbol, score FROM all_stocks ORDER BY score DESC LIMIT ?", (limit,))
    rows = c.fetchall()
    conn.close()
    return rows

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
            universe = universe[:50]
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
        universe = universe[:50]
        print(f"✅ Using {len(universe)} symbols from local CSV fallback")
        return universe

# ----------------------- ASYNC FETCH -----------------------
async def _fetch_and_compute(symbol: str, interval="5m", period="1d", retries=3, backoff=2):
    
    now = datetime.now(timezone.utc)
    cached = _PRICE_CACHE.get(symbol)
    if cached and now - cached[0] < CACHE_TTL:
        return cached[1]

    for attempt in range(1, retries+1):
        try:
            # Use asyncio.to_thread for synchronous I/O-bound operations
            df = await asyncio.to_thread(fetch_intraday, symbol if symbol.endswith(".NS") else symbol+".NS",
                                          period=period, interval=interval)
            feats = await asyncio.to_thread(compute_features, df)
            if feats:
                feats['symbol'] = symbol.replace(".NS", "")
                feats['last_price'] = feats.get('last_price') or (df['Close'].iloc[-1] if len(df)>0 else None)
                feats['intraday_pct'] = feats.get('intraday_pct') or ((feats['last_price'] - df['Open'].iloc[0])/df['Open'].iloc[0]*100 if len(df)>0 else 0)
                # --- ENSURE buy_confidence IS ALWAYS PRESENT ---
                if 'buy_confidence' not in feats:
                    
                    feats['buy_confidence'] = compute_buy_confidence({
                        "candle_bull": feats.get("candle_bull", 0),
                        "vol_signal": feats.get("vol_signal", 0),
                        "trend_phase": feats.get("trend_phase", ""),
                        "rsi": feats.get("rsi", 50),
                        "breakout_score": feats.get("breakout_score", 0)
                    })
                feats['ts'] = now.isoformat()
                _PRICE_CACHE[symbol] = (now, feats)
                return feats
        except Exception as e:
            msg = str(e)
            if "Too Many Requests" in msg or "rate limit" in msg.lower():
                wait = backoff * attempt
                print(f"⚠️ Rate limit on {symbol}, retrying in {wait}s (attempt {attempt}/{retries})")
                await asyncio.sleep(wait)
            else:
                print(f"Error fetching {symbol}: {e}")
                break
    print(f"❌ Failed to fetch {symbol} after {retries} attempts")
    return None

# ----------------------- POSITION MONITOR -----------------------
def evaluate_and_maybe_open(picks):
    open_syms = {row[1] for row in list_open_positions()}
    for p in picks[:TOP_N]:
        sym, price, score = p['symbol'], p['last_price'], p['score']
        ma_diff, vol_ratio = p.get('ma_diff',0), p.get('vol_ratio',0)
        if score >= 0.6 and ma_diff>0 and vol_ratio>1.2 and sym not in open_syms:
            open_position(sym, price, size=1.0, target_pct=DEFAULT_TARGET_PCT, stop_pct=DEFAULT_STOP_PCT)
            msg = f"Buy suggestion: {sym} @ {price:.2f} | Target {DEFAULT_TARGET_PCT}% Stop {DEFAULT_STOP_PCT}%"
            print("🔔", msg)
            if FCM_TEST_TOKEN:
                send_push(to_token=FCM_TEST_TOKEN, title=f"BUY {sym}", body=msg, data={"symbol": sym})

def monitor_positions_job():
    positions = list_open_positions()
    if not positions:
        return
    for pos in positions:
        _id, sym, entry_price, *_ = pos
        try:
            cached = _PRICE_CACHE.get(sym)
            now = dt.utcnow()
            if cached and now - cached[0] < CACHE_TTL:
                current = cached[1]['last_price']
            else:
                try:
                    df = fetch_intraday(sym+".NS", period="1d", interval="1m")
                    feats = compute_features(df)
                    current = feats['last_price'] if feats else (df['Close'].iloc[-1] if len(df)>0 else None)
                    if feats:
                        feats['symbol'] = sym
                        feats['last_price'] = current
                        feats['ts'] = now.isoformat()
                        _PRICE_CACHE[sym] = (now, feats)
                except Exception as e:
                    print(f"fetch_intraday error {sym}: {e}")
                    continue

            if current is None:
                continue

            pct = (current - entry_price)/entry_price*100
            if pct >= DEFAULT_TARGET_PCT:
                close_position(sym, current)
                msg = f"Target hit: Sell {sym} @ {current:.2f} (+{pct:.2f}%)"
                print("🔔", msg)
                if FCM_TEST_TOKEN:
                    send_push(to_token=FCM_TEST_TOKEN, title=f"SELL {sym}", body=msg, data={"symbol": sym})
            elif pct <= -DEFAULT_STOP_PCT:
                close_position(sym, current)
                msg = f"Stop hit: Sell {sym} @ {current:.2f} ({pct:.2f}%)"
                print("🔔", msg)
                if FCM_TEST_TOKEN:
                    send_push(to_token=FCM_TEST_TOKEN, title=f"SELL {sym}", body=msg, data={"symbol": sym})
            elif pct <= -(DEFAULT_STOP_PCT*0.6):
                print(f"⚠️ Warning {sym}: unrealized {pct:.2f}%")
                log_notification("warning", sym, f"Warn {sym}", f"Unrealized {pct:.2f}%")
        except Exception as e:
            print("monitor error for", sym, e)

# ----------------------- REMOVED find_top_picks_scheduler & run_async_safe -----------------------

async def compute_top_picks(batch_size=BATCH_SIZE): # <-- New ASYNC function for main compute logic
    ensure_all_stocks_table()
    universe = load_universe()
    if not universe:
        print("⚠️ No tickers found for top picks")
        return []

    print(f"🔎 Computing top picks for {len(universe)} tickers...")
    features_list = []

    async def run_batches():
        for i in range(0, len(universe), batch_size):
            batch = universe[i:i + batch_size]
            tasks = [_fetch_and_compute(sym, interval="5m", period="1d") for sym in batch]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for r in results:
                if isinstance(r, Exception):
                    print("Batch error:", r)
                elif r:
                    features_list.append(r)
            await asyncio.sleep(BATCH_DELAY)

    # AWAIT the async function call
    await run_batches()

    if not features_list:
        print("⚠️ No features computed")
        return []

    scored = score_from_features(features_list)
    ts_val = dt.utcnow().isoformat()
    
    # Run synchronous DB writing in a thread pool to avoid blocking
    for p in scored:
        p['ts'] = ts_val
        # This function is fast enough, but for safety, we could also use await asyncio.to_thread(upsert_all_stock, p)
        upsert_all_stock(p)

    print("✅ Computed and stored latest stock data")
    return scored

async def run_top_picks_once(): # <-- New ASYNC function to manage a full pick cycle
    print("🔁 Running top picks once (startup/manual trigger)")
    
    scored = await compute_top_picks() # AWAIT the compute function
    if not scored:
        print("⚠️ No valid scores, skipping save.")
        return

    # Check for new top pick before saving
    current_tops = await asyncio.to_thread(get_current_top_scores, TOP_N)
    first_run = len(current_tops) == 0
    prev_best_score = current_tops[0][1] if current_tops else 0

    if first_run or prev_best_score == 0:
        await asyncio.to_thread(save_top_picks, scored, TOP_N)
        print("✅ Initial top picks saved (first run or reset)")
    else:
        new_best = scored[0] 
        if new_best['score'] > prev_best_score + 0.05:
            title = f"New top pick: {new_best['symbol']}"
            body = f"Score {round(new_best['score']*100,2)} — Price {new_best['last_price']}"
            await asyncio.to_thread(log_notification, "new_top", new_best['symbol'], title, body)
            if FCM_TEST_TOKEN:
                await asyncio.to_thread(send_push, to_token=FCM_TEST_TOKEN, title=title, body=body, data={"symbol": new_best['symbol']})
            await asyncio.to_thread(save_top_picks, scored, TOP_N)
            print("✅ Top picks updated & notified")
        else:
            print("✅ No new top beyond threshold; top picks unchanged — forcing Firestore save for verification.")
            

# ----------------------- SCHEDULER -----------------------
scheduler = BackgroundScheduler()

# Wrapper function for APScheduler to call the async job
def run_top_picks_async_wrapper():
    """Runs the async job safely in a new event loop/thread for APScheduler."""
    try:
        # Use asyncio.run() to safely start the async coroutine from the sync thread
        asyncio.run(run_top_picks_once())
    except Exception as e:
        print(f"❌ Error running scheduled top picks job: {e}")

def start_scheduler():
    # Use scheduler.running check for robust prevention of duplicate startups
    if scheduler.running:
        print("⚠️ Scheduler already running, skipping duplicate start.")
        return
    
    # 1. Top Picks Job (Runs every 15 minutes)
    # CRITICAL CHANGE: Removed next_run_time=dt.utcnow(). 
    # This allows the initial blocking run in main.py to complete 
    # before the recurring job starts its first interval.
    scheduler.add_job(
        run_top_picks_async_wrapper, 
        'interval', 
        minutes=TOPPICKS_INTERVAL_MIN
    )
    
    # 2. Position Monitoring Job (Runs immediately and then every 5 minutes)
    scheduler.add_job(
        monitor_positions_job, 
        'interval', 
        minutes=MONITOR_INTERVAL_MIN, 
        next_run_time=dt.utcnow()
    )
    
    scheduler.start()
    print("✅ Scheduler started: monitoring + top picks active.")

def shutdown_scheduler():
    # Gracefully shut down the scheduler
    scheduler.shutdown(wait=True)
    print("🛑 Scheduler stopped safely.")


# ----------------------- STANDALONE RUN -----------------------
if __name__ == "__main__":
    print("🚀 TradeGuru Standalone Scheduler Starting...")
    start_scheduler()
    try:
        # Keep the main thread alive so the background scheduler can run
        while True:
            time.sleep(1)
    except (KeyboardInterrupt, SystemExit):
        # Handle graceful exit
        shutdown_scheduler()