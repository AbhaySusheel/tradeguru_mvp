# backend/scheduler.py
"""
Async-friendly scheduler runner for TradeGuru.

Strategy:
 - Process "tickers.csv" in batches.
 - For each ticker in a batch, run the existing sync fetch_intraday + compute_features
   concurrently using asyncio.to_thread (so we get parallelism without blocking).
 - Cache last_price/feature results in-memory with a short TTL to reduce repeated fetches.
 - After scoring, upsert into all_stocks, save top_picks, optionally notify, and open virtual positions.
"""

import os
import time
import sqlite3
import asyncio
from datetime import datetime as dt, timedelta
from apscheduler.schedulers.background import BackgroundScheduler

from utils.market import fetch_intraday, compute_features     # existing sync fns
from utils.score import score_from_features
from utils.notifier import send_push
from utils.positions import open_position, close_position, list_open_positions

# Configs via env (fallback defaults)
DB = os.getenv("DB_PATH", "app.db")
BATCH_SIZE = int(os.getenv("BATCH_SIZE", "60"))         # how many symbols per batch
BATCH_DELAY = float(os.getenv("BATCH_DELAY_SEC", "1.5"))# delay between batches (seconds)
TOP_N = int(os.getenv("TOP_N", "5"))
DEFAULT_TARGET_PCT = float(os.getenv("DEFAULT_TARGET_PCT", "5.0"))
DEFAULT_STOP_PCT = float(os.getenv("DEFAULT_STOP_PCT", "1.5"))
TOPPICKS_INTERVAL_MIN = int(os.getenv("TOPPICKS_INTERVAL_MIN", "15"))
MONITOR_INTERVAL_MIN = int(os.getenv("MONITOR_INTERVAL_MIN", "1"))
FCM_TEST_TOKEN = os.getenv("TEST_DEVICE_TOKEN", "")

# cache: { symbol: (timestamp, features_dict) }
_PRICE_CACHE = {}
CACHE_TTL = timedelta(seconds=int(os.getenv("PRICE_CACHE_TTL_SEC", "90")))

def load_universe(csv_path="tickers.csv"):
    if not os.path.exists(csv_path):
        print("⚠️ tickers.csv missing at", csv_path)
        return []
    with open(csv_path) as f:
        return [line.strip() for line in f if line.strip()]

def db_conn():
    conn = sqlite3.connect(DB)
    return conn

def upsert_all_stock(s):
    """Upsert result into all_stocks table (simple schema)."""
    conn = db_conn()
    c = conn.cursor()
    c.execute("""
      CREATE TABLE IF NOT EXISTS all_stocks(
        symbol TEXT PRIMARY KEY, last_price REAL, intraday_pct REAL,
        ma_diff REAL, vol_ratio REAL, rsi REAL, score REAL, ts TEXT
      )
    """)
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
          s.get('ma_diff', 0), s.get('vol_ratio', 0),
          s.get('rsi', 50), s['score'], s['ts']))
    conn.commit()
    conn.close()

def save_top_picks(picks, top_n=5):
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

def get_current_top_scores(limit=10):
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

# -----------------------
# Async helper: fetch single ticker via existing sync fetch_intraday + compute_features
# We run this in a thread using asyncio.to_thread to gain concurrency.
# -----------------------
async def _fetch_and_compute(symbol: str, interval="5m", period="1d"):
    # check cache first
    now = dt.utcnow()
    cached = _PRICE_CACHE.get(symbol)
    if cached:
        ts, data = cached
        if now - ts < CACHE_TTL:
            return data

    # run sync fetch + compute in thread pool
    try:
        # fetch_intraday returns a dataframe (sync) — call it in thread
        df = await asyncio.to_thread(fetch_intraday, symbol + ("" if symbol.endswith(".NS") else ".NS"), interval, period)
        feats = await asyncio.to_thread(compute_features, df)
        if feats:
            feats['symbol'] = symbol.replace(".NS", "") if ".NS" in symbol else symbol
            feats['last_price'] = feats.get('last_price') or (df['Close'].iloc[-1] if (hasattr(df, "iloc") and len(df)>0) else None)
            feats['intraday_pct'] = feats.get('intraday_pct') or ( (feats['last_price'] - df['Open'].iloc[0]) / df['Open'].iloc[0] * 100 if (hasattr(df, "iloc") and len(df)>0) else 0 )
            feats['ts'] = now.isoformat()
            # cache it
            _PRICE_CACHE[symbol] = (now, feats)
            return feats
    except Exception as e:
        # Don't stop whole job for single failure
        print(f"Error fetching {symbol}: {e}")
    return None

