# backend/scheduler.py
"""
TradeGuru Async Scheduler - Fully safe version with first-run top picks
Features:
- Async top picks fetching with retries
- Dynamic batching (top 500 symbols)
- APScheduler safe shutdown
- First-run top picks always saved
"""

import os
import time
import sqlite3
import asyncio
from datetime import datetime as dt, timedelta
from apscheduler.schedulers.background import BackgroundScheduler

from utils.market import fetch_intraday, compute_features
from utils.score import score_from_features
from utils.notifier import send_push
from utils.positions import open_position, close_position, list_open_positions

# ----------------------- CONFIG -----------------------
DB = os.getenv("DB_PATH", "app.db")
BATCH_SIZE = int(os.getenv("BATCH_SIZE", "60"))
BATCH_DELAY = float(os.getenv("BATCH_DELAY_SEC", "1.5"))
TOP_N = int(os.getenv("TOP_N", "5"))
DEFAULT_TARGET_PCT = float(os.getenv("DEFAULT_TARGET_PCT", "5.0"))
DEFAULT_STOP_PCT = float(os.getenv("DEFAULT_STOP_PCT", "1.5"))
TOPPICKS_INTERVAL_MIN = int(os.getenv("TOPPICKS_INTERVAL_MIN", "15"))
MONITOR_INTERVAL_MIN = int(os.getenv("MONITOR_INTERVAL_MIN", "1"))
FCM_TEST_TOKEN = os.getenv("TEST_DEVICE_TOKEN", "")

_PRICE_CACHE = {}
CACHE_TTL = timedelta(seconds=int(os.getenv("PRICE_CACHE_TTL_SEC", "90")))

# ----------------------- DB HELPERS -----------------------
def db_conn():
    return sqlite3.connect(DB)

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

def save_top_picks(picks, top_n=TOP_N):
    conn = db_conn()
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS top_picks(
                 ts TEXT, symbol TEXT, last_price REAL, score REAL, intraday_pct REAL)""")
    ts = dt.utcnow().isoformat()
    for p in picks[:top_n]:
        c.execute("INSERT INTO top_picks(ts,symbol,last_price,score,intraday_pct) VALUES (?,?,?,?,?)",
                  (ts, p.get('symbol'), p.get('last_price'), p.get('score'), p.get('intraday_pct')))
    conn.commit()
    conn.close()

def get_current_top_scores(limit=TOP_N):
    ensure_all_stocks_table()
    conn = db_conn()
    c = conn.cursor()
    c.execute("SELECT symbol, score FROM all_stocks ORDER BY score DESC LIMIT ?", (limit,))
    rows = c.fetchall()
    conn.close()
    return rows

def log_notification(type_, symbol, title, body):
    conn = db_conn()
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS notifications(
                    id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, type TEXT, symbol TEXT, note TEXT
                 )""")
    ts = dt.utcnow().isoformat()
    c.execute("INSERT INTO notifications(ts,type,symbol,note) VALUES (?,?,?,?)",
              (ts, type_, symbol, title + " - " + body))
    conn.commit()
    conn.close()

# ----------------------- LOAD UNIVERSE -----------------------
def load_universe(csv_path=os.path.join("backend", "tickers.csv")):
    """
    Load live NSE symbols via nsetools, fallback to CSV.
    Limit to top 500 symbols.
    """
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
            universe = universe[:500]
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
        universe = universe[:500]
        print(f"✅ Using {len(universe)} symbols from local CSV fallback")
        return universe

# ----------------------- ASYNC FETCH -----------------------
async def _fetch_and_compute(symbol: str, interval="5m", period="1d", retries=3, backoff=2):
    now = dt.utcnow()
    cached = _PRICE_CACHE.get(symbol)
    if cached and now - cached[0] < CACHE_TTL:
        return cached[1]

    for attempt in range(1, retries+1):
        try:
            df = await asyncio.to_thread(fetch_intraday, symbol if symbol.endswith(".NS") else symbol+".NS",
                                         period=period, interval=interval)
            feats = await asyncio.to_thread(compute_features, df)
            if feats:
                feats['symbol'] = symbol.replace(".NS", "")
                feats['last_price'] = feats.get('last_price') or (df['Close'].iloc[-1] if len(df)>0 else None)
                feats['intraday_pct'] = feats.get('intraday_pct') or ((feats['last_price'] - df['Open'].iloc[0])/df['Open'].iloc[0]*100 if len(df)>0 else 0)
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

