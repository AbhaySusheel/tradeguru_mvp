from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from routes.stocks import router as stocks_router
from routes.picks import router as picks_router
from routes.positions import router as positions_router
from db_init import init_db
from scheduler import start_scheduler, find_top_picks_scheduler
from contextlib import asynccontextmanager
import os

API_KEY = os.getenv("API_KEY")

@asynccontextmanager
async def lifespan(app: FastAPI):
    print("🗄 Initializing database...")
    init_db()

    start_scheduler()
    print("🚀 Running top stock finder once at startup...")
    try:
        find_top_picks_scheduler()
    except Exception as e:
        print("Startup top picks run failed:", e)
    yield

app = FastAPI(title="TradeGuru API", lifespan=lifespan)

# ✅ Allow frontend to send x-api-key via CORS
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
        print(f"🔍 Expected API_KEY: {API_KEY}")
        print(f"🔍 Got header: {header_key}")
        if header_key != API_KEY:
            return JSONResponse(status_code=401, content={"detail": "Invalid or missing API key"})
    return await call_next(request)

app.include_router(stocks_router, prefix="/api")
app.include_router(picks_router, prefix="/api")
app.include_router(positions_router, prefix="/api")

@app.get("/")
def root():
    return {"status": "TradeGuru API running"}
