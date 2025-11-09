# backend/main.py
from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, Request, HTTPException
from routes.stocks import router as stocks_router
from routes.picks import router as picks_router
from routes.positions import router as positions_router
from db_init import init_db

from scheduler import start_scheduler, find_top_picks_scheduler
from contextlib import asynccontextmanager
import os

API_KEY = os.getenv("API_KEY", "8f912050f8a403046ea774190bf4fa33")

@app.middleware("http")
async def verify_api_key(request: Request, call_next):
    # Only protect /api/positions and /api/positions/close endpoints
    if request.url.path.startswith("/api/positions"):
        key = request.headers.get("x-api-key")
        if key != API_KEY:
            raise HTTPException(status_code=401, detail="Invalid or missing API key")
    response = await call_next(request)
    return response



@asynccontextmanager
async def lifespan(app: FastAPI):
    print("🗄 Initializing database...")
    init_db()  # <— add this line


    start_scheduler()
    print("🚀 Running top stock finder once at startup...")
    # run once at startup to populate DB quickly
    try:
        find_top_picks_scheduler()
    except Exception as e:
        print("Startup top picks run failed:", e)
    yield

app = FastAPI(title="TradeGuru API", lifespan=lifespan)
app.include_router(stocks_router, prefix="/api")
app.include_router(picks_router, prefix="/api")
app.include_router(positions_router, prefix="/api")

@app.get("/")
def root():
    return {"status": "TradeGuru API running"}
