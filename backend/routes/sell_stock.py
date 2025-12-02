# backend/routes/sell_stock.py
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from datetime import datetime as dt
import sqlite3
import asyncio

from scheduler import log_notification, db_conn, monitor_positions_sync

router = APIRouter()


class SellStockRequest(BaseModel):
    symbol: str
    sell_price: float


@router.post("/sell")
async def sell_stock(req: SellStockRequest):
    symbol = req.symbol.upper()
    sell_price = req.sell_price

    conn = db_conn()
    c = conn.cursor()
    # Check if position exists and is OPEN
    c.execute(
        "SELECT status, entry_price, predicted_max, soft_stop_pct, hard_stop_pct, profit_alerts_sent, stop_alerts_sent "
        "FROM positions WHERE symbol=? AND status='OPEN'",
        (symbol,),
    )
    row = c.fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail=f"No open position found for {symbol}")

    (
        status,
        entry_price,
        predicted_max,
        soft_stop_pct,
        hard_stop_pct,
        profit_alerts_sent,
        stop_alerts_sent,
    ) = row

    # Update position to CLOSED
    ts_val = dt.utcnow().isoformat()
    c.execute(
        """UPDATE positions 
           SET status='CLOSED', sell_price=?, closed_at=? 
           WHERE symbol=?""",
        (sell_price, ts_val, symbol),
    )
    conn.commit()
    conn.close()

    # Log sell notification
    profit_loss = round(sell_price - entry_price, 2)
    title = f"🛑 Sold {symbol}"
    body = f"Sold at {sell_price} | P/L: {profit_loss}"
    log_notification("sell", symbol, title, body)

    # --------------------------
    # Trigger async monitoring safely for this position
    # Import monitor_position locally to avoid circular import
    async def monitor_closed_position():
        from scheduler import monitor_position
        await monitor_position(
            (symbol, entry_price, predicted_max, "CLOSED", soft_stop_pct, hard_stop_pct, profit_alerts_sent, stop_alerts_sent)
        )

    asyncio.create_task(monitor_closed_position())

    # Optional: trigger full monitoring (all positions) in background
    # asyncio.create_task(asyncio.to_thread(monitor_positions_sync))

    return {
        "ok": True,
        "symbol": symbol,
        "sell_price": sell_price,
        "profit_loss": profit_loss,
        "message": "Position closed and monitoring updated",
    }
