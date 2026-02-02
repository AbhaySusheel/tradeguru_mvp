#backend/routes/register_push_token.py
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from firebase_admin import firestore
from datetime import datetime

router = APIRouter()
db = firestore.client()

# ---------- Models ----------
class PushToken(BaseModel):
    token: str


# ---------- Register Token ----------
@router.post("/register-push-token")
async def register_push_token(payload: PushToken):
    token = payload.token.strip()

    if not token:
        raise HTTPException(status_code=400, detail="Token is required")

    try:
        # Use token itself as document ID (prevents duplicates)
        db.collection("push_tokens").document(token).set({
            "createdAt": firestore.SERVER_TIMESTAMP
        })

        return {
            "success": True,
            "message": "Push token registered"
        }

    except Exception as e:
        print("❌ Error registering push token:", e)
        raise HTTPException(status_code=500, detail="Failed to register token")


# ---------- Fetch All Tokens (USED BY SCHEDULER) ----------
def get_all_tokens():
    try:
        docs = db.collection("push_tokens").stream()
        tokens = [doc.id for doc in docs]
        return tokens
    except Exception as e:
        print("❌ Failed to fetch tokens:", e)
        return []


# ---------- Debug Endpoint ----------
@router.get("/debug_tokens")
def debug_tokens():
    docs = db.collection("push_tokens").stream()
    tokens = [doc.id for doc in docs]
    return {
        "count": len(tokens),
        "tokens": tokens
    }
