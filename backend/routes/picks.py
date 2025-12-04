# backend/routes/picks.py
import os
import sqlite3
import asyncio
import logging
from datetime import datetime as dt
from fastapi import APIRouter, HTTPException, BackgroundTasks
from pydantic import BaseModel

from scheduler import run_top_picks_once
from utils.notifier import send_push_async
from firebase_admin import firestore
from google.auth.exceptions import DefaultCredentialsError

logger = logging.getLogger("picks")
logger.setLevel(logging.INFO)
if not logger.handlers:
    ch = logging.StreamHandler()
    ch.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(ch)

router = APIRouter()
DB_PATH = "app.db"

# Firestore client global
try:
    DB_FIRESTORE = firestore.client()
except Exception:
    DB_FIRESTORE = None


# -----------------------
# Push Token Model
# -----------------------
class PushTokenBody(BaseModel):
    token: str


@router.post("/registerPushToken")
async def register_push_token(payload: PushTokenBody):
    if DB_FIRESTORE is None:
        raise HTTPException(status_code=503, detail="Firestore client not initialized")
    try:
        doc_ref = DB_FIRESTORE.collection("push_tokens").document(payload.token)
        await asyncio.to_thread(doc_ref.set, {"token": payload.token, "created_at": dt.utcnow().isoformat()})
        return {"status": "ok", "saved": True}
    except Exception as e:
        logger.exception(f"❌ Failed to save push token: {e}")
        raise HTTPException(status_code=500, detail="Failed to save token")


# -----------------------
# Buy endpoint
# -----------------------
@router.post("/buy")
def buy_stock(payload: dict):
    symbol = payload.get("symbol")
    price = payload.get("price")
    size = payload.get("size", 1.0)
    target = payload.get("target", 5.0)
    stop = payload.get("stop", 1.5)

    if not symbol or price is None:
        raise HTTPException(status_code=400, detail="symbol and price required")

    ts = dt.utcnow().isoformat()
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        """INSERT INTO positions(symbol, entry_price, created_at, size, status, predicted_max, soft_stop_pct, hard_stop_pct)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (symbol, price, ts, size, "OPEN", target, stop, stop)
    )
    conn.commit()
    conn.close()
    return {"status": "ok", "message": "Position opened"}


# -----------------------
# Sell endpoint
# -----------------------
@router.post("/sell")
def sell_stock(payload: dict):
    symbol = payload.get("symbol")
    price = payload.get("price")

    if not symbol or price is None:
        raise HTTPException(status_code=400, detail="symbol and price required")

    ts = dt.utcnow().isoformat()
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # Get last open entry
    c.execute(
        "SELECT entry_price FROM positions WHERE symbol=? AND status='OPEN' ORDER BY id DESC LIMIT 1",
        (symbol,)
    )
    row = c.fetchone()
    entry_price = row[0] if row else None

    c.execute(
        "UPDATE positions SET sell_price=?, closed_at=?, status='CLOSED' WHERE symbol=? AND status='OPEN'",
        (price, ts, symbol)
    )
    conn.commit()
    conn.close()
    return {"status": "ok", "message": "Position closed"}


# -----------------------
# Top Picks update
# -----------------------
@router.get("/update-top-picks")
async def update_top_picks(token: str, background_tasks: BackgroundTasks):
    CRON_SECRET = os.getenv("CRON_SECRET", "my_secret_token")
    if token != CRON_SECRET:
        raise HTTPException(status_code=401, detail="Invalid token")
    try:
        background_tasks.add_task(run_top_picks_once)
        return {"status": "ok", "message": "Top picks update STARTED successfully in background."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to start task: {e}")


# -----------------------
# Get latest cached top picks from Firestore
# -----------------------
@router.get("/top-picks")
async def get_cached_top_picks():
    if DB_FIRESTORE is None:
        raise HTTPException(status_code=503, detail="Firestore client not initialized")
    try:
        doc_ref = DB_FIRESTORE.collection("top_picks").document("latest")
        doc = await asyncio.to_thread(doc_ref.get)
        if doc.exists:
            return {"status": "ok", "data": doc.to_dict()}
        else:
            raise HTTPException(status_code=504, detail="Firestore read timeout")
    except DefaultCredentialsError as e:
        raise HTTPException(status_code=500, detail=f"Firestore auth error: {e}")
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Fai_
