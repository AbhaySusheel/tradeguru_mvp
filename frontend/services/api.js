import axios from 'axios';
// Replace <RENDER_URL> with your deployed backend URL (no trailing slash)
const API = axios.create({ baseURL: 'http://10.0.2.2:8000/api' });
export const getSignals = () => API.get('/signals/today').then(r => r.data);
