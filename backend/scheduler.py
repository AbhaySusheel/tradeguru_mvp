# backend/scheduler.py
"""
TradeGuru Async Scheduler - Full Update
Includes:
- DB migration on startup
- Smart profit notifications (progress + near-max)
- Dynamic stop-loss (soft/hard)
- Market hours guard (NSE)
- Top picks generation and notifications
"""

import os
import time
import sqlite3
import asyncio
import json
import logging
from firebase_admin import firestore

from datetime import datetime as dt, timedelta, time as dttime
from apscheduler.schedulers.background import BackgroundScheduler

from routes.register_push_token import get_all_tokens  # helper to fetch all saved Expo tokens
from utils.notifier import send_push_async  # async push version

from engine.top_picks_engine import generate_top_picks
from models.stock_model import get_default_engine
from db_migration import add_missing_columns  # migration helper

logger = logging.getLogger("scheduler")
logger.setLevel(logging.INFO)
if not logger.handlers:
    ch = logging.StreamHandler()
    ch.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(ch)

# ----------------------- CONFIG -----------------------
DB = os.getenv("DB_PATH", "app.db")
TOP_N = int(os.getenv("TOP_N", "10"))
TOPPICKS_INTERVAL_MIN = int(os.getenv("TOPPICKS_INTERVAL_MIN", "15"))
MONITOR_INTERVAL_MIN = int(os.getenv("MONITOR_INTERVAL_MIN", "2"))
FCM_TEST_TOKEN = os.getenv("TEST_DEVICE_TOKEN", "")
BUY_THRESHOLD = float(os.getenv("BUY_THRESHOLD", "0.70"))

# ----------------------- FIREBASE INIT -----------------------

db_firestore = firestore.client()

# ----------------------- DB HELPERS -----------------------
def db_conn():
    return sqlite3.connect(DB, check_same_thread=False)

def try_db_write(func, *args, retries=2, **kwargs):
    for attempt in range(1, retries + 1):
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

def load_universe(csv_path="universe_final_with_liquidity.csv"):
    if not os.path.exists(csv_path):
        logger.warning(f"❌ Universe CSV not found at: {csv_path}")
        return []
    rows = []
    with open(csv_path, "r") as f:
        next(f)
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
    rows.sort(key=lambda x: x[1], reverse=True)
    symbols = [r[0] + ".NS" for r in rows]
    logger.info(f"✅ Loaded {len(symbols)} symbols")
    return symbols

# ----------------------- MARKET HOURS CHECK -----------------------
def market_open_now():
    """NSE market hours: Mon-Fri 09:15 - 15:30 IST"""
    now = dt.utcnow() + timedelta(hours=5, minutes=30)
    if now.weekday() >= 5:
        return False
    return dttime(9, 15) <= now.time() <= dttime(15, 30)

