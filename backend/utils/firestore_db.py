# backend/utils/firestore_db.py
from firebase_admin import firestore

_db = firestore.client()

def firestore_db():
    """Return Firestore client"""
    return _db

def positions_ref():
    return _db.collection("positions")

def notifications_ref():
    return _db.collection("notifications")