# ----------------------- TOP PICKS SCHEDULER -----------------------
def find_top_picks_scheduler(batch_size=BATCH_SIZE):
    ensure_all_stocks_table()
    universe = load_universe()
    if not universe:
        print("⚠️ No tickers found")
        return []

    print(f"🔁 Running top picks for {len(universe)} tickers")
    features_list = []

    async def run_batches():
        for i in range(0, len(universe), batch_size):
            batch = universe[i:i+batch_size]
            tasks = [_fetch_and_compute(sym, interval="5m", period="1d") for sym in batch]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for r in results:
                if isinstance(r, Exception):
                    print("Batch fetch exception:", r)
                elif r:
                    features_list.append(r)
            await asyncio.sleep(BATCH_DELAY)

    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    loop.run_until_complete(run_batches())

    if not features_list:
        print("⚠️ No features computed")
        return []

    # Score and update DB
    scored = score_from_features(features_list)
    ts = dt.utcnow().isoformat()
    current_tops = get_current_top_scores(limit=TOP_N)
    first_run = len(current_tops) == 0
    prev_best_score = current_tops[0][1] if current_tops else 0

    for p in scored:
        p['ts'] = ts
        upsert_all_stock(p)

    # ----------------------- First-run always save -----------------------
    if first_run:
        save_top_picks(scored, top_n=TOP_N)
        print("✅ First-run top picks saved")
    else:
        new_best = scored[0] if scored else None
        if new_best and new_best['score'] > prev_best_score + 0.05:
            title = f"New top pick: {new_best['symbol']}"
            body = f"Score {round(new_best['score']*100,2)} — Price {new_best['last_price']}"
            log_notification("new_top", new_best['symbol'], title, body)
            if FCM_TEST_TOKEN:
                send_push(to_token=FCM_TEST_TOKEN, title=title, body=body, data={"symbol": new_best['symbol']})
            save_top_picks(scored, top_n=TOP_N)
            print("✅ Top picks updated & notified")
        else:
            print("✅ No new top beyond threshold; top picks unchanged")

    return scored[:TOP_N]

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
                df = fetch_intraday(sym+".NS", period="1d", interval="1m")
                feats = compute_features(df)
                current = feats['last_price'] if feats else (df['Close'].iloc[-1] if len(df)>0 else None)
                if feats:
                    feats['symbol'] = sym
                    feats['last_price'] = current
                    feats['ts'] = now.isoformat()
                    _PRICE_CACHE[sym] = (now, feats)

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

# ----------------------- SCHEDULER -----------------------
scheduler = BackgroundScheduler()

def start_scheduler():
    scheduler.add_job(find_top_picks_scheduler, 'interval', minutes=TOPPICKS_INTERVAL_MIN, next_run_time=dt.utcnow())
    scheduler.add_job(monitor_positions_job, 'interval', minutes=MONITOR_INTERVAL_MIN, next_run_time=dt.utcnow())
    scheduler.start()
    print("✅ Scheduler started: monitoring + top picks active.")

def shutdown_scheduler():
    scheduler.shutdown(wait=True)
    print("🛑 Scheduler stopped safely.")

# ----------------------- STANDALONE RUN -----------------------
if __name__ == "__main__":
    print("🚀 TradeGuru Standalone Scheduler Starting...")
    start_scheduler()
    try:
        while True:
            time.sleep(1)  # synchronous sleep to avoid asyncio warnings
    except (KeyboardInterrupt, SystemExit):
        shutdown_scheduler()


