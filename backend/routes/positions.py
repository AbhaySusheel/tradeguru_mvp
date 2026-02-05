# backend/routes/positions.py

from fastapi import APIRouter
from utils.firestore_db import positions_ref

router = APIRouter()

@router.get("/positions")
def list_positions():
    docs = positions_ref().stream()

    open_positions = []
    closed_positions = []

    for d in docs:
        rec = d.to_dict()

        if rec["status"] == "OPEN":
            open_positions.append(rec)
        else:
            closed_positions.append(rec)

    return {
        "open": open_positions,
        "closed": closed_positions
    }