# ----------------------- SMART MONITOR -----------------------
async def monitor_positions():
    """Smart notifications: progress + near-max profit and dynamic stop-loss."""
    if not market_open_now():
        logger.info("⚠️ Market closed, skipping monitoring")
        return

    conn = db_conn()
    c = conn.cursor()
    c.execute("""SELECT symbol, entry_price, predicted_max, status, soft_stop_pct, hard_stop_pct, 
                        profit_alerts_sent, stop_alerts_sent
                 FROM positions""")  # fetch all
    positions = c.fetchall()
    conn.close()

    tasks = []

    for pos in positions:
        symbol, entry_price, predicted_max, status, soft_stop_pct, hard_stop_pct, profit_alerts_sent, stop_alerts_sent = pos
        if status != "OPEN":
            logger.info(f"ℹ️ Skipping {symbol}, status={status}")
            continue  # skip sold/closed

        symbol_ns = symbol if symbol.endswith(".NS") else symbol + ".NS"

        try:
            engine = get_default_engine()
            stock_data = engine.get_last_price(symbol_ns)
            if not stock_data:
                continue
            last_price = float(stock_data.get("last_price", 0))
        except Exception as e:
            logger.warning(f"Failed to fetch price for {symbol}: {e}")
            continue

        # -------- PROFIT MILESTONES --------
        if predicted_max and predicted_max > entry_price:
            milestones = [
                (0.25, "Stock is rising!"),
                (0.50, "Stock is rising steadily!"),
                (0.75, "Stock is rising — almost halfway to max!"),
                (0.95, "Almost there!"),
                (0.97, "Getting close!"),
                (0.985, "Near maximum!")
            ]
            sent = set(profit_alerts_sent.split(',')) if profit_alerts_sent else set()
            for pct, note in milestones:
                milestone_price = entry_price + (predicted_max - entry_price) * pct
                key = str(round(milestone_price, 2))
                if last_price >= milestone_price and key not in sent:
                    title = f"📈 {symbol} is rising!"
                    body = f"Entry:{entry_price}, Current:{round(last_price, 2)}, {note} ({round(milestone_price, 2)})"
                    log_notification("profit-milestone", symbol, title, body)
                    if FCM_TEST_TOKEN:
                        tasks.append(send_push_async(
                            to_token=FCM_TEST_TOKEN,
                            title=title,
                            body=body,
                            data={"symbol": symbol, "type": "profit-milestone"}
                        ))
                    sent.add(key)
            conn = db_conn()
            c = conn.cursor()
            c.execute("UPDATE positions SET profit_alerts_sent=? WHERE symbol=?", (','.join(sent), symbol))
            conn.commit()
            conn.close()

        # -------- DYNAMIC STOP-LOSS --------
        stop_sent = set(stop_alerts_sent.split(',')) if stop_alerts_sent else set()
        soft_stop_price = entry_price * (1 - soft_stop_pct / 100)
        hard_stop_price = entry_price * (1 - hard_stop_pct / 100)

        if last_price <= soft_stop_price and "soft" not in stop_sent:
            title = f"⚠️ {symbol} dropped, monitor closely!"
            body = f"Entry:{entry_price}, Current:{round(last_price,2)}, Soft stop:{round(soft_stop_price,2)}"
            log_notification("stop-loss-soft", symbol, title, body)
            if FCM_TEST_TOKEN:
                tasks.append(send_push_async(
                    to_token=FCM_TEST_TOKEN,
                    title=title,
                    body=body,
                    data={"symbol": symbol, "type": "stop-loss-soft"}
                ))
            stop_sent.add("soft")

        if last_price <= hard_stop_price and "hard" not in stop_sent:
            title = f"❌ {symbol} hit stop-loss!"
            body = f"Entry:{entry_price}, Current:{round(last_price,2)}, Hard stop:{round(hard_stop_price,2)}"
            log_notification("stop-loss-hard", symbol, title, body)
            if FCM_TEST_TOKEN:
                tasks.append(send_push_async(
                    to_token=FCM_TEST_TOKEN,
                    title=title,
                    body=body,
                    data={"symbol": symbol, "type": "stop-loss-hard"}
                ))
            stop_sent.add("hard")

        conn = db_conn()
        c = conn.cursor()
        c.execute("UPDATE positions SET stop_alerts_sent=? WHERE symbol=?", (','.join(stop_sent), symbol))
        conn.commit()
        conn.close()

    if tasks:
        await asyncio.gather(*tasks)

# ----------------------- SAVE + NOTIFY -----------------------
def save_top_picks_to_firestore(picks, top_n=TOP_N):
    ts_val = dt.utcnow().isoformat()
    docs = [{"ts": ts_val, "symbol": p.get("symbol"), "last_price": p.get("last_price"),
             "score": p.get("score"), "intraday_pct": p.get("intraday_pct")} for p in picks[:top_n]]
    try:
        db_firestore.collection("top_picks").document("latest").set({"timestamp": ts_val, "data": docs})
        logger.info("✅ Top picks saved to Firestore")
    except Exception as e:
        logger.error("❌ Failed to save top picks to Firestore: %s", e)

