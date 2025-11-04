import yfinance as yf
import pandas as pd
from datetime import datetime, timedelta

def fetch_data(ticker: str):
    try:
        end = datetime.now()
        start = end - timedelta(days=200)
        df = yf.download(
            ticker,
            start=start.strftime('%Y-%m-%d'),
            end=end.strftime('%Y-%m-%d'),
            progress=False,
            interval='1d',
            auto_adjust=True  # Avoids warnings and errors
        )

        if df is None or df.empty:
            print(f"⚠️ No data for {ticker}")
            return pd.DataFrame()

        df = df.reset_index()
        return df

    except Exception as e:
        print(f"❌ Error fetching {ticker}: {e}")
        return pd.DataFrame()
