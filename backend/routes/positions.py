# backend/routes/positions.py
from fastapi import APIRouter, Depends
from firebase_admin import firestore

router = APIRouter()
db = firestore.client()

@router.get("/positions")
def list_positions():
    docs = db.collection("positions").stream()

    open_pos = []
    closed_pos = []

    for d in docs:
        data = d.to_dict()
        data["id"] = d.id

        if data.get("status") == "OPEN":
            open_pos.append(data)
        else:
            closed_pos.append(data)

    return {
        "open": open_pos,
        "closed": closed_pos,
    }