# -----------------------
# The main scheduler job that processes the entire universe in batches
# -----------------------
def find_top_picks_scheduler(batch_size=BATCH_SIZE):
    universe = load_universe("tickers.csv")
    if not universe:
        print("⚠️ No tickers found in tickers.csv")
        return []

    print(f"🔁 Starting top picks run for {len(universe)} tickers (batch={batch_size})")
    features_list = []

    async def run_batches():
        # For each batch, concurrently fetch features using to_thread (asyncio)
        for i in range(0, len(universe), batch_size):
            batch = universe[i:i+batch_size]
            tasks = [ _fetch_and_compute(sym, interval="5m", period="1d") for sym in batch ]
            # gather results (concurrent)
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for r in results:
                if isinstance(r, Exception):
                    print("batch fetch exception:", r)
                elif r:
                    # ensure symbol format without .NS in stored symbol
                    if isinstance(r.get('symbol'), str) and r.get('symbol').endswith(".NS"):
                        r['symbol'] = r['symbol'].replace(".NS","")
                    features_list.append(r)
            # small delay between batches
            await asyncio.sleep(BATCH_DELAY)

    # run the async batch fetcher
    try:
        asyncio.get_event_loop().run_until_complete(run_batches())

    except Exception as e:
        print("Async batch runner failed:", e)
        # fallback to synchronous single-thread run (best-effort)
        for symbol in universe:
            try:
                df = fetch_intraday(symbol, interval="5m", period="1d")
                feats = compute_features(df)
                if feats:
                    feats['symbol'] = symbol.replace(".NS","")
                    feats['last_price'] = feats.get('last_price') or (df['Close'].iloc[-1] if len(df)>0 else None)
                    feats['intraday_pct'] = feats.get('intraday_pct') or 0
                    feats['ts'] = dt.utcnow().isoformat()
                    features_list.append(feats)
            except Exception as e2:
                print("fallback fetch error", symbol, e2)

    if not features_list:
        print("⚠️ No features calculated this run")
        return []

    # score all features
    scored = score_from_features(features_list)
    ts = dt.utcnow().isoformat()

    # detect previous best
    current_tops = get_current_top_scores(limit=TOP_N)
    prev_best_score = current_tops[0][1] if current_tops else 0

    # upsert all into all_stocks (and look for new best)
    for p in scored:
        p['ts'] = ts
        upsert_all_stock(p)

    new_best = scored[0] if scored else None
    if new_best and new_best['score'] > prev_best_score + 0.05:
        title = f"New top pick: {new_best['symbol']}"
        body = f"Score {round(new_best['score']*100,2)} — Price {new_best['last_price']}"
        log_notification("new_top", new_best['symbol'], title, body)
        if FCM_TEST_TOKEN:
            try:
                send_push(to_token=FCM_TEST_TOKEN, title=title, body=body, data={"symbol": new_best['symbol']})
            except Exception as e:
                print("Push failed:", e)
        save_top_picks(scored, top_n=TOP_N)
        print("✅ Top picks updated successfully (and notified).")
        # Optional: auto-evaluate buys
        try:
            evaluate_and_maybe_open(scored)
        except Exception as e:
            print("Error during auto-open evaluation:", e)
    else:
        # still save top picks for history (we save always top N)
        save_top_picks(scored, top_n=TOP_N)
        print("✅ Top picks saved (no new top beyond threshold).")

    return scored[:TOP_N]


