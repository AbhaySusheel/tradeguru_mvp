import time
import pytz
import datetime
import os
from datetime import datetime as dt
from apscheduler.schedulers.background import BackgroundScheduler

from backend.data.fetch_data import fetch_data
from backend.models.stock_model import generate_signals
from backend.db.database import SessionLocal, signals
from backend.utils.notifier import send_push


def run_realtime_trader():
    tz = pytz.timezone("Asia/Kolkata")
    market_open = datetime.time(9, 15)
    market_close = datetime.time(15, 30)
    session = SessionLocal()
    tickers = os.getenv("STOCK_LIST", "TCS.NS,INFY.NS").split(",")

    print("🚀 Starting real-time trading signal engine...")

    while True:
        now = dt.now(tz)
        current_time = now.time()

        # Run only during market hours
        if market_open <= current_time <= market_close:
            print(f"⏰ Checking signals at {now.strftime('%H:%M:%S')}")

            for ticker in tickers:
                df = fetch_data(ticker)
                sigs = generate_signals(df)

                for sig in sigs:
                    existing = session.execute(
                        signals.select()
                        .where(signals.c.symbol == ticker)
                        .where(signals.c.signal_type == sig['type'])
                        .where(signals.c.entry == sig['entry'])
                    ).fetchone()

                    if not existing:
                        session.execute(
                            signals.insert().values(
                                symbol=ticker,
                                signal_type=sig['type'],
                                reason=sig['reason'],
                                entry=sig['entry'],
                                sl=sig['sl'],
                                target=sig['target'],
                                confidence=sig['confidence'],
                                timestamp=now
                            )
                        )
                        session.commit()

                        # ✅ Send push notification
                        send_push(
                            to_token=os.getenv("TEST_DEVICE_TOKEN", ""),
                            title=f"{sig['type']} Signal for {ticker}",
                            body=f"{sig['reason']} | Entry: {sig['entry']:.2f}, Target: {sig['target']:.2f}",
                            data={"symbol": ticker, "type": sig['type']}
                        )
                        print(f"📈 Sent signal for {ticker}: {sig['type']}")

            print("✅ Cycle complete. Sleeping 3 minutes...\n")
            time.sleep(180)
        else:
            print("🕒 Market closed. Sleeping 30 minutes.")
            time.sleep(1800)


def start_scheduler():
    """
    Launches the real-time trading engine in a background scheduler.
    This keeps the main FastAPI app responsive.
    """
    scheduler = BackgroundScheduler()
    scheduler.add_job(run_realtime_trader, trigger='date', next_run_time=dt.now())
    scheduler.start()
    print("✅ Scheduler started in background.")
