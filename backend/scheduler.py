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
#import sqlite3
import asyncio
import json
import logging
from firebase_admin import firestore

from datetime import datetime as dt, timedelta, time as dttime
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from data.top_picks_cache import update_top_picks_cache
from pytz import timezone

from routes.register_push_token import get_all_tokens  # helper to fetch all saved Expo tokens
from utils.notifier import send_push_async  # async push version

from engine.top_picks_engine import generate_top_picks
from models.stock_model import get_default_engine
from utils.firestore_db import positions_ref
from utils.firestore_db import notifications_ref
  # migration helper

_scheduler_started = False


logger = logging.getLogger("scheduler")
logger.setLevel(logging.INFO)
if not logger.handlers:
    ch = logging.StreamHandler()
    ch.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(ch)

# ----------------------- CONFIG -----------------------

TOP_N = int(os.getenv("TOP_N", "10"))
TOPPICKS_INTERVAL_MIN = int(os.getenv("TOPPICKS_INTERVAL_MIN", "15"))
MONITOR_INTERVAL_MIN = int(os.getenv("MONITOR_INTERVAL_MIN", "2"))
FCM_TEST_TOKEN = os.getenv("TEST_DEVICE_TOKEN", "")
BUY_THRESHOLD = float(os.getenv("BUY_THRESHOLD", "0.60"))

# ----------------------- FIREBASE INIT -----------------------

def get_firestore():
    return firestore.client()

# ----------------------- DB HELPERS -----------------------

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
# Inside scheduler.py
# ----------------------- SMART MONITOR -----------------------
async def monitor_position(doc_id, pos):
    # ---- status guard ----
    if pos.get("status") != "OPEN":
        return

    symbol = pos["symbol"]
    entry_price = float(pos["entry_price"])
    predicted_max = pos.get("predicted_max")

    # ---- validation ----
    if not predicted_max or predicted_max <= entry_price:
        logger.warning(f"[{symbol}] Invalid predicted_max")
        return

    # ---- stops ----
    soft_stop_pct = float(pos.get("soft_stop_pct", 3.0))
    hard_stop_pct = float(pos.get("hard_stop_pct", 7.0))

    # ---- state ----
    highest_progress = float(pos.get("highest_profit_pct", 0.0))
    milestones_sent = set(pos.get("profit_alerts_sent", []))
    early_drop_sent = pos.get("early_drop_sent", False)

    # ---------- FETCH PRICE ----------
    try:
        engine = get_default_engine()
        res = engine.analyze_stock(symbol, fetch_if_missing=True)
        if not res.get("ok"):
            return
        last_price = float(res["last_price"])
    except Exception as e:
        logger.warning(f"[{symbol}] Price fetch failed: {e}")
        return

    # ---------- PROGRESS CALCULATION ----------
    if predicted_max == entry_price:
        return

    progress_pct = (last_price - entry_price) / (predicted_max - entry_price)

    # ---------- HARD STOP LOSS ----------
    hard_stop_price = entry_price * (1 - hard_stop_pct / 100)
    if last_price <= hard_stop_price:
        log_notification(
            "stop-loss",
            symbol,
            f"🚨 Stop Loss Hit: {symbol}",
            f"Entry {entry_price} → Exit {round(last_price, 2)}"
        )

        positions_ref().document(doc_id).update({
            "status": "CLOSED",
            "sell_price": last_price,
            "closed_at": dt.utcnow().isoformat(),
        })
        return

    # ---------- EARLY DROP WARNING ----------
    if not early_drop_sent and highest_progress == 0 and progress_pct < -0.02:
        log_notification(
            "early-drop",
            symbol,
            f"⚠️ {symbol} Falling After Buy",
            f"Price slipping below entry: {round(last_price, 2)}"
        )
        early_drop_sent = True

    # ---------- MILESTONE NOTIFICATIONS ----------
    milestones = [0.25, 0.50, 0.75, 0.90]

    if progress_pct > highest_progress:
        highest_progress = progress_pct

        for m in milestones:
            if progress_pct >= m and str(m) not in milestones_sent:
                price_at_milestone = entry_price + m * (predicted_max - entry_price)

                log_notification(
                    "profit",
                    symbol,
                    f"📈 {symbol} {int(m * 100)}% of Target",
                    f"Price reached {round(price_at_milestone, 2)}"
                )

                milestones_sent.add(str(m))

    # ---------- TRAILING SELL (PROFIT PROTECTION) ----------
    if highest_progress >= 0.25:
        trail_level = highest_progress - 0.10  # 10% pullback from peak

        if progress_pct < trail_level:
            log_notification(
                "sell",
                symbol,
                f"📉 Sell Alert: {symbol}",
                f"Dropped from {int(highest_progress * 100)}% → {int(progress_pct * 100)}%"
            )

            positions_ref().document(doc_id).update({
                "status": "CLOSED",
                "sell_price": last_price,
                "closed_at": dt.utcnow().isoformat(),
                "highest_profit_pct": highest_progress
            })
            return

    # ---------- SAVE STATE ----------
    positions_ref().document(doc_id).update({
        "highest_profit_pct": highest_progress,
        "profit_alerts_sent": list(milestones_sent),
        "early_drop_sent": early_drop_sent,
        "last_checked_at": dt.utcnow().isoformat()
    })


