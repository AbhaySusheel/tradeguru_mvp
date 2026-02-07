#backend/routes/closed_positions.py
from fastapi import APIRouter
from datetime import datetime, timedelta
from typing import Optional
from utils.firestore_db import positions_ref

router = APIRouter()

@router.get("/closed-positions")
async def get_closed_positions(days: Optional[int] = None):
    now = datetime.utcnow()
    cutoff = now - timedelta(days=days) if days else None

    docs = positions_ref().stream()
    result = []

    for d in docs:
        pos = d.to_dict()
        if pos.get("status") != "CLOSED":
            continue

        closed_at_str = pos.get("closed_at")
        if not closed_at_str:
            continue

        closed_at = datetime.fromisoformat(closed_at_str)

        if cutoff and closed_at < cutoff:
            continue

        result.append(pos)

    result.sort(key=lambda x: x["closed_at"], reverse=True)

    return {
        "ok": True,
        "positions": result
    }
