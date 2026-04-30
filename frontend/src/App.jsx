import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { fetchRoutePreview, getBins, getSummary, getTomTomTrafficTileUrl } from './services/api'
import MapView from './components/MapView'

const DUBLIN_DEPOT = { lat: 53.3498, lon: -6.2603 }
const TRAFFIC_TILE_URL = getTomTomTrafficTileUrl()

function App() {
  const [bins, setBins] = useState([])
  const [summary, setSummary] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [showTraffic, setShowTraffic] = useState(false)
  const [trafficRefreshToken, setTrafficRefreshToken] = useState(0)
  const [routeSegments, setRouteSegments] = useState([])
  const [routeInfo, setRouteInfo] = useState(null)
  const [routeLoading, setRouteLoading] = useState(false)
  const [routeError, setRouteError] = useState('')
  const navigate = useNavigate()

  useEffect(() => {
    const load = async () => {
      try {
        setLoading(true)
        const [binsResponse, summaryResponse] = await Promise.all([getBins(), getSummary()])
        setBins(binsResponse.data)
        setSummary(summaryResponse.data)
      } catch {
        setError('Veri yüklenemedi. Backend bağlantısını kontrol et.')
      } finally {
        setLoading(false)
      }
    }
    load()
  }, [])

  const mapCenter = useMemo(() => {
    if (bins.length > 0) return [bins[0].lat, bins[0].lon]
    return null
  }, [bins])

  const handleToggleTraffic = () => {
    setShowTraffic((prev) => !prev)
    setTrafficRefreshToken((prev) => prev + 1)
  }

  const handlePlanRoute = async () => {
    const priorityBins = bins.filter((b) => b.status === 'CRITICAL_FULL' || b.status === 'FULL')
    if (priorityBins.length === 0) {
      setRouteError('Haritada FULL veya CRITICAL_FULL bin bulunamadı.')
      return
    }

    setRouteLoading(true)
    setRouteError('')
    setRouteSegments([])
    setRouteInfo(null)

    try {
      // ORS max 50 waypoints (start + 49)
      const waypoints = priorityBins.slice(0, 49).map((b) => ({ lat: b.lat, lon: b.lon }))
      const result = await fetchRoutePreview({ start: DUBLIN_DEPOT, waypoints })

      // GeoJSON coordinates are [lon, lat]; Leaflet needs [lat, lon]
      const coords = result.geometry.coordinates.map(([lon, lat]) => [lat, lon])

      setRouteSegments([{ id: 'collection-route', coordinates: coords, color: '#2563eb' }])
      setRouteInfo({
        stops: priorityBins.length,
        distance_km: (result.distance_m / 1000).toFixed(1),
        duration_min: Math.round(result.duration_s / 60)
      })
    } catch (err) {
      const msg =
        err.message === 'ORS_API_KEY_MISSING'
          ? 'ORS API anahtarı eksik (.env kontrol edin).'
          : 'Rota hesaplanamadı. ORS servisini kontrol edin.'
      setRouteError(msg)
    } finally {
      setRouteLoading(false)
    }
  }

  const handleClearRoute = () => {
    setRouteSegments([])
    setRouteInfo(null)
    setRouteError('')
  }

  return (
    <div className="app">
      <header className="header">
        <div className="header-left">
          <h1>EcoHaul - Atık Yönetim Sistemi</h1>
          <p>
            Toplam Kutu: {summary?.total_bins ?? '-'} | Offline: {summary?.offline_bins ?? '-'}
          </p>
        </div>
        <div className="header-actions">
          <button
            type="button"
            className={`toggle-button${showTraffic ? ' active' : ''}`}
            onClick={handleToggleTraffic}
          >
            {showTraffic ? 'Trafik Kapat' : 'Trafik Göster'}
          </button>
          <button
            type="button"
            className="route-button"
            onClick={routeSegments.length > 0 ? handleClearRoute : handlePlanRoute}
            disabled={routeLoading}
          >
            {routeLoading
              ? 'Hesaplanıyor...'
              : routeSegments.length > 0
                ? 'Rotayı Temizle'
                : 'Rota Planla'}
          </button>
          <button
            type="button"
            className="anomaly-button"
            onClick={() => navigate('/anomalies')}
          >
            Anomali Geçmişini Göster
          </button>
        </div>
      </header>

      <section className="map-wrapper">
        {loading && <div className="loading">Harita verileri yükleniyor...</div>}
        {error && <div className="error">{error}</div>}
        {!loading && !error && (
          <MapView
            bins={bins}
            mapCenter={mapCenter}
            routeSegments={routeSegments}
            showTraffic={showTraffic}
            trafficRefreshToken={trafficRefreshToken}
            trafficTileUrl={TRAFFIC_TILE_URL}
          />
        )}

        {showTraffic && (
          <div className="traffic-legend-panel">
            <div className="traffic-legend-title">Trafik Yoğunluğu</div>
            <div className="traffic-legend-updated">TomTom Gerçek Zamanlı</div>
            <div className="traffic-legend-items">
              <div>
                <span className="legend-dot low" />
                Serbest akış
              </div>
              <div>
                <span className="legend-dot medium" />
                Orta yoğunluk
              </div>
              <div>
                <span className="legend-dot high" />
                Yüksek yoğunluk
              </div>
              <div>
                <span className="legend-dot severe" />
                Durma noktası
              </div>
            </div>
            {routeSegments.length > 0 && (
              <div className="traffic-legend-items route">
                <div>
                  <span className="legend-dot route-free" />
                  Planlanan Rota
                </div>
              </div>
            )}
          </div>
        )}

        {routeInfo && (
          <div className="eta-panel">
            <div className="eta-title">Rota Özeti</div>
            <div className="eta-grid">
              <span>Durak</span>
              <span>
                <strong>{routeInfo.stops}</strong>
              </span>
              <span>Mesafe</span>
              <span>
                <strong>{routeInfo.distance_km} km</strong>
              </span>
              <span>Tahmini Süre</span>
              <span>
                <strong>{routeInfo.duration_min} dk</strong>
              </span>
            </div>
          </div>
        )}

        {routeError && <div className="status-message">{routeError}</div>}
      </section>
    </div>
  )
}

export default App
