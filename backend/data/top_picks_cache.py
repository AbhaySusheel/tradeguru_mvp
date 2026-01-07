# backend/data/top_picks_cache.py
from datetime import datetime
from typing import Dict, Any, List

_TOP_PICKS_CACHE: Dict[str, Any] = {
    "timestamp": None,
    "interval": "5m",
    "data": [],
}

def update_top_picks_cache(data: List[Dict[str, Any]]):
    _TOP_PICKS_CACHE["timestamp"] = datetime.utcnow().isoformat()
    _TOP_PICKS_CACHE["data"] = data

def get_top_picks_cache():
    return _TOP_PICKS_CACHE