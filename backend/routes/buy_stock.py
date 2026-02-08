# backend/routes/buy_stock.py
"""
Buy Stock API
- Inserts a new position into the database
- Automatically triggers monitoring for profit/loss notifications
"""
from fastapi import APIRouter, HTTPException, Request
from datetime import datetime as dt
from utils.firestore_db import positions_ref

router = APIRouter()

DEFAULT_SOFT_STOP = 3.0
DEFAULT_HARD_STOP = 7.0


@router.post("/buy")
async def buy_stock(request: Request):
    data = await request.json()

    symbol = data.get("symbol")
    entry_price = data.get("entry_price")
    predicted_max = data.get("predicted_max")

    if not symbol or entry_price is None:
        raise HTTPException(status_code=400, detail="symbol and entry_price required")

    symbol_ns = symbol if symbol.endswith(".NS") else symbol + ".NS"
    doc_ref = positions_ref().document(symbol_ns)

    doc_ref.set({
        "symbol": symbol_ns,
        "entry_price": entry_price,

        # optional (keep for analytics / UI)
        "predicted_max": predicted_max,

        "status": "OPEN",
        "soft_stop_pct": DEFAULT_SOFT_STOP,
        "hard_stop_pct": DEFAULT_HARD_STOP,

        # 🔥 REQUIRED STATE FIELDS
        "highest_profit_pct": 0.0,
        "profit_alerts_sent": [],
        "stop_alerts_sent": [],

        "created_at": dt.utcnow().isoformat(),
        "closed_at": None,
        "sell_price": None
    })

    return {
        "ok": True,
        "symbol": symbol_ns,
        "entry_price": entry_price,
        "status": "OPEN"
    }