# ----------------------- MAIN LOOP -----------------------
async def monitor_positions():
    try:
        if not market_open_now():
            logger.info("⏸️ Market closed — skipping Positions Monitoring")
            return

        docs = positions_ref().stream()
        tasks = []

        for d in docs:
            tasks.append(monitor_position(d.id, d.to_dict()))

        if not tasks:
            logger.info("ℹ️ No positions found (Firestore)")
            return

        await asyncio.gather(*tasks)

    except Exception as e:
        logger.exception("❌ monitor_positions crashed: %s", e)
# ----------------------- SAVE + NOTIFY -----------------------
def save_top_picks_to_firestore(picks, top_n=TOP_N):
    ts_val = dt.utcnow().isoformat()
    docs = [{
        "ts": ts_val,
        "symbol": p.get("symbol"),
        "last_price": p.get("last_price"),
        "score": p.get("score"),
        "intraday_pct": p.get("intraday_pct")
    } for p in picks[:top_n]]

    try:
        db = get_firestore()
        db.collection("top_picks").document("latest").set({
            "timestamp": ts_val,
            "data": docs
        })
        logger.info("✅ Top picks saved to Firestore")
    except Exception as e:
        logger.error("❌ Failed to save top picks to Firestore: %s", e)


def log_notification(type_, symbol, title, body):
    notifications_ref().add({
        "type": type_,
        "symbol": symbol,
        "title": title,
        "body": body,
        "created_at": dt.utcnow().isoformat()
    })

# ----------------------- TOP PICKS -----------------------
scheduler = AsyncIOScheduler(timezone=timezone("Asia/Kolkata"))


async def notify_all_users_about_top_pick(top_pick):
    if not top_pick:
        return

    tokens = get_all_tokens()
    logger.warning(f"📣 TOKENS FOUND (top-pick): {len(tokens)}")
    if not tokens:
        return

    title = f"🔥 New BUY top pick: {top_pick['symbol']}"
    body = f"Score {round(top_pick.get('score',0), 4)} | Price {top_pick.get('last_price',0)}"

    for i in range(0, len(tokens), 20):
        batch = tokens[i:i + 20]
        try:
            await asyncio.gather(*[
                send_push_async(
                    to_token=token,
                    title=title,
                    body=body,
                    data={"symbol": top_pick['symbol'], "type": "top-pick"}
                ) for token in batch
            ], return_exceptions=True)
        except Exception as e:
            logger.warning(f"Push batch failed: {e}")

async def generate_and_store_top_picks(universe, limit=TOP_N):
    picks = await generate_top_picks(universe, limit)
    if not picks:
        logger.info("⚠️ No valid top picks generated")
        return

    ts_val = dt.utcnow().isoformat()
    clean = []

    for p in picks:
        if not p.get("ok"):
            logger.info(f"⏭️ Skipped {p.get('symbol')} (no data)")
            continue

        p['ts'] = ts_val
        p['score'] = float(p.get('combined_score', 0.0))
        p['last_price'] = float(p.get('last_price', 0.0))
        p['intraday_pct'] = float(
            p.get('features', {}).get('core', {}).get('intraday_pct', 0.0)
        ) if isinstance(p.get('features', {}), dict) else 0.0

        clean.append(p)

    if not clean:
        return

    save_top_picks_to_firestore(clean, top_n=limit)
    update_top_picks_cache(clean)
    logger.info("🧠 Top picks cached in memory")

    try:
        top0 = clean[0]
        if top0.get('combined_score', 0.0) >= BUY_THRESHOLD:
            title = f"🔥 New BUY top pick: {top0['symbol']}"
            body = f"Score {round(top0['combined_score'], 4)} | Price {top0['last_price']}"
            log_notification("buy", top0['symbol'], title, body)
            await notify_all_users_about_top_pick(top0)
    except Exception as e:
        logger.error("Notification error: %s", e)


async def run_top_picks_once(limit=TOP_N):
    if not market_open_now():
        logger.info("⏸️ Market closed — skipping top picks generation")
        return

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
async def safe_run_top_picks():
    try:
        await run_top_picks_once()
    except Exception as e:
        logger.exception("❌ Top picks job crashed: %s", e)


def start_scheduler():
    global _scheduler_started

    if _scheduler_started:
        logger.warning("⚠️ Scheduler already started (guarded).")
        return

    

    if scheduler.running:
        logger.warning("⚠️ Scheduler already running (APS check).")
        return

    tokens = get_all_tokens()
    logger.warning(f"🚀 PUSH TOKENS AT STARTUP: {len(tokens)}")    

    scheduler.add_job(
        monitor_positions,        # ✅ async OK
        trigger="interval",
        minutes=MONITOR_INTERVAL_MIN,
        max_instances=1,
        coalesce=True,
        id="monitor_positions"
    )

    scheduler.add_job(
        safe_run_top_picks,       # ✅ async OK
        trigger="interval",
        minutes=TOPPICKS_INTERVAL_MIN,
        max_instances=1,
        coalesce=True,
        id="top_picks"
    )

    scheduler.start()
    _scheduler_started = True

    logger.info("✅ AsyncIO Scheduler started successfully.")

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
