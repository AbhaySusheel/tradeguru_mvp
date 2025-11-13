import os
import sqlite3
import asyncio
import httpx 
from datetime import datetime as dt
from fastapi import APIRouter, HTTPException, BackgroundTasks
from scheduler import db_conn
from utils.notifier import send_push
from scheduler import run_top_picks_once
from firebase_admin import firestore
# Import specific Firestore types and errors for robust handling
from google.cloud.firestore_v1.base_document import DocumentSnapshot
from google.api_core.exceptions import DeadlineExceeded 
# Import the base Google Auth exceptions just in case
from google.auth.exceptions import DefaultCredentialsError

CRON_SECRET = os.getenv("CRON_SECRET", "my_secret_token")
router = APIRouter()

EXPO_PUSH_TOKEN = os.getenv("EXPO_PUSH_TOKEN", "")
FCM_TEST_TOKEN = os.getenv("TEST_DEVICE_TOKEN", "")

# -------------------- GLOBAL FIREBASE CLIENT INITIALIZATION --------------------
# FIX: Initialize the Firestore client once globally. This is the optimal approach.
DB_FIRESTORE = firestore.client()

# -------------------- HELPER FOR BLOCKING FIREBASE CALL --------------------

def _get_top_picks_data_sync(limit: int):
    """
    Synchronously fetches data from Firestore using the global client in a separate thread.
    Added verbose error handling for debugging connection issues.
    """
    try:
        db_firestore = DB_FIRESTORE 
        doc_ref = db_firestore.collection("top_picks").document("latest")
        
        # Blocking synchronous network call with a timeout
        doc: DocumentSnapshot = doc_ref.get(timeout=5) 

        if not doc.exists:
            return {"top_picks": [], "message": "No data available yet."}

        data = doc.to_dict().get("data", [])
        return {"top_picks": data[:limit]}
    
    except DeadlineExceeded as e:
        # Expected timeout error
        print(f"DEBUG: DeadlineExceeded occurred inside sync function. The read request timed out: {e}")
        raise e
    
    except DefaultCredentialsError as e:
        # Critical error if credentials are not found/configured
        print(f"CRITICAL: GOOGLE AUTH ERROR: Default credentials could not be found or are invalid. Check GOOGLE_APPLICATION_CREDENTIALS / Service Account setup. Error: {e}")
        # Re-raise as an HTTPException precursor
        raise RuntimeError(f"Authentication Error: {e}")
        
    except Exception as e:
        # Catch any other connection, environment, or unexpected error
        print(f"CRITICAL: Unhandled error in Firestore sync function: {type(e).__name__}: {e}")
        # Re-raise to be caught by the async wrapper for the 503 HTTP response
        raise RuntimeError(f"Internal Firestore Error ({type(e).__name__}): {e}")

# ------------------------- ASYNC ROUTE -------------------------

@router.get("/top-picks")
async def top_picks(limit: int = 10):
    """Return latest top picks from Firebase Firestore, running the synchronous read in a background thread."""
    try:
        # Run the potentially blocking function in a separate thread
        result = await asyncio.to_thread(_get_top_picks_data_sync, limit)
        return result

    except DeadlineExceeded as e:
        print(f"⚠️ Firestore read timeout (DeadlineExceeded): {e}")
        raise HTTPException(
            status_code=504, 
            detail="Failed to fetch data: External API timeout (Firestore)."
        )
    except RuntimeError as e:
        # Catch errors explicitly raised from the sync function (Auth, Unhandled)
        print(f"⚠️ Runtime Error from Firestore sync function: {e}")
        raise HTTPException(
            status_code=500, 
            detail=f"Internal Server Error during Firestore fetch. Check credentials/network. Error: {e}"
        )
    except Exception as e:
        print(f"⚠️ Unexpected error fetching top picks: {e}")
        raise HTTPException(
            status_code=503, 
            detail=f"Service unavailable: Failed to fetch data. Error: {e}"
        )

