# backend/scheduler.py
import time
import os
from datetime import datetime as dt
from apscheduler.schedulers.background import BackgroundScheduler
from utils.market import fetch_intraday, compute_features
from utils.score import score_from_features
from utils.notifier import send_push
from utils.positions import open_position, close_position, list_open_positions
import sqlite3

DB = "app.db"

# Config
BATCH_SIZE = int(os.getenv("BATCH_SIZE", "40"))
TOP_N = int(os.getenv("TOP_N", "5"))
DEFAULT_TARGET_PCT = float(os.getenv("DEFAULT_TARGET_PCT", "5.0"))
DEFAULT_STOP_PCT = float(os.getenv("DEFAULT_STOP_PCT", "1.5"))
FCM_TEST_TOKEN = os.getenv("TEST_DEVICE_TOKEN", "")  # set in .env / Render env

def load_universe(csv_path="tickers.csv"):
    with open(csv_path) as f:
        return [line.strip() for line in f if line.strip()]

def save_top_picks(picks, top_n=5):
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS top_picks(
                 ts TEXT, symbol TEXT, last_price REAL, score REAL, intraday_pct REAL)""")
    ts = dt.utcnow().isoformat()
    for p in picks[:top_n]:
        c.execute(
            "INSERT INTO top_picks(ts,symbol,last_price,score,intraday_pct) VALUES (?,?,?,?,?)",
            (ts, p.get("symbol"), p.get("last_price"), p.get("score"), p.get("intraday_pct"))
        )
    conn.commit()
    conn.close()

def find_top_picks_scheduler(batch_size=BATCH_SIZE):
    universe = load_universe("tickers.csv")
    if not universe:
        print("⚠️ No tickers found in tickers.csv")
        return []

    features_list = []

    for i in range(0, len(universe), batch_size):
        batch = universe[i:i+batch_size]
        for symbol in batch:
            try:
                df = fetch_intraday(symbol, interval="5m", period="1d")
                feats = compute_features(df)
                if feats:
                    feats["symbol"] = symbol.replace(".NS", "")
                    features_list.append(feats)
            except Exception as e:
                print(f"Error fetching {symbol}: {e}")
        time.sleep(2)  # small pause between batches

    if not features_list:
        print("⚠️ No features calculated for any symbol in this run")
        return []

    scored = score_from_features(features_list)
    save_top_picks(scored, top_n=TOP_N)
    print("✅ Top picks updated successfully.")
    # After saving picks, evaluate buy rules
    try:
        evaluate_and_maybe_open(scored)
    except Exception as e:
        print("Error in evaluate_and_maybe_open:", e)
    return scored[:TOP_N]

# -----------------------
# Position management & monitoring
# -----------------------
def evaluate_and_maybe_open(picks):
    """Open virtual positions for high scoring picks following simple rules."""
    open_syms = {row[1] for row in list_open_positions()}  # (id, symbol, ...)
    for p in picks[:TOP_N]:
        sym = p['symbol']
        price = p['last_price']
        score = p['score']
        ma_diff = p.get('ma_diff', 0)
        vol_ratio = p.get('vol_ratio', 0)

        # sample buy rules (tweak weights/thresholds as you wish)
        if score >= 0.6 and ma_diff > 0 and vol_ratio > 1.2:
            if sym not in open_syms:
                open_position(sym, price, size=1.0, target_pct=DEFAULT_TARGET_PCT, stop_pct=DEFAULT_STOP_PCT)
                msg = f"Buy suggestion: {sym} @ {price:.2f} | Target {DEFAULT_TARGET_PCT}% Stop {DEFAULT_STOP_PCT}%"
                print("🔔", msg)
                # attempt push
                if FCM_TEST_TOKEN:
                    try:
                        send_push(to_token=FCM_TEST_TOKEN, title=f"BUY {sym}", body=msg, data={"symbol": sym})
                    except Exception as e:
                        print("Push failed:", e)

def monitor_positions_job():
    """Check open positions often and close when target/stop hit (virtual)."""
    positions = list_open_positions()
    if not positions:
        return

    for pos in positions:
        _id, sym, entry_price, entry_ts, size, target_pct, stop_pct = pos
        try:
            df = fetch_intraday(sym + ".NS", interval="1m", period="1d")
            feats = compute_features(df)
            if not feats:
                continue
            current = feats['last_price']
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
        except Exception as e:
            print("monitor_positions_job error for", sym, e)

# -----------------------
# Scheduler starter
# -----------------------
def start_scheduler():
    """
    Launches the real-time engine in a background scheduler.
    """
    scheduler = BackgroundScheduler()
    # top picks: every 15 minutes (adjustable)
    scheduler.add_job(find_top_picks_scheduler, 'interval', minutes=int(os.getenv("TOPPICKS_INTERVAL_MIN", "15")))
    # monitor positions: every 1 minute
    scheduler.add_job(monitor_positions_job, 'interval', minutes=int(os.getenv("MONITOR_INTERVAL_MIN", "1")))
    scheduler.start()
    print("✅ Scheduler started and running jobs: top-picks + monitor_positions")
