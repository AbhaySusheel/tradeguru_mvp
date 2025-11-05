from fastapi import APIRouter
import yfinance as yf

router = APIRouter()

@router.get("/stocks")
def get_stocks():
    stock_symbols = ["TCS.NS", "INFY.NS", "RELIANCE.NS", "HDFCBANK.NS", "ICICIBANK.NS"]
    stocks = []

    for symbol in stock_symbols:   
        try:
            ticker = yf.Ticker(symbol)
            info = ticker.history(period="1d")
            if not info.empty:
                last_quote = info.tail(1).iloc[0]
                price = round(last_quote["Close"], 2)
                prev_close = last_quote["Open"]
                change = round(((price - prev_close) / prev_close) * 100, 2)
                stocks.append({
                    "symbol": symbol.replace(".NS", ""),
                    "price": price,
                    "change": change
                })
        except Exception as e:
            print(f"Error fetching {symbol}: {e}")

    return stocks
