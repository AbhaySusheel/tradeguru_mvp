import os
import firebase_admin
from firebase_admin import credentials, messaging

# Initialize Firebase app only once
if not firebase_admin._apps:
   cred_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")

if not cred_path:
    print("❌ GOOGLE_APPLICATION_CREDENTIALS not set — skipping push notifications.")
else:
    cred_path = os.path.normpath(cred_path)  # ✅ Normalize Windows path
    if not os.path.exists(cred_path):
        print(f"❌ Firebase key file not found at: {cred_path}")
    else:
        cred = credentials.Certificate(cred_path)
        firebase_admin.initialize_app(cred)
        print(f"✅ Firebase initialized using: {cred_path}")

def send_push(to_token: str, title: str, body: str, data: dict = None):
    """
    Sends a push notification via Firebase Cloud Messaging (HTTP v1).
    to_token: FCM device registration token
    title: Notification title
    body: Notification body
    data: Optional dict for extra payload data
    """
    if not firebase_admin._apps:
        print("⚠️ Firebase not initialized — skipping push.")
        return False

    try:
        message = messaging.Message(
            notification=messaging.Notification(title=title, body=body),
            data={str(k): str(v) for k, v in (data or {}).items()},
            token=to_token
        )
        response = messaging.send(message)
        print(f"✅ Push sent successfully: {response}")
        return True
    except Exception as e:
        print(f"❌ Push failed: {e}")
        return False
