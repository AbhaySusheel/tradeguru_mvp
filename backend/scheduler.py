# backend/scheduler.py
import os
import time
import sqlite3
import requests
from datetime import datetime as dt, timedelta
from apscheduler.schedulers.background import BackgroundScheduler
from utils.market import fetch_intraday, compute_features
from utils.score import score_from_features
from utils.notifier import send_push
from utils.positions import open_position, close_position, list_open_positions

DB = "app.db"

# Configuration
BATCH_SIZE = int(os.getenv("BATCH_SIZE", "40"))
TOP_N = int(os.getenv("TOP_N", "5"))
DEFAULT_TARGET_PCT = float(os.getenv("DEFAULT_TARGET_PCT", "5.0"))
DEFAULT_STOP_PCT = float(os.getenv("DEFAULT_STOP_PCT", "1.5"))
FCM_TEST_TOKEN = os.getenv("TEST_DEVICE_TOKEN", "")
NOTIFY_COOLDOWN_MIN = int(os.getenv("NOTIFY_COOLDOWN_MIN", "15"))


# --------------------- DB helpers ---------------------
def upsert_all_stock(s):
    conn = sqlite3.connect(DB)
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
    """, (s['symbol'], s['last_price'], s['intraday_pct'], s.get('ma_diff', 0),
          s.get('vol_ratio', 0), s.get('rsi', 50), s['score'], s['ts']))
    conn.commit()
    conn.close()


def get_current_top_scores(limit=10):
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("SELECT symbol, score FROM all_stocks ORDER BY score DESC LIMIT ?", (limit,))
    rows = c.fetchall()
    conn.close()
    return rows


def log_notification(type_, symbol, title, body):
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    ts = dt.utcnow().isoformat()
    c.execute("INSERT INTO notifications(ts,type,symbol,title,body) VALUES (?,?,?,?,?)",
              (ts, type_, symbol, title, body))
    conn.commit()
    conn.close()


# --------------------- Push notifications ---------------------
def send_expo_push(token, title, body, data=None):
    if not token:
        print("⚠️ No push token set")
        return
    payload = {
        "to": token,
        "sound": "default",
        "title": title,
        "body": body,
        "data": data or {}
    }
    try:
        r = requests.post("https://exp.host/--/api/v2/push/send", json=payload, timeout=10)
        print("Push status:", r.status_code, r.text)
    except Exception as e:
        print("Push send error:", e)


# --------------------- Top picks ---------------------
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
        batch = universe[i:i + batch_size]
        for symbol in batch:
            try:
                df = fetch_intraday(symbol, interval="5m", period="1d")
                feats = compute_features(df)
                if feats:
                    feats["symbol"] = symbol.replace(".NS", "")
                    features_list.append(feats)
            except Exception as e:
                print(f"Error fetching {symbol}: {e}")
        time.sleep(2)

    if not features_list:
        return []

    scored = score_from_features(features_list)
    ts = dt.utcnow().isoformat()

    current_tops = get_current_top_scores(limit=TOP_N)
    prev_best_score = current_tops[0][1] if current_tops else 0

    for p in scored:
        p['ts'] = ts
        upsert_all_stock(p)

    new_best = scored[0] if scored else None
    if new_best and new_best['score'] > prev_best_score + 0.05:
        title = f"New top pick: {new_best['symbol']}"
        body = f"Expected profit potential {round(new_best['score'] * 100, 2)}%"
        log_notification("new_top", new_best['symbol'], title, body)
        if FCM_TEST_TOKEN:
            send_push(FCM_TEST_TOKEN, title, body, data={"symbol": new_best['symbol']})

    save_top_picks(scored, top_n=TOP_N)
    evaluate_and_maybe_open(scored)
    print("✅ Top picks updated successfully.")
    return scored[:TOP_N]


# --------------------- Position Management ---------------------
def evaluate_and_maybe_open(picks):
    open_syms = {row[1] for row in list_open_positions()}
    for p in picks[:TOP_N]:
        sym = p['symbol']
        price = p['last_price']
        score = p['score']
        ma_diff = p.get('ma_diff', 0)
        vol_ratio = p.get('vol_ratio', 0)

        if score >= 0.6 and ma_diff > 0 and vol_ratio > 1.2:
            if sym not in open_syms:
                open_position(sym, price, size=1.0,
                              target_pct=DEFAULT_TARGET_PCT, stop_pct=DEFAULT_STOP_PCT)
                msg = f"Buy signal: {sym} @ ₹{price:.2f} | Target {DEFAULT_TARGET_PCT}% Stop {DEFAULT_STOP_PCT}%"
                print("🔔", msg)
                if FCM_TEST_TOKEN:
                    send_push(FCM_TEST_TOKEN, f"BUY {sym}", msg, data={"symbol": sym})


def monitor_positions_job():
    """Enhanced continuous monitoring with warnings and throttled notifications"""
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("SELECT id,symbol,entry_price,entry_ts,size,target_pct,stop_pct FROM positions WHERE status='OPEN'")
    rows = c.fetchall()
    conn.close()
    if not rows:
        return

    for row in rows:
        _id, sym, entry_price, entry_ts, size, target_pct, stop_pct = row
        try:
            df = fetch_intraday(sym + ".NS", interval="1m", period="1d")
            feats = compute_features(df)
            if not feats:
                continue

            current = feats['last_price']
            pct = (current - entry_price) / entry_price * 100

            # SELL - Profit reached
            if pct >= target_pct:
                close_position(sym, current)
                msg = f"🎯 Target hit: Sell {sym} @ ₹{current:.2f} (+{pct:.2f}%)"
                print(msg)
                if FCM_TEST_TOKEN:
                    send_push(FCM_TEST_TOKEN, f"SELL {sym}", msg)
                continue

            # STOP - Loss reached
            if pct <= -stop_pct:
                close_position(sym, current)
                msg = f"⚠️ Stop loss: Sell {sym} @ ₹{current:.2f} ({pct:.2f}%)"
                print(msg)
                if FCM_TEST_TOKEN:
                    send_push(FCM_TEST_TOKEN, f"SELL {sym}", msg)
                continue

            # WARNING - Gradual loss alert
            if pct < 0 and abs(pct) >= 0.5 * stop_pct:  # half-way to stop loss
                if can_send_cooldown(sym):
                    msg = f"📉 Warning: {sym} down {pct:.2f}%, watch closely!"
                    print(msg)
                    if FCM_TEST_TOKEN:
                        send_push(FCM_TEST_TOKEN, f"Warning on {sym}", msg)

        except Exception as e:
            print("monitor_positions_job error for", sym, e)


def can_send_cooldown(symbol):
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("SELECT last_warn_ts FROM notification_cooldown WHERE symbol=?", (symbol,))
    row = c.fetchone()
    now = dt.utcnow()
    if not row:
        c.execute("INSERT OR REPLACE INTO notification_cooldown(symbol,last_warn_ts) VALUES (?,?)",
                  (symbol, now.isoformat()))
        conn.commit()
        conn.close()
        return True
    last_ts = dt.fromisoformat(row[0])
    if now - last_ts >= timedelta(minutes=NOTIFY_COOLDOWN_MIN):
        c.execute("UPDATE notification_cooldown SET last_warn_ts=? WHERE symbol=?",
                  (now.isoformat(), symbol))
        conn.commit()
        conn.close()
        return True
    conn.close()
    return False


# --------------------- Scheduler ---------------------
def start_scheduler():
    scheduler = BackgroundScheduler()
    scheduler.add_job(find_top_picks_scheduler, 'interval', minutes=int(os.getenv("TOPPICKS_INTERVAL_MIN", "15")))
    scheduler.add_job(monitor_positions_job, 'interval', minutes=int(os.getenv("MONITOR_INTERVAL_MIN", "1")))
    scheduler.start()
    print("✅ Scheduler started: monitoring + top picks engine active.")
