import axios from 'axios'

const api = axios.create({
  baseURL: import.meta.env.VITE_API_URL || 'http://localhost:8000'
})

const TOMTOM_BASE_URL      = import.meta.env.VITE_TOMTOM_BASE_URL      || 'https://api.tomtom.com'
const TOMTOM_API_KEY       = import.meta.env.VITE_TOMTOM_API_KEY
const TOMTOM_TRAFFIC_STYLE = import.meta.env.VITE_TOMTOM_TRAFFIC_STYLE || 'relative'

// ── Bin / Anomali ────────────────────────────────────────────────────────────
export const getBins      = ()              => api.get('/api/bins')
export const getSummary   = ()              => api.get('/api/bins/summary')
export const getAnomalies = (limit = 50)   => api.get('/api/anomalies', { params: { limit } })

// ── TomTom ───────────────────────────────────────────────────────────────────
export const getTomTomTrafficTileUrl = () => {
  if (!TOMTOM_API_KEY) return ''
  return `${TOMTOM_BASE_URL}/traffic/map/4/tile/flow/${TOMTOM_TRAFFIC_STYLE}/{z}/{x}/{y}.png?key=${TOMTOM_API_KEY}`
}

// ── Canlı Simülasyon ─────────────────────────────────────────────────────────
export const startSim       = ()                   => api.post('/api/simulation/start')
export const stopSim        = ()                   => api.post('/api/simulation/stop')
export const resetSim       = ()                   => api.post('/api/simulation/reset')
export const setSimSpeed    = (multiplier)         => api.patch('/api/simulation/speed', { multiplier })
export const setFixedAlgorithm = (algorithm)       => api.patch('/api/simulation/fixed-algorithm', { algorithm })
export const getLiveState   = ()                   => api.get('/api/simulation/live-state')
export const getLiveKPIs    = ()                   => api.get('/api/simulation/live-kpis')
export const getSimAnomalies = ()                  => api.get('/api/simulation/anomalies')

export default api
