# TradeGuru - AI Stock Advisor (MVP)

This is a minimal MVP for a mobile app that suggests short-term stock signals and sends daily notifications.
It includes a FastAPI backend and a React Native (Expo) frontend.

Important: This project is for education and paper-trading only. Do NOT use with real funds until you fully validate strategies.

Quick start:
1. Backend:
   - python 3.10+
   - cd backend
   - python -m venv venv
   - source venv/bin/activate  (or venv\Scripts\activate on Windows PowerShell)
   - pip install -r requirements.txt
   - create a .env file using .env.example
   - uvicorn main:app --reload --host 0.0.0.0 --port 8000
2. Frontend:
   - Node.js 16+ and npm
   - cd frontend
   - npm install
   - npx expo start
