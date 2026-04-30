import axios from 'axios'

const api = axios.create({
  baseURL: import.meta.env.VITE_API_URL || 'http://localhost:8000'
})

const ORS_BASE_URL = import.meta.env.VITE_ORS_BASE_URL || 'https://api.openrouteservice.org'
const ORS_API_KEY = import.meta.env.VITE_ORS_API_KEY
const TOMTOM_BASE_URL = import.meta.env.VITE_TOMTOM_BASE_URL || 'https://api.tomtom.com'
const TOMTOM_API_KEY = import.meta.env.VITE_TOMTOM_API_KEY
const TOMTOM_TRAFFIC_STYLE = import.meta.env.VITE_TOMTOM_TRAFFIC_STYLE || 'relative'

export const getBins = () => api.get('/api/bins')
export const getSummary = () => api.get('/api/bins/summary')
export const getAnomalies = (limit = 50) => api.get('/api/anomalies', { params: { limit } })

export const fetchRoutePreview = async ({ start, waypoints, profile = 'driving-car' }) => {
  if (!ORS_API_KEY) {
    throw new Error('ORS_API_KEY_MISSING')
  }

  const coordinates = [start, ...waypoints].map((point) => [point.lon, point.lat])
  const url = `${ORS_BASE_URL}/v2/directions/${profile}/geojson`

  const response = await axios.post(
    url,
    { coordinates },
    {
      headers: {
        Authorization: ORS_API_KEY,
        'Content-Type': 'application/json'
      }
    }
  )

  const feature = response.data?.features?.[0]
  if (!feature) {
    throw new Error('ORS_ROUTE_NOT_FOUND')
  }

  const summary = feature.properties?.summary || {}
  return {
    distance_m: summary.distance ?? 0,
    duration_s: summary.duration ?? 0,
    geometry: feature.geometry,
    route_provider: 'openrouteservice'
  }
}

export const fetchTomTomTrafficFlow = async ({ lat, lon }) => {
  if (!TOMTOM_API_KEY) {
    throw new Error('TOMTOM_API_KEY_MISSING')
  }

  const response = await axios.get(`${TOMTOM_BASE_URL}/traffic/services/4/flowSegmentData/absolute/10/json`, {
    params: {
      point: `${lat},${lon}`,
      key: TOMTOM_API_KEY
    }
  })

  return response.data?.flowSegmentData
}

export const getTomTomTrafficTileUrl = () => {
  if (!TOMTOM_API_KEY) {
    return ''
  }

  return `${TOMTOM_BASE_URL}/traffic/map/4/tile/flow/${TOMTOM_TRAFFIC_STYLE}/{z}/{x}/{y}.png?key=${TOMTOM_API_KEY}`
}

export default api
