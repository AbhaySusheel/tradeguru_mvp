# backend/routes/sell_stock.py

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from datetime import datetime as dt
from utils.firestore_db import positions_ref

router = APIRouter()

class SellStockRequest(BaseModel):
    symbol: str
    sell_price: float

@router.post("/sell")
async def sell_stock(req: SellStockRequest):
    symbol = req.symbol.upper()
    symbol_ns = symbol if symbol.endswith(".NS") else symbol + ".NS"

    doc_ref = positions_ref().document(symbol_ns)
    doc = doc_ref.get()

    if not doc.exists:
        raise HTTPException(status_code=404, detail="Position not found")

    data = doc.to_dict()
    if data["status"] != "OPEN":
        raise HTTPException(status_code=400, detail="Position already closed")

    entry_price = float(data["entry_price"])
    sell_price = float(req.sell_price)

    profit_loss = round(((sell_price - entry_price) / entry_price) * 100, 2)
    closed_at = dt.utcnow().isoformat()

    # ✅ Update Firestore
    doc_ref.update({
        "status": "CLOSED",
        "sell_price": sell_price,
        "closed_at": closed_at,
        "profit_loss": profit_loss,
        "close_reason": "MANUAL"
    })

    # ✅ Return everything frontend needs
    return {
        "ok": True,
        "symbol": symbol_ns,
        "entry_price": entry_price,
        "sell_price": sell_price,
        "profit_loss": profit_loss,
        "sold_at": closed_at,
        "close_reason": "MANUAL"
    }
