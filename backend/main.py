from dotenv import load_dotenv
load_dotenv()

import os
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

from db_init import init_db  # Initializes Firebase and SQLite
from scheduler import start_scheduler, run_top_picks_once
from routes.stocks import router as stocks_router
from routes.picks import router as picks_router
from routes.positions import router as positions_router
from routes.register_push_token import router as push_token_router
from routes.buy_stock import router as buy_stock_router
from routes.sell_stock import router as sell_stock_router




API_KEY = os.getenv("API_KEY")

@asynccontextmanager
async def lifespan(app: FastAPI):
    print("🗄 Initializing database...")
    init_db()

    print("🚀 Running top stock finder once at startup...")
    try:
        await run_top_picks_once()
        print("✅ Initial top picks run completed")
    except Exception as e:
        print("⚠️ Startup top picks run failed:", e)

    start_scheduler()
    print("✅ Scheduler started, TradeGuru API is running")
    
    yield  # App is now running

app = FastAPI(title="TradeGuru API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*", "x-api-key"],
)

@app.middleware("http")
async def verify_api_key(request: Request, call_next):
    if request.url.path.startswith("/api/positions"):
        header_key = request.headers.get("x-api-key")
        if header_key != API_KEY:
            return JSONResponse(status_code=401, content={"detail": "Invalid or missing API key"})
    return await call_next(request)

# Include routes
app.include_router(stocks_router, prefix="/api")
app.include_router(picks_router, prefix="/api")
app.include_router(positions_router, prefix="/api")
app.include_router(push_token_router, prefix="/api")
app.include_router(buy_stock_router, prefix="/api") 
app.include_router(sell_stock_router, prefix="/api")

@app.get("/")
def root():
    return {"status": "TradeGuru API running"}
