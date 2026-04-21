import { useMemo } from 'react'
import L from 'leaflet'
import { MapContainer, Marker, Popup, TileLayer } from 'react-leaflet'
import MarkerClusterGroup from 'react-leaflet-cluster'
import BinPopup from './BinPopup'

const DUBLIN_CENTER = [53.3498, -6.2603]

function MapView({ bins }) {
  const iconsByStatus = useMemo(
    () => ({
      OFFLINE: L.divIcon({
        className: 'bin-marker-gray',
        html: '<span></span>',
        iconSize: [12, 12],
        iconAnchor: [6, 6]
      }),
      EMPTY: L.divIcon({
        className: 'bin-marker-empty',
        html: '<span></span>',
        iconSize: [12, 12],
        iconAnchor: [6, 6]
      }),
      FULL: L.divIcon({
        className: 'bin-marker-full',
        html: '<span></span>',
        iconSize: [12, 12],
        iconAnchor: [6, 6]
      }),
      CRITICAL_FULL: L.divIcon({
        className: 'bin-marker-critical',
        html: '<span></span>',
        iconSize: [12, 12],
        iconAnchor: [6, 6]
      })
    }),
    []
  )

  const getIconForBin = (bin) => {
    const status = bin.status || 'OFFLINE'
    return iconsByStatus[status] || iconsByStatus.OFFLINE
  }

  return (
    <MapContainer center={DUBLIN_CENTER} zoom={12} style={{ height: '100%', width: '100%' }}>
      <TileLayer
        attribution="&copy; OpenStreetMap contributors"
        url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
      />
      <MarkerClusterGroup chunkedLoading>
        {bins.map((bin) => (
          <Marker
            key={bin.bin_id}
            position={[bin.lat, bin.lon]}
            icon={getIconForBin(bin)}
            eventHandlers={{
              mouseover: (event) => event.target.openPopup(),
              mouseout: (event) => event.target.closePopup()
            }}
          >
            <Popup>
              <BinPopup bin={bin} />
            </Popup>
          </Marker>
        ))}
      </MarkerClusterGroup>
    </MapContainer>
  )
}

export default MapView