def log_notification(type_, symbol, title, body):
    def _write():
        conn = db_conn()
        c = conn.cursor()
        c.execute("""CREATE TABLE IF NOT EXISTS notifications(
                     id INTEGER PRIMARY KEY AUTOINCREMENT,
                     ts TEXT, type TEXT, symbol TEXT, note TEXT)""")
        ts_val = dt.utcnow().isoformat()
        c.execute("INSERT INTO notifications(ts,type,symbol,note) VALUES(?,?,?,?)",
                  (ts_val, type_, symbol, title + " - " + body))
        conn.commit()
        conn.close()
    try_db_write(_write)

# ----------------------- TOP PICKS -----------------------
scheduler = BackgroundScheduler()

async def generate_and_store_top_picks(universe, limit=TOP_N):
    picks = await generate_top_picks(universe, limit)
    ts_val = dt.utcnow().isoformat()
    for p in picks:
        p['ts'] = ts_val
        p['score'] = float(p.get('combined_score', 0.0))
        p['last_price'] = float(p.get('last_price', 0.0))
        p['intraday_pct'] = float(p.get('features', {}).get('core', {}).get('intraday_pct', 0.0)) \
            if isinstance(p.get('features', {}), dict) else 0.0
    save_top_picks_to_firestore(picks, top_n=limit)

    try:
        top0 = picks[0] if picks else None
        if top0 and top0.get('combined_score', 0.0) >= BUY_THRESHOLD:
            title = f"🔥 New BUY top pick: {top0['symbol']}"
            body = f"Score {round(top0['combined_score'], 4)} | Price {top0['last_price']}"
            log_notification("buy", top0['symbol'], title, body)
            if FCM_TEST_TOKEN:
                await send_push_async(
                    to_token=FCM_TEST_TOKEN,
                    title=title,
                    body=body,
                    data={"symbol": top0['symbol'], "type": "top-pick"}
                )
            await notify_all_users_about_top_pick(top0)
    except Exception as e:
        logger.error("Notification error: %s", e)

async def notify_all_users_about_top_pick(top_pick):
    if not top_pick:
        return

    tokens = get_all_tokens()
    if not tokens:
        return

    title = f"🔥 New BUY top pick: {top_pick['symbol']}"
    body = f"Score {round(top_pick.get('score',0), 4)} | Price {top_pick.get('last_price',0)}"

    await asyncio.gather(*[
        send_push_async(
            to_token=token,
            title=title,
            body=body,
            data={"symbol": top_pick['symbol'], "type": "top-pick"}
        ) for token in tokens
    ])

async def run_top_picks_once(limit=TOP_N):
    universe = load_universe()
    if not universe:
        logger.warning("⚠️ No universe available for top picks")
        return
    universe = universe[:200]
    logger.info(f"🚀 Running Top Picks for {len(universe)} stocks...")
    await generate_and_store_top_picks(universe, limit)
    logger.info("✅ Top picks generation completed.")

def run_top_picks_async_wrapper():
    try:
        asyncio.run(run_top_picks_once())
    except Exception as e:
        logger.error("❌ Error running scheduled top picks job: %s", e)


def monitor_positions_sync():
    asyncio.run(monitor_positions())

def run_top_picks_once_sync():
    asyncio.run(run_top_picks_once())
# ----------------------- SCHEDULER -----------------------
def start_scheduler():
    add_missing_columns()
    if scheduler.running:
        logger.warning("⚠️ Scheduler already running.")
        return
    scheduler.add_job(monitor_positions_sync, 'interval', minutes=MONITOR_INTERVAL_MIN)
    scheduler.add_job(run_top_picks_once_sync, 'interval', minutes=TOPPICKS_INTERVAL_MIN)
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
