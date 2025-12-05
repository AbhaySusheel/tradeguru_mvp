// services/api.js
import axios from "axios";

const BASE_URL = "https://tradeguru-mvp.onrender.com"; // Backend URL

const API_KEY = "mysecret123"; // for /positions endpoint

// -------------------------
// Top Picks
// -------------------------
export const fetchTopPicks = async () => {
  try {
    const res = await axios.get(`${BASE_URL}/api/top_picks`);
    return res.data; // expected: [{symbol, last_price, predicted_max, score, intraday_pct}, ...]
  } catch (err) {
    console.error("Error fetching top picks:", err);
    return [];
  }
};

// -------------------------
// Positions (Open + Closed)
// -------------------------
export const fetchPositions = async () => {
  try {
    const res = await axios.get(`${BASE_URL}/api/positions`, {
      headers: { "x-api-key": API_KEY },
    });
    return res.data; // expected: [{id, symbol, entry_price, predicted_max, status, sell_price, ...}, ...]
  } catch (err) {
    console.error("Error fetching positions:", err);
    return [];
  }
};

// -------------------------
// Buy Stock
// -------------------------
export const buyStock = async (symbol, price, target = 5.0, size = 1.0, stop = 1.5) => {
  try {
    const res = await axios.post(`${BASE_URL}/api/buy`, {
      symbol,
      price,
      target,
      size,
      stop,
    });
    return res.data;
  } catch (err) {
    console.error("Error buying stock:", err);
    throw err;
  }
};

// -------------------------
// Sell Stock
// -------------------------
export const sellStock = async (symbol, price) => {
  try {
    const res = await axios.post(`${BASE_URL}/api/sell`, {
      symbol,
      price,
    });
    return res.data;
  } catch (err) {
    console.error("Error selling stock:", err);
    throw err;
  }
};

// -------------------------
// Fetch Top Picks + Add Buy Confidence (Optional)
// -------------------------
export const fetchTopPicksWithConfidence = async () => {
  const picks = await fetchTopPicks();
  return picks.map((p) => ({
    ...p,
    buyConfidence: p.buy_confidence || 0, // default to 0 if missing
  }));
};