# -----------------------
# Position management & monitoring (unchanged logic but adapted to use fetch helper)
# -----------------------
def evaluate_and_maybe_open(picks):
    open_syms = {row[1] for row in list_open_positions()}  # (id, symbol, ...)
    for p in picks[:TOP_N]:
        sym = p['symbol']
        price = p['last_price']
        score = p['score']
        ma_diff = p.get('ma_diff', 0)
        vol_ratio = p.get('vol_ratio', 0)

        if score >= 0.6 and ma_diff > 0 and vol_ratio > 1.2:
            if sym not in open_syms:
                open_position(sym, price, size=1.0, target_pct=DEFAULT_TARGET_PCT, stop_pct=DEFAULT_STOP_PCT)
                msg = f"Buy suggestion: {sym} @ {price:.2f} | Target {DEFAULT_TARGET_PCT}% Stop {DEFAULT_STOP_PCT}%"
                print("🔔", msg)
                if FCM_TEST_TOKEN:
                    try:
                        send_push(to_token=FCM_TEST_TOKEN, title=f"BUY {sym}", body=msg, data={"symbol": sym})
                    except Exception as e:
                        print("Push failed:", e)


def monitor_positions_job():
    positions = list_open_positions()
    if not positions:
        return
    for pos in positions:
        _id, sym, entry_price, entry_ts, size, target_pct, stop_pct = pos
        try:
            # get current data from cache if fresh otherwise fetch sync
            cached = _PRICE_CACHE.get(sym)
            now = dt.utcnow()
            if cached and now - cached[0] < CACHE_TTL:
                feats = cached[1]
                current = feats.get('last_price')
            else:
                # synchronous fetch (fast path)
                df = fetch_intraday(sym + ".NS", interval="1m", period="1d")
                feats = compute_features(df)
                current = feats.get('last_price') if feats else (df['Close'].iloc[-1] if len(df)>0 else None)
                if feats:
                    feats['symbol'] = sym
                    feats['last_price'] = current
                    feats['ts'] = now.isoformat()
                    _PRICE_CACHE[sym] = (now, feats)

            if current is None:
                continue

            pct = (current - entry_price) / entry_price * 100
            if pct >= target_pct:
                close_position(sym, current)
                msg = f"Target hit: Sell {sym} @ {current:.2f} (+{pct:.2f}%)"
                print("🔔", msg)
                if FCM_TEST_TOKEN:
                    try:
                        send_push(to_token=FCM_TEST_TOKEN, title=f"SELL {sym}", body=msg, data={"symbol": sym})
                    except Exception as e:
                        print("Push failed:", e)
            elif pct <= -stop_pct:
                close_position(sym, current)
                msg = f"Stop hit: Sell {sym} @ {current:.2f} ({pct:.2f}%)"
                print("🔔", msg)
                if FCM_TEST_TOKEN:
                    try:
                        send_push(to_token=FCM_TEST_TOKEN, title=f"SELL {sym}", body=msg, data={"symbol": sym})
                    except Exception as e:
                        print("Push failed:", e)
            else:
                # progressive warnings: if position losing but not yet stop, warn every NOTIFY_COOLDOWN_MIN minutes
                cooldown_min = int(os.getenv("NOTIFY_COOLDOWN_MIN", "15"))
                if pct <= - (stop_pct * 0.6):  # e.g. -60% of stop threshold
                    # leave the logic for notification_cooldown in DB or reuse _PRICE_CACHE timestamps
                    # we'll do a simple print + local DB log here
                    print(f"⚠️ Warning for {sym}: unrealized {pct:.2f}% — consider selling")
                    log_notification("warning", sym, f"Warn {sym}", f"Unrealized {pct:.2f}%")
        except Exception as e:
            print("monitor_positions_job error for", sym, e)


# -----------------------
# Scheduler starter
# -----------------------
def start_scheduler():
    scheduler = BackgroundScheduler()
    scheduler.add_job(find_top_picks_scheduler, 'interval', minutes=TOPPICKS_INTERVAL_MIN, next_run_time=dt.utcnow())
    scheduler.add_job(monitor_positions_job, 'interval', minutes=MONITOR_INTERVAL_MIN, next_run_time=dt.utcnow())
    scheduler.start()
    print("✅ Scheduler started: monitoring + top picks engine active.")
