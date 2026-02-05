# backend/routes/buy_stock.py
"""
Buy Stock API
- Inserts a new position into the database
- Automatically triggers monitoring for profit/loss notifications
"""
from fastapi import APIRouter, HTTPException, Request
from datetime import datetime
from firebase_admin import firestore

router = APIRouter()
db = firestore.client()

@router.post("/buy")
async def buy_stock(request: Request):
    data = await request.json()

    symbol = data.get("symbol")
    entry_price = data.get("entry_price")
    predicted_max = data.get("predicted_max")

    if not symbol or entry_price is None:
        raise HTTPException(status_code=400, detail="symbol and entry_price required")

    symbol_ns = symbol if symbol.endswith(".NS") else symbol + ".NS"

    doc = {
        "symbol": symbol_ns,
        "entry_price": entry_price,
        "predicted_max": predicted_max,
        "status": "OPEN",
        "soft_stop_pct": 3.0,
        "hard_stop_pct": 7.0,
        "profit_alerts_sent": [],
        "stop_alerts_sent": [],
        "created_at": datetime.utcnow().isoformat(),
    }

    db.collection("positions").add(doc)

    return {"ok": True, "symbol": symbol_ns, "status": "OPEN"}
