import { useCallback, useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import L from 'leaflet'
import {
  MapContainer,
  Marker,
  Polyline,
  Popup,
  TileLayer,
} from 'react-leaflet'
import MarkerClusterGroup from 'react-leaflet-cluster'
import {
  getLiveKPIs,
  getLiveState,
  getSimAnomalies,
  resetSim,
  setSimSpeed,
  startSim,
  stopSim,
  getTomTomTrafficTileUrl,
} from '../services/api'

// ── Sabitler ─────────────────────────────────────────────────────────────────

const DUBLIN_CENTER = [53.3498, -6.2603]
const TRAFFIC_URL   = getTomTomTrafficTileUrl()

const SPEED_OPTIONS = [
  { label: '1x',     multiplier: 1     },
  { label: '60x',    multiplier: 60    },
  { label: '3600x',  multiplier: 3600  },
  { label: '86400x', multiplier: 86400 },
]
const DEFAULT_SPEED_IDX = 2   // 3600x

const POLL_STATE_MS    = 1_000
const POLL_KPIS_MS     = 2_000
const POLL_ANOMALY_MS  = 3_000

const fmtCost = (n) => (n >= 1000 ? `₺${(n / 1000).toFixed(1)}k` : `₺${Math.round(n)}`)
const fmtDt = (iso) => {
  if (!iso) return '—'
  try {
    return new Date(iso).toLocaleString('tr-TR', {
      day: '2-digit', month: 'short', year: 'numeric',
      hour: '2-digit', minute: '2-digit',
    })
  } catch { return iso }
}

// ── Bin icon — fill_pct'e göre renk ─────────────────────────────────────────

function fillColor(status, fillPct) {
  if (status === 'OFFLINE')       return '#6b7280'
  if (status === 'SENSOR_ERROR')  return '#a855f7'
  if (status === 'CRITICAL_FULL') return '#ef4444'
  if (status === 'FULL')          return '#f97316'
  if (fillPct >= 30)              return '#eab308'
  return '#22c55e'
}

function makeBinIcon(status, fillPct) {
  const color = fillColor(status, fillPct)
  const pct   = Math.round(fillPct)
  return L.divIcon({
    className: '',
    html: `<div style="position:relative;width:16px;height:16px">
      <span style="display:block;width:16px;height:16px;border-radius:50%;
        background:${color};border:1.5px solid rgba(0,0,0,0.3)"></span>
      ${pct > 0 ? `<span style="position:absolute;top:-6px;left:50%;transform:translateX(-50%);
        font-size:8px;color:#fff;font-weight:700;text-shadow:0 0 2px #000;white-space:nowrap">${pct}%</span>` : ''}
    </div>`,
    iconSize: [16, 16],
    iconAnchor: [8, 8],
  })
}

const DEPOT_ICON = L.divIcon({
  className: '',
  html: `<div style="
    width:20px;height:20px;border-radius:50%;
    background:#c026d3;
    border:3px solid #e879f9;
    box-shadow:0 0 14px #c026d3, 0 0 28px rgba(192,38,211,0.5);
  "></div>`,
  iconSize: [20, 20],
  iconAnchor: [10, 10],
})

function makeTruckIcon(routeType, status) {
  const color  = routeType === 'algo' ? '#22c55e' : '#f59e0b'
  const border = routeType === 'algo' ? '#166534' : '#92400e'
  const emoji  = status === 'servicing' ? '🗑' : '🚛'
  return L.divIcon({
    className: '',
    html: `<div style="background:${color};border:2px solid ${border};border-radius:4px;
      padding:2px 4px;font-size:14px;line-height:1;box-shadow:0 2px 6px rgba(0,0,0,0.4)">${emoji}</div>`,
    iconSize: [28, 24],
    iconAnchor: [14, 12],
  })
}

// ── TrafficLayer ──────────────────────────────────────────────────────────────

function TrafficLayer({ url, token }) {
  return <TileLayer key={`traffic-${token}`} url={url} opacity={0.8} zIndex={5} />
}

// ── SimMap ────────────────────────────────────────────────────────────────────

function SimMap({ bins, trucks, showTraffic, trafficToken, depotLat, depotLon, accent }) {
  const accentColor = accent === 'algo' ? '#22c55e' : '#f59e0b'

  return (
    <MapContainer center={DUBLIN_CENTER} zoom={12} style={{ height: '100%', width: '100%' }}>
      <TileLayer
        attribution="&copy; OpenStreetMap contributors"
        url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
      />
      {showTraffic && TRAFFIC_URL && (
        <TrafficLayer url={TRAFFIC_URL} token={trafficToken} />
      )}

      {/* Tam rota çizgisi — saydam (tüm rota planı) */}
      {trucks.map((truck) =>
        truck.full_latlons && truck.full_latlons.length > 1 ? (
          <Polyline
            key={`full-route-${truck.truck_id}`}
            positions={truck.full_latlons}
            pathOptions={{ color: accentColor, weight: 1.5, opacity: 0.25, dashArray: '4 6' }}
          />
        ) : null
      )}

      {/* Kalan rota çizgisi — parlak (kamyonun önündeki yol) */}
      {trucks.map((truck) =>
        truck.route_ahead && truck.route_ahead.length > 1 ? (
          <Polyline
            key={`ahead-${truck.truck_id}`}
            positions={truck.route_ahead}
            pathOptions={{ color: accentColor, weight: 2.5, opacity: 0.75, dashArray: '8 4' }}
          />
        ) : null
      )}

      {/* Bin marker'ları */}
      <MarkerClusterGroup chunkedLoading>
        {bins.map((bin) => (
          <Marker
            key={bin.bin_id}
            position={[bin.lat, bin.lon]}
            icon={makeBinIcon(bin.status, bin.fill_pct)}
          >
            <Popup>
              <div style={{ fontSize: 12, minWidth: 180 }}>
                <strong>{bin.bin_id}</strong>
                <div>Dolum: <strong style={{ color: fillColor(bin.status, bin.fill_pct) }}>{Math.round(bin.fill_pct)}%</strong></div>
                <div>Durum: {bin.status}</div>
                <div>Etiket: Hız <strong>{bin.fill_label}</strong> · Mesafe <strong>{bin.distance_label}</strong></div>
                <div>Bölge: {bin.region}</div>
                <div style={{ marginTop: 4, borderTop: '1px solid #e2e8f0', paddingTop: 4 }}>
                  <div>
                    <span style={{ color: '#64748b' }}>Tahmini Dolum: </span>
                    <strong style={{ color: bin.fill_pct >= 100 ? '#ef4444' : '#f97316' }}>
                      {bin.fill_pct >= 100
                        ? 'DOLU'
                        : bin.estimated_full_iso
                          ? fmtDt(bin.estimated_full_iso)
                          : '—'}
                    </strong>
                  </div>
                  <div>
                    <span style={{ color: '#64748b' }}>Son Boşaltım: </span>
                    <strong style={{ color: '#22c55e' }}>
                      {bin.last_emptied_iso ? fmtDt(bin.last_emptied_iso) : 'Henüz boşaltılmadı'}
                    </strong>
                  </div>
                </div>
              </div>
            </Popup>
          </Marker>
        ))}
      </MarkerClusterGroup>

      {/* Depot marker — parlak mor */}
      {depotLat && depotLon && (
        <Marker position={[depotLat, depotLon]} icon={DEPOT_ICON} zIndexOffset={2000}>
          <Popup>
            <div style={{ fontSize: 12 }}>
              <strong>Depo Merkezi</strong>
              <div style={{ color: '#9333ea' }}>Kamyonlar buradan başlar ve döner</div>
              <div style={{ fontSize: 11, color: '#64748b' }}>{depotLat.toFixed(4)}, {depotLon.toFixed(4)}</div>
            </div>
          </Popup>
        </Marker>
      )}

      {/* Kamyon marker'ları */}
      {trucks.map((truck, i) => (
        <Marker
          key={`truck-${truck.truck_id}-${i}`}
          position={[truck.lat, truck.lon]}
          icon={makeTruckIcon(truck.route_type, truck.status)}
          zIndexOffset={1000}
        >
          <Popup>
            <div style={{ fontSize: 12 }}>
              <strong>Kamyon #{truck.truck_id}</strong>
              <div>
                {truck.status === 'servicing' ? `Servis: ${truck.at_bin}`  :
                 truck.status === 'returning'  ? 'Depoya dönüyor'           :
                 truck.status === 'en_route'   ? `→ ${truck.to_bin}`        : truck.status}
              </div>
              <div>İlerleme: {Math.round((truck.progress || 0) * 100)}%</div>
              <div>Duraklar: {truck.current_stop_idx + 1}/{truck.stops_total}</div>
            </div>
          </Popup>
        </Marker>
      ))}
    </MapContainer>
  )
}

// ── KPIChip ───────────────────────────────────────────────────────────────────

function KPIChip({ label, value, unit, accent }) {
  return (
    <div className={`opc-chip opc-chip-${accent}`}>
      <div className={`opc-chip-val opc-val-${accent}`}>
        {value}{unit && <span className="opc-chip-unit">{unit}</span>}
      </div>
      <div className="opc-chip-label">{label}</div>
    </div>
  )
}

function EffChip({ rate, loadPerKm, overflowHours, accent }) {
  const display  = rate !== null ? `${rate}%` : '—'
  const fmtK     = (n) => n >= 1000 ? `${(n / 1000).toFixed(1)}k` : String(n)
  const sub1     = loadPerKm    !== null ? `${loadPerKm} yk/km` : ''
  const sub2     = overflowHours !== null ? `${fmtK(overflowHours)} bin·s taşma` : ''
  return (
    <div className={`opc-chip opc-chip-${accent} opc-chip-eff`}>
      <div className="opc-eff-top">
        <span className={`opc-chip-val opc-val-${accent}`}>{display}</span>
        {sub1 && <span className="opc-chip-sub">{sub1}</span>}
      </div>
      {sub2 && <div className="opc-chip-sub opc-chip-sub-overflow">{sub2}</div>}
      <div className="opc-eff-track">
        <div className={`opc-eff-fill opc-eff-${accent}`} style={{ width: `${rate ?? 0}%` }} />
      </div>
      <div className="opc-chip-label">Sistem Skoru</div>
    </div>
  )
}

function TruckDots({ count, accent }) {
  return (
    <div className="opc-truck-bar">
      <div className="opc-truck-dots">
        {count
          ? Array.from({ length: Math.min(count, 8) }).map((_, i) => (
              <span key={i} className={`opc-truck-dot opc-dot-${accent}`} />
            ))
          : <span className="opc-truck-empty">—</span>
        }
      </div>
      <span className="opc-truck-label">
        {count ? `${count} Kamyon Aktif` : 'Bekleniyor'}
      </span>
    </div>
  )
}

// ── ColPanel ──────────────────────────────────────────────────────────────────

function ColPanel({ title, accent, kpis, trucks, bins, showTraffic, trafficToken, depotLat, depotLon }) {
  // ── Verimlilik: load/km (yük verimliliği) — taşma AYRI gösterilir ────────
  // Verimlilik ve taşma farklı boyutlar; birini diğerine kurban etmek
  // akademik olarak yanlış. Taşma sub-label'da kırmızı görünür, skoru etkilemez.
  // Referans: 80 yk/km → %100 (ortalama %80 dolu 1 bin/km)
  const loadPerKm     = kpis && kpis.distance_km > 0
    ? Math.round((kpis.load_collected / kpis.distance_km) * 10) / 10
    : null
  const overflowHours = kpis ? kpis.overflow_events : null   // bin-saat (informational)
  const effRate       = loadPerKm !== null
    ? Math.min(100, Math.round(loadPerKm / 0.8))
    : kpis ? 0 : null

  const validBins = bins.filter((b) => b.lat && b.lon)

  return (
    <div className={`opc-col opc-col-${accent}`}>
      <div className={`opc-col-head opc-head-${accent}`}>
        <span className={`opc-col-badge opc-badge-${accent}`}>{title}</span>
      </div>

      <div className="opc-chips-row">
        <KPIChip label="CO₂ Emisyonu"    value={kpis ? kpis.co2_kg             : '—'} unit={kpis ? ' kg' : ''} accent={accent} />
        <KPIChip label="Yakıt Sarfiyatı" value={kpis ? kpis.fuel_l             : '—'} unit={kpis ? ' L'  : ''} accent={accent} />
        <KPIChip label="Op. Maliyet"     value={kpis ? fmtCost(kpis.cost_tl)   : '—'} unit=""                   accent={accent} />
        <EffChip rate={effRate} loadPerKm={loadPerKm} overflowHours={overflowHours} accent={accent} />
      </div>

      <TruckDots count={trucks.length} accent={accent} />

      <div className="opc-map-area">
        <SimMap
          bins={validBins}
          trucks={trucks}
          showTraffic={showTraffic}
          trafficToken={trafficToken}
          depotLat={depotLat}
          depotLon={depotLon}
          accent={accent}
        />
        {kpis && (
          <div className={`opc-map-pill opc-pill-${accent}`}>
            <span>{kpis.dispatch_count} Sefer</span>
            <span className="opc-pill-dot">·</span>
            <span>{kpis.distance_km} km</span>
            <span className="opc-pill-dot">·</span>
            <span style={{ color: '#ef4444' }}>{kpis.overflow_count ?? kpis.overflow_events} Taşma</span>
          </div>
        )}
      </div>
    </div>
  )
}

// ── SavingsStrip ──────────────────────────────────────────────────────────────

function SavingsStrip({ savings }) {
  if (!savings) return null
  const items = [
    { label: 'CO₂ Tasarrufu',     val: `${savings.co2_kg} kg`      },
    { label: 'Yakıt Tasarrufu',   val: `${savings.fuel_l} L`       },
    { label: 'Maliyet Tasarrufu', val: fmtCost(savings.cost_tl)    },
    { label: 'Taşma Azalması',    val: `${savings.overflow_diff} olay` },
  ]
  return (
    <div className="opc-savings-strip">
      <span className="opc-savings-label">ALGORİTMA TASARRUFU</span>
      <div className="opc-savings-items">
        {items.map((it) => (
          <div key={it.label} className="opc-savings-item">
            <span className="opc-savings-val">{it.val}</span>
            <span className="opc-savings-sub">{it.label}</span>
          </div>
        ))}
      </div>
    </div>
  )
}

// ── AnomalyLog ────────────────────────────────────────────────────────────────

const ANOMALY_COLOR = {
  OVERFLOW_RISK:            '#ef4444',
  FILL_ANOMALY:             '#f97316',
  SENSOR_FIXED_VALUE_ERROR: '#a855f7',
  BIN_OFFLINE:              '#6b7280',
}

function AnomalyLog({ anomalies }) {
  return (
    <div className="opc-anomaly-log">
      <div className="opc-anomaly-title">Son Anomaliler</div>
      {anomalies.length === 0 && (
        <div className="opc-anomaly-empty">Henüz anomali yok</div>
      )}
      {anomalies.slice(0, 8).map((a, i) => (
        <div key={i} className="opc-anomaly-row">
          <span
            className="opc-anomaly-dot"
            style={{ background: ANOMALY_COLOR[a.event_type] || '#64748b' }}
          />
          <span className="opc-anomaly-bin">{a.bin_id}</span>
          <span className="opc-anomaly-type">{a.event_type}</span>
          <span className="opc-anomaly-time">{fmtDt(a.virtual_time)}</span>
        </div>
      ))}
    </div>
  )
}

// ── SimControls ───────────────────────────────────────────────────────────────

function SimControls({ isRunning, speedIdx, virtualClock, onStart, onStop, onReset, onSpeed }) {
  return (
    <div className="opc-sim-controls">
      <div className="opc-ctrl-left">
        <button
          className={`opc-ctrl-btn${isRunning ? ' active' : ''}`}
          onClick={isRunning ? onStop : onStart}
        >
          {isRunning ? '⏸ Durdur' : '▶ Başlat'}
        </button>
        <button className="opc-ctrl-btn opc-ctrl-reset" onClick={onReset}>
          ↺ Sıfırla
        </button>
        <div className="opc-speed-btns">
          {SPEED_OPTIONS.map((opt, i) => (
            <button
              key={opt.label}
              className={`opc-speed-btn${i === speedIdx ? ' active' : ''}`}
              onClick={() => onSpeed(i)}
            >
              {opt.label}
            </button>
          ))}
        </div>
      </div>
      <div className="opc-ctrl-clock">
        <span className="opc-clock-label">Simülasyon Saati</span>
        <span className="opc-clock-val">{fmtDt(virtualClock)}</span>
      </div>
    </div>
  )
}

// ── Ana Bileşen ───────────────────────────────────────────────────────────────

export default function SimulationPage() {
  const navigate = useNavigate()

  const [isRunning, setIsRunning]   = useState(false)
  const [speedIdx, setSpeedIdx]     = useState(DEFAULT_SPEED_IDX)
  const [virtualClock, setVirtualClock] = useState(null)

  const [depotLat, setDepotLat] = useState(null)
  const [depotLon, setDepotLon] = useState(null)

  const [algoBins, setAlgoBins]       = useState([])
  const [fixedBins, setFixedBins]     = useState([])
  const [algoTrucks, setAlgoTrucks]   = useState([])
  const [fixedTrucks, setFixedTrucks] = useState([])

  const [algoKPIs, setAlgoKPIs]   = useState(null)
  const [fixedKPIs, setFixedKPIs] = useState(null)
  const [savings, setSavings]     = useState(null)

  const [anomalies, setAnomalies] = useState([])

  const [showTraffic, setShowTraffic]   = useState(false)
  const [trafficToken, setTrafficToken] = useState(0)

  // Polling intervalları
  const stateTimer   = useRef(null)
  const kpiTimer     = useRef(null)
  const anomalyTimer = useRef(null)

  // ── Polling ───────────────────────────────────────────────────────────

  const pollState = useCallback(async () => {
    try {
      const { data } = await getLiveState()
      setAlgoBins(data.algo_bins   || [])
      setFixedBins(data.fixed_bins  || [])
      setAlgoTrucks(data.algo_trucks  || [])
      setFixedTrucks(data.fixed_trucks || [])
      setVirtualClock(data.virtual_clock)
      setIsRunning(data.is_running)
      if (data.depot_lat) setDepotLat(data.depot_lat)
      if (data.depot_lon) setDepotLon(data.depot_lon)
    } catch { /* bağlantı hatası sessizce geçilir */ }
  }, [])

  const pollKPIs = useCallback(async () => {
    try {
      const { data } = await getLiveKPIs()
      setAlgoKPIs(data.algo)
      setFixedKPIs(data.fixed)
      setSavings(data.savings)
    } catch {}
  }, [])

  const pollAnomalies = useCallback(async () => {
    try {
      const { data } = await getSimAnomalies()
      setAnomalies(data || [])
    } catch {}
  }, [])

  useEffect(() => {
    pollState()
    pollKPIs()
    pollAnomalies()

    stateTimer.current   = setInterval(pollState,    POLL_STATE_MS)
    kpiTimer.current     = setInterval(pollKPIs,     POLL_KPIS_MS)
    anomalyTimer.current = setInterval(pollAnomalies, POLL_ANOMALY_MS)

    return () => {
      clearInterval(stateTimer.current)
      clearInterval(kpiTimer.current)
      clearInterval(anomalyTimer.current)
    }
  }, [pollState, pollKPIs, pollAnomalies])

  // ── Kontrol handler'ları ──────────────────────────────────────────────

  const handleStart = async () => {
    await startSim()
    setIsRunning(true)
  }

  const handleStop = async () => {
    await stopSim()
    setIsRunning(false)
  }

  const handleReset = async () => {
    await resetSim()
    setAlgoBins([])
    setFixedBins([])
    setAlgoTrucks([])
    setFixedTrucks([])
    setAlgoKPIs(null)
    setFixedKPIs(null)
    setSavings(null)
    setAnomalies([])
    setVirtualClock(null)
  }

  const handleSpeed = async (idx) => {
    setSpeedIdx(idx)
    await setSimSpeed(SPEED_OPTIONS[idx].multiplier)
  }

  const handleToggleTraffic = () => {
    setShowTraffic((p) => !p)
    setTrafficToken((p) => p + 1)
  }

  // ─────────────────────────────────────────────────────────────────────

  return (
    <div className="opc-page">
      {/* ── Header ── */}
      <div className="opc-header">
        <div className="opc-header-left">
          <span className={`opc-live-dot${isRunning ? ' opc-dot-on' : ''}`} />
          <span className="opc-header-title">EcoHaul — Operasyon Merkezi</span>
          {isRunning && <span className="opc-live-badge">CANLI</span>}
        </div>
        <div className="opc-header-actions">
          <button
            className={`opc-btn opc-btn-traffic${showTraffic ? ' on' : ''}`}
            onClick={handleToggleTraffic}
          >
            {showTraffic ? '● Trafik Aktif' : '○ Trafik Göster'}
          </button>
          <button className="opc-btn opc-btn-back" onClick={() => navigate('/anomalies')}>
            Anomali Geçmişi →
          </button>
        </div>
      </div>

      {/* ── Simülasyon Kontrolleri ── */}
      <SimControls
        isRunning={isRunning}
        speedIdx={speedIdx}
        virtualClock={virtualClock}
        onStart={handleStart}
        onStop={handleStop}
        onReset={handleReset}
        onSpeed={handleSpeed}
      />

      <SavingsStrip savings={savings} />

      {/* ── İki Dünya ── */}
      <div className="opc-body">
        <ColPanel
          title="ALGORİTMA KPI"
          accent="algo"
          kpis={algoKPIs}
          trucks={algoTrucks}
          bins={algoBins}
          showTraffic={showTraffic}
          trafficToken={trafficToken}
          depotLat={depotLat}
          depotLon={depotLon}
        />
        <div className="opc-divider" />
        <ColPanel
          title="SABİT ROTA"
          accent="fixed"
          kpis={fixedKPIs}
          trucks={fixedTrucks}
          bins={fixedBins}
          showTraffic={showTraffic}
          trafficToken={trafficToken}
          depotLat={depotLat}
          depotLon={depotLon}
        />
      </div>

      {/* ── Anomali Log ── */}
      <AnomalyLog anomalies={anomalies} />
    </div>
  )
}
