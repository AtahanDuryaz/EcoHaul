import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter, Routes, Route } from 'react-router-dom'
import 'leaflet/dist/leaflet.css'
import 'react-leaflet-cluster/dist/assets/MarkerCluster.css'
import 'react-leaflet-cluster/dist/assets/MarkerCluster.Default.css'
import './App.css'
import SimulationPage from './components/SimulationPage'
import AnomaliesPage from './components/AnomaliesPage'

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <BrowserRouter>
      <Routes>
        <Route path="/"          element={<SimulationPage />} />
        <Route path="/anomalies" element={<AnomaliesPage />} />
      </Routes>
    </BrowserRouter>
  </React.StrictMode>
)
