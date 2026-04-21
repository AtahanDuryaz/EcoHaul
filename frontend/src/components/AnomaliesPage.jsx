import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { getAnomalies } from '../services/api'

function AnomaliesPage() {
  const [anomalies, setAnomalies] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [binFilter, setBinFilter] = useState('')
  const [startDate, setStartDate] = useState('')
  const [endDate, setEndDate] = useState('')

  useEffect(() => {
    const load = async () => {
      try {
        setLoading(true)
        const response = await getAnomalies()
        setAnomalies(response.data)
      } catch (requestError) {
        setError('Anomali verileri alınamadı. Backend bağlantısını kontrol et.')
      } finally {
        setLoading(false)
      }
    }

    load()
  }, [])

  const filteredAnomalies = useMemo(() => {
    return anomalies.filter((event) => {
      if (binFilter && !event.bin_id.toLowerCase().includes(binFilter.toLowerCase())) {
        return false
      }

      const eventDate = new Date(event.created_at)

      if (startDate) {
        const start = new Date(startDate)
        if (eventDate < start) {
          return false
        }
      }

      if (endDate) {
        const end = new Date(endDate)
        end.setDate(end.getDate() + 1)
        if (eventDate >= end) {
          return false
        }
      }

      return true
    })
  }, [anomalies, binFilter, startDate, endDate])

  return (
    <div className="app">
      <header className="header">
        <div className="header-left">
          <h1>EcoHaul - Anomali Logları</h1>
          <p>
            Toplam Anomali: {anomalies.length} | Filtrelenen: {filteredAnomalies.length}
          </p>
        </div>
        <Link to="/" className="anomaly-button">
          Haritaya Dön
        </Link>
      </header>

      <section className="anomalies-page">
        <div className="anomalies-filters">
          <div className="filter-group">
            <label htmlFor="binFilter">Bin ID ile filtrele</label>
            <input
              id="binFilter"
              type="text"
              placeholder="Örn: WMS1873"
              value={binFilter}
              onChange={(event) => setBinFilter(event.target.value)}
            />
          </div>

          <div className="filter-group">
            <label htmlFor="startDate">Başlangıç Tarihi</label>
            <input
              id="startDate"
              type="date"
              value={startDate}
              onChange={(event) => setStartDate(event.target.value)}
            />
          </div>

          <div className="filter-group">
            <label htmlFor="endDate">Bitiş Tarihi</label>
            <input
              id="endDate"
              type="date"
              value={endDate}
              onChange={(event) => setEndDate(event.target.value)}
            />
          </div>
        </div>

        {loading && <div className="loading">Anomali verileri yükleniyor...</div>}
        {error && <div className="error">{error}</div>}

        {!loading && !error && (
          <div className="anomalies-table-wrapper">
            {filteredAnomalies.length === 0 ? (
              <div className="empty-state">Filtrelere uyan anomali bulunamadı.</div>
            ) : (
              <table className="anomalies-table">
                <thead>
                  <tr>
                    <th>Timestamp</th>
                    <th>Bin ID</th>
                    <th>Event Type</th>
                    <th>Details</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredAnomalies.map((event, index) => (
                    <tr key={`${event.bin_id}-${event.created_at}-${index}`}>
                      <td>{new Date(event.created_at).toLocaleString()}</td>
                      <td>{event.bin_id}</td>
                      <td>{event.event_type}</td>
                      <td>{event.details}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        )}
      </section>
    </div>
  )
}

export default AnomaliesPage
