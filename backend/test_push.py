# backend/test_push.py
import asyncio
from utils.notifier import send_push_async

async def main():
    token = "ExponentPushToken[fAmEtjBDVoEksN_mn1hwNA]"

    result = await send_push_async(
        token,
        title="Test Notification",
        body="Hello! This is a working test notification.",
        data={"test": True}
    )

    print("\nFINAL RESULT:")
    print(result)

asyncio.run(main())
