import os
import firebase_admin
from firebase_admin import credentials, messaging

# Initialize Firebase app only once
if not firebase_admin._apps:
    # Try environment variable first
    cred_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")

    # ✅ Fallback to one directory above (../firebase_key.json)
    if not cred_path:
        base_dir = os.path.dirname(os.path.abspath(__file__))
        cred_path = os.path.join(base_dir, "..", "firebase_key.json")

    cred_path = os.path.normpath(cred_path)

    if not os.path.exists(cred_path):
        print(f"❌ Firebase key file not found at: {cred_path}")
    else:
        cred = credentials.Certificate(cred_path)
        firebase_admin.initialize_app(cred)
        print(f"✅ Firebase initialized using: {cred_path}")

def send_push(to_token: str, title: str, body: str, data: dict = None):
    """Send a push notification via Firebase Cloud Messaging (FCM)."""
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
