from db.database import SessionLocal, paper_trades

class PaperTrader:
    def __init__(self, starting_capital=1500.0):
        self.capital = starting_capital
        self.positions = []

    def open_position(self, ticker, side, entry, size_percent=5, sl=None, target=None):
        size = self.capital * (size_percent / 100.0)
        qty = size / entry if entry > 0 else 0
        pos = {'ticker': ticker, 'side': side, 'entry': entry, 'qty': qty, 'sl': sl, 'target': target}
        self.positions.append(pos)
        return pos

    def close_position(self, pos, exit_price):
        pnl = 0
        if pos['side'] == 'BUY':
            pnl = (exit_price - pos['entry']) * pos['qty']
        else:
            pnl = (pos['entry'] - exit_price) * pos['qty']
        self.capital += pnl
        db = SessionLocal()
        db.execute(paper_trades.insert().values(ticker=pos['ticker'], side=pos['side'], entry=pos['entry'], exit=exit_price, pnl=float(pnl)))
        db.commit()
        db.close()
        return pnl
