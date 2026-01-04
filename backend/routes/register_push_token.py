# backend/routes/register_push_token.py
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import sqlite3
from datetime import datetime

DB_PATH = "app.db"  # SQLite DB

router = APIRouter()

class PushToken(BaseModel):
    token: str

@router.post("/register-push-token")
async def register_push_token(payload: PushToken):
    token = payload.token.strip()
    if not token:
        raise HTTPException(status_code=400, detail="Token is required")

    try:
        conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        c = conn.cursor()

        c.execute("""
            INSERT OR IGNORE INTO push_tokens (token)
            VALUES (?)
        """, (token, ))

        conn.commit()
        conn.close()

        return {"success": True, "message": "Token registered"}
    except Exception as e:
        print("Error registering push token:", e)
        raise HTTPException(status_code=500, detail="Failed to register token")

def db_conn():
    return sqlite3.connect(DB_PATH, check_same_thread=False)


def get_all_tokens():
    conn = db_conn()
    c = conn.cursor()
    c.execute("SELECT token FROM push_tokens")
    tokens = [row[0] for row in c.fetchall()]
    conn.close()
    return tokens

@router.get("/debug_tokens")
def debug_tokens():
    conn = db_conn()
    c = conn.cursor()
    rows = c.execute("SELECT * FROM push_tokens").fetchall()
    conn.close()
    return {"tokens": rows}

