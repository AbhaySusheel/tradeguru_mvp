import axios from "axios";

export const API_BASE = "https://tradeguru-mvp.onrender.com/api";
export const API_KEY = "8f912050f8a403046ea774190bf4fa33";

const api = axios.create({
  baseURL: API_BASE,
  headers: {
    "x-api-key": API_KEY,
    "Content-Type": "application/json",
  },
});

// 🔍 Debug log: print header before each request
api.interceptors.request.use((config) => {
  console.log("🛰️ Sending request:", config.url, "Header:", config.headers["x-api-key"]);
  return config;
});

export default api;
