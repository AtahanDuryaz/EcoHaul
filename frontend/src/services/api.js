import axios from 'axios'

const api = axios.create({
  baseURL: import.meta.env.VITE_API_URL || 'http://localhost:8000'
})

export const getBins = () => api.get('/api/bins')
export const getSummary = () => api.get('/api/bins/summary')
export const getAnomalies = () => api.get('/api/anomalies')

export default api
