# backend/debug_top_picks.py

from models.stock_model import get_default_engine
from utils.market import load_universe  # assuming this returns list of symbols

def debug_top_picks(verbose=True):
    engine = get_default_engine(verbose=True)
    universe = load_universe()  # list of symbols
    
    if not universe:
        print("Universe is empty! Check load_universe().")
        return
    
    print(f"Debugging top picks for {len(universe)} symbols...\n")
    
    results = []
    for sym in universe:
        try:
            res = engine.analyze_stock(sym, fetch_if_missing=True)
            ml = res.get("ml_buy_prob", 0)
            eng = res.get("engine_score", 0)
            combined = res.get("combined_score", 0)
            label = res.get("label", "N/A")
            ok = res.get("ok", False)
            
            print(f"{sym:10} | ok={ok} | ML={ml:.3f} | Engine={eng:.3f} | Combined={combined:.3f} | Label={label}")
            results.append((sym, ml, eng, combined, label))
        except Exception as e:
            print(f"{sym:10} | ERROR: {e}")
    
    # Optionally, sort by combined score
    results.sort(key=lambda x: x[3], reverse=True)
    
    print("\nTop 10 by combined score:")
    for r in results[:10]:
        print(f"{r[0]:10} | Combined={r[3]:.3f} | Label={r[4]}")

if __name__ == "__main__":
    debug_top_picks()
