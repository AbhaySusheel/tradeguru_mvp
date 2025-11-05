import time
from datetime import datetime as dt
from apscheduler.schedulers.background import BackgroundScheduler
from utils.market import fetch_intraday, compute_features
from utils.score import score_from_features
import csv
import sqlite3

DB = "app.db"

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
        c.execute("INSERT INTO top_picks(ts,symbol,last_price,score,intraday_pct) VALUES (?,?,?,?,?)",
                  (ts, p.get("symbol"), p.get("last_price"), p.get("score"), p.get("intraday_pct")))
    conn.commit()
    conn.close()

def find_top_picks_scheduler(batch_size=40):
    universe = load_universe("tickers.csv")
    features_list = []

    for i in range(0, len(universe), batch_size):
        batch = universe[i:i+batch_size]
        for symbol in batch:
            df = fetch_intraday(symbol, interval="5m", period="1d")
            feats = compute_features(df)
            if feats:
                feats["symbol"] = symbol.replace(".NS", "")
                features_list.append(feats)
        time.sleep(2)

    if not features_list:
        return []

    scored = score_from_features(features_list)
    save_top_picks(scored, top_n=5)
    print("✅ Top picks updated successfully.")
    return scored[:5]

# ✅ Add this function
def start_scheduler():
    """
    Launches the real-time trading engine in a background scheduler.
    This keeps the main FastAPI app responsive.
    """
    scheduler = BackgroundScheduler()
    scheduler.add_job(find_top_picks_scheduler, 'interval', minutes=30)
    scheduler.start()
    print("✅ Scheduler started and will run every 30 minutes.")
