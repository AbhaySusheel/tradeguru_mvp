import aiohttp
import logging
import asyncio

logger = logging.getLogger("notifier")

EXPO_PUSH_URL = "https://exp.host/--/api/v2/push/send"

async def send_push_async(to_token: str, title: str, body: str, data: dict = None):
    message = {
        "to": to_token,
        "sound": "default",
        "title": title,
        "body": body,
        "data": data or {}
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(EXPO_PUSH_URL, json=message) as resp:
                result = await resp.json()
                logger.info(f"Expo push response: {result}")
                return result

    except Exception as e:
        logger.error(f"❌ Push failed: {e}")
        return None


def send_push(to_token, title, body, data=None):
    asyncio.run(send_push_async(to_token, title, body, data))
