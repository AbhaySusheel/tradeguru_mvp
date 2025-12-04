# backend/utils/notifier.py
import aiohttp
import asyncio
import logging
from typing import List, Dict, Optional

logger = logging.getLogger("notifier")
logger.setLevel(logging.INFO)
if not logger.handlers:
    ch = logging.StreamHandler()
    ch.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(ch)

EXPO_PUSH_URL = "https://exp.host/--/api/v2/push/send"

# -----------------------
# Global HTTP session
# -----------------------
_session: Optional[aiohttp.ClientSession] = None
_session_lock = asyncio.Lock()


async def _get_session() -> aiohttp.ClientSession:
    global _session
    async with _session_lock:
        if _session is None or _session.closed:
            _session = aiohttp.ClientSession()
        return _session


# -----------------------
# Async push notification
# -----------------------
async def send_push_async(to_token: str, title: str, body: str, data: Dict = None) -> Optional[dict]:
    """Send one Expo push notification asynchronously."""
    message = {
        "to": to_token,
        "sound": "default",
        "title": title,
        "body": body,
        "data": data or {}
    }
    try:
        session = await _get_session()
        async with session.post(EXPO_PUSH_URL, json=message, timeout=10) as resp:
            result = await resp.json()
            logger.debug("Expo push response: %s", result)
            return result
    except Exception as e:
        logger.exception("❌ Push failed for token %s: %s", to_token, e)
        return None


async def send_push_batch(
    tokens: List[str],
    title: str,
    body: str,
    data: Dict = None,
    batch_size: int = 50,
    concurrency: int = 10
):
    """Send notifications in parallel with concurrency limit."""
    if not tokens:
        return []

    sem = asyncio.Semaphore(concurrency)

    async def _send(to):
        async with sem:
            return await send_push_async(to, title, body, data)

    tasks = [_send(t) for t in tokens]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    return results


# -----------------------
# Synchronous wrapper
# -----------------------
def send_push(to_token: str, title: str, body: str, data: Dict = None):
    """Safe to call from synchronous context."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        # Inside an async loop (FastAPI), schedule as background task
        asyncio.create_task(send_push_async(to_token, title, body, data))
    else:
        asyncio.run(send_push_async(to_token, title, body, data))


# -----------------------
# Cleanup on shutdown
# -----------------------
async def close_notifier_session():
    global _session
    if _session and not _session.closed:
        await _session.close()
        logger.info("✅ Notifier session closed")