@router.get("/all-stocks")
def all_stocks(search: str = "", limit: int = 100, offset: int = 0):
    conn = sqlite3.connect("app.db")
    c = conn.cursor()
    if search:
        q = f"%{search.upper()}%"
        c.execute("SELECT symbol,last_price,score,intraday_pct,ts FROM all_stocks WHERE symbol LIKE ? ORDER BY score DESC LIMIT ? OFFSET ?",
                  (q, limit, offset))
    else:
        c.execute("SELECT symbol,last_price,score,intraday_pct,ts FROM all_stocks ORDER BY score DESC LIMIT ? OFFSET ?", (limit, offset))
    rows = c.fetchall()
    conn.close()
    return [{"symbol": r[0], "price": r[1], "score": r[2], "change": r[3], "ts": r[4]} for r in rows]


@router.post("/buy")
def buy_stock(payload: dict):
    symbol = payload.get("symbol")
    price = payload.get("price")
    size = payload.get("size", 1.0)
    target = payload.get("target", 5.0)
    stop = payload.get("stop", 1.5)
    if not symbol or not price:
        raise HTTPException(status_code=400, detail="symbol and price required")

    ts = dt.utcnow().isoformat()
    conn = sqlite3.connect("app.db")
    c = conn.cursor()
    c.execute("INSERT INTO positions(symbol,entry_price,entry_ts,size,status,target_pct,stop_pct) VALUES (?,?,?,?,?,?,?)",
              (symbol, price, ts, size, "OPEN", target, stop))
    conn.commit()
    conn.close()

    # Notification logic (assuming send_push is defined elsewhere)
    # title = f"Bought {symbol}"
    # body = f"Opened @ ₹{price:.2f} | Target {target}% Stop {stop}%"
    # if FCM_TEST_TOKEN:
    # 	 send_push(FCM_TEST_TOKEN, title, body)
    # if EXPO_PUSH_TOKEN:
    # 	 send_push(EXPO_PUSH_TOKEN, title, body)
    
    return {"status": "ok", "message": "Position opened"}


@router.post("/sell")
def sell_stock(payload: dict):
    symbol = payload.get("symbol")
    price = payload.get("price")
    if not symbol or not price:
        raise HTTPException(status_code=400, detail="symbol and price required")

    ts = dt.utcnow().isoformat()
    conn = sqlite3.connect("app.db")
    c = conn.cursor()
    c.execute("SELECT entry_price FROM positions WHERE symbol=? AND status='OPEN' ORDER BY id DESC LIMIT 1", (symbol,))
    row = c.fetchone()
    entry_price = row[0] if row else None

    c.execute("UPDATE positions SET exit_price=?,exit_ts=?,status='CLOSED' WHERE symbol=? AND status='OPEN'",
              (price, ts, symbol))
    conn.commit()
    conn.close()

    # Notification logic (assuming send_push is defined elsewhere)
    # pl_text = ""
    # if entry_price:
    # 	 pl_pct = (price - entry_price) / entry_price * 100
    # 	 pl_text = f" Realized P/L: {pl_pct:.2f}%"
    # 
    # title = f"Sold {symbol}"
    # body = f"Closed @ ₹{price:.2f}.{pl_text}"
    # if FCM_TEST_TOKEN:
    # 	 send_push(FCM_TEST_TOKEN, title, body)
    # if EXPO_PUSH_TOKEN:
    # 	 send_push(EXPO_PUSH_TOKEN, title, body)

    return {"status": "ok", "message": "Position closed"}


@router.get("/update-top-picks")
async def update_top_picks(token: str, background_tasks: BackgroundTasks):
    if token != CRON_SECRET:
        raise HTTPException(status_code=401, detail="Invalid token")

    try:
        # Uses BackgroundTasks to ensure the HTTP request returns immediately (200 OK)
        background_tasks.add_task(run_top_picks_once)
        return {"status": "ok", "message": "Top picks update STARTED successfully in background."}

    except Exception as e:
        print(f"Error starting top picks task: {e}")
        raise HTTPException(
            status_code=500, 
            detail=f"Failed to start task: {e}"
        )