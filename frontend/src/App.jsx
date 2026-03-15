import { useEffect, useState } from 'react'
import { getBins, getSummary } from './services/api'
import MapView from './components/MapView'

function App() {
  const [bins, setBins] = useState([])
  const [summary, setSummary] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    const load = async () => {
      try {
        setLoading(true)
        const [binsResponse, summaryResponse] = await Promise.all([getBins(), getSummary()])
        setBins(binsResponse.data)
        setSummary(summaryResponse.data)
      } catch (requestError) {
        setError('Veri yüklenemedi. Backend bağlantısını kontrol et.')
      } finally {
        setLoading(false)
      }
    }

    load()
  }, [])

  return (
    <div className="app">
      <header className="header">
        <h1>EcoHaul - Hafta 1 MVP</h1>
        <p>
          Toplam Kutu: {summary?.total_bins ?? '-'} | Offline: {summary?.offline_bins ?? '-'}
        </p>
      </header>
      <section className="map-wrapper">
        {loading && <div className="loading">Harita verileri yükleniyor...</div>}
        {error && <div className="error">{error}</div>}
        {!loading && !error && <MapView bins={bins} />}
      </section>
    </div>
  )
}

export default App
