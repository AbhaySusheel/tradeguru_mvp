from fastapi import APIRouter
from db.database import SessionLocal
from models.stock_model import generate_signals
from data.fetch_data import fetch_data


from sqlalchemy import text  # add this import at the top of the file




router = APIRouter()

@router.get('/signals/today')
def get_signals():
    db = SessionLocal()
    res = db.execute(text('SELECT * FROM signals ORDER BY created_at DESC LIMIT 50')).fetchall()
    db.close()
    out = []
    for r in res:
        out.append({
            'id': r[0], 'ticker': r[1], 'side': r[2], 'entry': r[3], 'sl': r[4], 'target': r[5], 'confidence': r[6], 'reason': r[7], 'created_at': str(r[8])
        })
    return {'signals': out}
