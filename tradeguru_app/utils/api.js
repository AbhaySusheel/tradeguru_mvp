import axios from "axios";

const API_BASE = "https://tradeguru-mvp.onrender.com";
const API_KEY = "8f912050f8a403046ea774190bf4fa33";

const client = axios.create({
  baseURL: API_BASE,
  timeout: 60000,
  headers: {
    "Content-Type": "application/json",
    "x-api-key": API_KEY,
    "User-Agent": "TradeGuruApp/1.0",
  },
});

export default {
  getTopPicks: (limit = 10) =>
    client.get(`/api/top-picks?limit=${limit}`).then((r) => r.data),
  getPositions: () =>
    client.get("/api/positions").then((r) => r.data),
  openPosition: (payload) =>
    client.post("/api/positions", payload).then((r) => r.data),
  closePosition: (payload) =>
    client.post("/api/positions/close", payload).then((r) => r.data),

  // New function to register Expo push token
  registerPushToken: (token) =>
    client.post("/api/registerPushToken", { token }).then((r) => r.data),
};
