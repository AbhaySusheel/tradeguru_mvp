from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI
from routes.stocks import router as stocks_router
from scheduler import start_scheduler, find_top_picks_scheduler
from contextlib import asynccontextmanager


@asynccontextmanager
async def lifespan(app: FastAPI):
    start_scheduler()
    print("🚀 Running top stock finder once at startup...")
    find_top_picks_scheduler()
    yield


app = FastAPI(title="TradeGuru API", lifespan=lifespan)
app.include_router(stocks_router, prefix="/api")


@app.get("/")
def root():
    return {"status": "TradeGuru API running"}
