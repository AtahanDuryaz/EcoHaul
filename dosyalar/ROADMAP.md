# EcoHaul AI — Geliştirme Yol Haritası
## 10 Mart 2026 → 20 Mayıs 2026

**Proje:** CSE-492 Bitirme Projesi — Local-First Versiyon  
**Süre:** 71 gün · 10 hafta + 1 gün  
**Teknoloji:** FastAPI · PostgreSQL/PostGIS · React/Tailwind · Leaflet · scikit-learn · ESP32

---

## Genel Takvim Görünümü

```
MART 2026
Hf  Tarihler          Faz           Başlık
─── ─────────────     ──────────    ──────────────────────────────────
0   10-16 Mar         Faz 0         Ortam Kurulumu
1   17-23 Mar         Faz 1A        DB Şeması + Veri Yükleme
2   24-30 Mar         Faz 1B        API + Frontend Harita

NİSAN 2026
Hf  Tarihler          Faz           Başlık
─── ─────────────     ──────────    ──────────────────────────────────
3   31 Mar-6 Nis      Faz 2A        IoT Simülatörü + Anomali Motoru
4   7-13 Nis          Faz 2B        Heartbeat Manager + ESP32 Entegrasyonu
5   14-20 Nis         Faz 3A        Optimizasyon Motoru (Mass-Aware + Greedy)
6   21-27 Nis         Faz 3B        ORS Entegrasyonu + Kamyon Simülatörü

MAYIS 2026
Hf  Tarihler          Faz           Başlık
─── ─────────────     ──────────    ───────────────────────────────────────
7   28 Nis-4 May      Faz 4A        Random Forest Regressor + /predictions
8   5-11 May          Faz 4A/5      Prediction Entegrasyonu + Dashboard Hazırlık (300 kutu)
9   12-18 May         Faz 5         Dashboard + 30 Gün Simülasyon (300 kutu)
10  19-20 May         Buffer        E2E Checklist + Demo Provası
```

---

## Faz 0 — Ortam Kurulumu
### Hafta 0 · 10–16 Mart (7 gün)

**Hedef:** Tek komutla ayağa kalkacak, hot-reload destekli geliştirme ortamı.

---

#### Gün 1–2 · 10–11 Mart · PostgreSQL + PostGIS

- [ ] PostgreSQL 14+ native kurulumu (Windows: EnterpriseDB installer)
- [ ] Stack Builder → PostGIS 3.x bundle kurulumu
- [ ] `psql -U postgres` → `CREATE DATABASE ecohaul;`
- [ ] `\c ecohaul` → `CREATE EXTENSION postgis;`
- [ ] Doğrulama: `SELECT PostGIS_Version();` → versiyon döner
- [ ] `ecohaul` için kullanıcı ve şifre oluştur, `.env` dosyasına yaz
- [ ] pgAdmin 4 kurulumu (opsiyonel ama görsel hata ayıklamada faydalı)

```
Beklenen çıktı:
  ecohaul=# SELECT PostGIS_Version();
   postgis_version
  ──────────────────────────────
   3.4 USE_GEOS=1 USE_PROJ=1 ...
```

---

#### Gün 2–3 · 11–12 Mart · Python Ortamı

- [ ] Python 3.10+ kurulu mu kontrol: `python --version`
- [ ] Proje kök klasörü oluştur: `eco_haul/`
- [ ] `python -m venv .venv` → `venv` aktif et
- [ ] `requirements.txt` hazırla ve yükle:
  ```
  fastapi==0.110.0
  uvicorn[standard]==0.27.0
  asyncpg==0.29.0
  pandas==2.2.0
  pyproj==3.6.1
  shapely==2.0.3
  scikit-learn==1.4.0
  httpx==0.27.0
  pytest==8.0.0
  pytest-asyncio==0.23.0
  pytest-mock==3.12.0
  python-dotenv==1.0.0
  ```
- [ ] `pip install -r requirements.txt` başarılı
- [ ] `python -c "import fastapi, asyncpg, pyproj, shapely; print('OK')"` → OK

---

#### Gün 3–4 · 12–13 Mart · Node.js + Frontend

- [ ] Node.js 20 LTS kurulumu (nodejs.org)
- [ ] `npm create vite@latest frontend -- --template react`
- [ ] Bağımlılıklar:
  ```bash
  cd frontend
  npm install
  npm install tailwindcss @tailwindcss/vite
  npm install react-leaflet leaflet
  npm install leaflet-moving-marker
  npm install axios
  npm install zustand
  ```
- [ ] `tailwind.config.js` oluştur, `index.css`'e `@tailwind` direktifleri ekle
- [ ] `npm run dev` → `localhost:5173` açılıyor

---

#### Gün 4–5 · 13–14 Mart · Proje Yapısı + .env

- [ ] Klasör yapısını oluştur (Docker dosyaları **yok**):
  ```
  eco_haul/
  ├── .env                 ← credentials (gitignore'da)
  ├── .env.example         ← takıma paylaşılan şablon
  ├── requirements.txt
  ├── .gitignore
  ├── data/
  │   └── dcc_public_bin_locations.csv
  ├── backend/
  │   ├── api/
  │   ├── database/
  │   ├── scripts/
  │   ├── services/
  │   └── ai/
  ├── frontend/src/
  │   ├── components/
  │   └── services/
  └── tests/
  ```
- [ ] `.env` dosyası:
  ```env
  DATABASE_URL=postgresql://postgres:sifre@localhost:5432/ecohaul
  ORS_BASE_URL=https://api.openrouteservice.org
  ORS_API_KEY=                  ← sonraki adımda doldurulacak
  BACKEND_HOST=localhost
  BACKEND_PORT=8000
  ```
- [ ] `.gitignore`: `.env`, `.venv/`, `__pycache__/`, `node_modules/`

---

#### Gün 5–6 · 14–15 Mart · ORS API Key + FastAPI Skeleton

- [ ] `openrouteservice.org` → ücretsiz hesap oluştur
- [ ] Dashboard → API Keys → yeni key oluştur
- [ ] Limitleri not et: 2.000 req/gün · 40 req/dk
- [ ] `.env`'e `ORS_API_KEY` yaz
- [ ] Hızlı test: `curl` ile Dublin koordinatlarına `GET /v2/directions/driving-car` → 200 OK
- [ ] `backend/api/main.py` skeleton:
  ```python
  from fastapi import FastAPI
  from fastapi.middleware.cors import CORSMiddleware
  app = FastAPI(title="EcoHaul AI")
  app.add_middleware(CORSMiddleware, allow_origins=["*"])

  @app.get("/health")
  async def health(): return {"status": "ok"}
  ```
- [ ] `uvicorn api.main:app --reload` → `localhost:8000/health` → `{"status":"ok"}`

---

#### Gün 7 · 16 Mart · Git + Ortam Doğrulama

- [ ] GitHub repo üzerinde `eco_haul/` commit'lendi
- [ ] `backend/` dizininde `uvicorn` çalışıyor
- [ ] `frontend/` dizininde `npm run dev` çalışıyor
- [ ] PostgreSQL bağlantısı `asyncpg.connect(DATABASE_URL)` başarılı
- [ ] PostGIS extension aktif

**✅ Faz 0 tamamlandı. Çalışan geliştirme ortamı hazır.**

---

## Faz 1A — Veritabanı Şeması + Veri Yükleme
### Hafta 1 · 17–23 Mart (7 gün)

**Hedef:** 300 adet seçili Dublin bin verisini PostGIS'e yükleyip SQL ile sorgulayabilmek.

---

#### Gün 1–2 · 17–18 Mart · `init.sql` — Tüm Tablolar

- [ ] `backend/database/init.sql` dosyası oluştur, 6 tablo tek seferde:

  ```sql
  -- Koordinat sistemi EPSG:4326 (WGS84)
  CREATE TABLE IF NOT EXISTS bins (
      bin_id     VARCHAR(20)  PRIMARY KEY,
      geom       GEOMETRY(Point, 4326) NOT NULL,
      region     VARCHAR(100),
      is_active  BOOLEAN      DEFAULT TRUE,
      fill_level VARCHAR(10)  DEFAULT 'LOW'
                 CHECK (fill_level IN ('LOW','MEDIUM','HIGH'))
  );
  CREATE INDEX IF NOT EXISTS idx_bins_geom   ON bins USING GIST(geom);
  CREATE INDEX IF NOT EXISTS idx_bins_region ON bins(region);
  CREATE INDEX IF NOT EXISTS idx_bins_fill   ON bins(fill_level);

  CREATE TABLE IF NOT EXISTS telemetry (
      id          SERIAL      PRIMARY KEY,
      bin_id      VARCHAR(20) NOT NULL,
      fill_level  VARCHAR(10) NOT NULL CHECK (fill_level IN ('LOW','MEDIUM','HIGH')),
      status      VARCHAR(10) NOT NULL DEFAULT 'OK'
                  CHECK (status IN ('OK','ANOMALY','OFFLINE')),
      recorded_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
  );
  CREATE INDEX IF NOT EXISTS idx_tel_bin     ON telemetry(bin_id);
  CREATE INDEX IF NOT EXISTS idx_tel_time    ON telemetry(recorded_at DESC);
  CREATE INDEX IF NOT EXISTS idx_tel_bin_t   ON telemetry(bin_id, recorded_at DESC);

  CREATE TABLE IF NOT EXISTS event_log (
      id         SERIAL      PRIMARY KEY,
      bin_id     VARCHAR(20) NOT NULL,
      event_type VARCHAR(30) NOT NULL,
      detail     JSONB,
      created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
  );
  CREATE INDEX IF NOT EXISTS idx_evt_bin  ON event_log(bin_id);
  CREATE INDEX IF NOT EXISTS idx_evt_type ON event_log(event_type);
  CREATE INDEX IF NOT EXISTS idx_evt_time ON event_log(created_at DESC);

  CREATE TABLE IF NOT EXISTS trucks (
      truck_id     VARCHAR(20) PRIMARY KEY,
      plate        VARCHAR(15),
      capacity_kg  NUMERIC     DEFAULT 8000,
      base_mass_kg NUMERIC     DEFAULT 12000,
      status       VARCHAR(15) DEFAULT 'IDLE'
                   CHECK (status IN ('IDLE','EN_ROUTE','COLLECTING','RETURNING','MAINTENANCE'))
  );

  CREATE TABLE IF NOT EXISTS truck_telemetry (
      id              BIGSERIAL   PRIMARY KEY,
      truck_id        VARCHAR(20) NOT NULL REFERENCES trucks(truck_id),
      sim_timestamp   TIMESTAMPTZ NOT NULL,
      lat             DOUBLE PRECISION NOT NULL,
      lon             DOUBLE PRECISION NOT NULL,
      current_mass_kg NUMERIC     NOT NULL,
      speed_kmh       NUMERIC,
      heading         NUMERIC,
      route_id        VARCHAR(50),
      segment_index   INTEGER,
      created_at      TIMESTAMPTZ DEFAULT NOW()
  );
  CREATE INDEX IF NOT EXISTS idx_tt_truck_time ON truck_telemetry(truck_id, sim_timestamp DESC);

  CREATE TABLE IF NOT EXISTS collection_events (
      id                SERIAL      PRIMARY KEY,
      truck_id          VARCHAR(20) NOT NULL,
      bin_id            VARCHAR(20) NOT NULL,
      collected_mass_kg NUMERIC     NOT NULL,
      sim_timestamp     TIMESTAMPTZ NOT NULL,
      route_id          VARCHAR(50),
      created_at        TIMESTAMPTZ DEFAULT NOW()
  );
  CREATE INDEX IF NOT EXISTS idx_ce_bin  ON collection_events(bin_id, sim_timestamp DESC);
  CREATE INDEX IF NOT EXISTS idx_ce_trk  ON collection_events(truck_id, sim_timestamp DESC);
  ```

- [ ] `psql -U postgres -d ecohaul -f backend/database/init.sql` → hatasız çalışıyor
- [ ] `\dt` → 5 tablo görünüyor

---

#### Gün 2–3 · 19–20 Mart · `seed_dublin.py` — Koordinat Dönüşümü

- [ ] `pyproj` ile EPSG:2157 → EPSG:4326:
  ```python
  from pyproj import Transformer
  t = Transformer.from_crs("EPSG:2157", "EPSG:4326", always_xy=True)
  lon, lat = t.transform(irish_x, irish_y)
  # always_xy=True → her zaman (lon, lat) sırasını garanti et
  ```
- [ ] `asyncpg` ile toplu INSERT (executemany):
  ```python
  await conn.executemany(
      "INSERT INTO bins (bin_id, geom, region) VALUES "
      "($1, ST_SetSRID(ST_MakePoint($2,$3),4326), $4)",
      records
  )
  ```
- [ ] Dublin bbox doğrulama:
  - Latitude: 53.20° – 53.45°
  - Longitude: -6.45° – -6.05°
- [ ] Script çalıştır: `python backend/scripts/seed_dublin.py`
- [ ] `SELECT COUNT(*) FROM bins;` → **300** (seçili Dublin bin'i)
- [ ] 5 rastgele bin koordinatını Google Maps'te doğrula

---

#### Gün 3–4 · 20–21 Mart · `database/schema.py` + Bağlantı Havuzu

- [ ] `asyncpg.create_pool()` ile connection pool:
  ```python
  pool = await asyncpg.create_pool(DATABASE_URL, min_size=2, max_size=10)
  ```
- [ ] FastAPI startup/shutdown event'lerine pool bağla
- [ ] `GET /bins` endpoint ilk versiyonu:
  ```python
  @app.get("/bins")
  async def get_bins(region: str = None, fill_level: str = None):
      query = "SELECT bin_id, ST_Y(geom) AS lat, ST_X(geom) AS lon,
               region, is_active, fill_level FROM bins WHERE 1=1"
      # filtreler dinamik ekleniyor
  ```

---

#### Gün 4–5 · 21–22 Mart · Faz 1 Testleri

- [ ] `tests/conftest.py` — pytest fixtures: test DB bağlantısı, seed data
- [ ] `tests/test_phase1.py` — 5 test:
  - `test_coordinate_bounds` — tüm koordinatlar Dublin bbox içinde
  - `test_bin_count` — `SELECT COUNT(*) = 3425`
  - `test_postgis_geometry` — `ST_IsValid(geom) = TRUE` tüm satırlar
  - `test_fill_level_default` — tümü `fill_level='LOW'`
  - `test_get_bins_200` — `GET /bins` 200 döner, liste boş değil
- [ ] `pytest tests/test_phase1.py -v` → 5/5 yeşil

---

#### Gün 5–7 · 22–23 Mart · Ek: PostGIS GIS Sorgularını Hazırla

- [ ] `backend/services/` altına `gis_queries.py` ekle — ileride optimization_engine'de kullanılacak sorgular hazır olsun:
  ```python
  # 1 km yarıçapındaki aktif HIGH bin'ler
  QUERY_NEARBY_HIGH = """
      SELECT bin_id, region, fill_level,
             ST_Y(geom) AS lat, ST_X(geom) AS lon,
             ST_Distance(geom::geography,
               ST_MakePoint($1,$2)::geography) AS distance_m
      FROM bins
      WHERE is_active = TRUE AND fill_level = $3
        AND ST_DWithin(geom::geography,
              ST_MakePoint($1,$2)::geography, $4)
      ORDER BY distance_m;
  """
  ```
- [ ] Test: `SELECT COUNT(*)` ile 500m yarıçap → sonuç mantıklı mı kontrol et

**✅ Faz 1A tamamlandı. 300 bin PostGIS'te, `GET /bins` çalışıyor.**

---

## Faz 1B — React Leaflet Haritası
### Hafta 2 devamı · 24–30 Mart

**Hedef:** Dublin haritasında 300 bin gerçek zamanlı CircleMarker ile akıcı şekilde görünüyor.

---

#### Gün 1–2 · 24–25 Mart · React Leaflet Temel Kurulum

- [ ] `frontend/src/components/MapView.jsx` — react-leaflet MapContainer:
  ```jsx
  <MapContainer center={[53.34, -6.27]} zoom={13}
                style={{height:"100vh"}} preferCanvas={true}>
    <TileLayer url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"/>
    {bins.map(b => <BinMarker key={b.bin_id} bin={b}/>)}
  </MapContainer>
  ```
- [ ] `preferCanvas={true}` → CircleMarker Canvas renderer (300 nokta için de performanslı, ileride ölçeklenmeye hazır)
- [ ] `frontend/src/services/api.js` — axios instance:
  ```js
  const api = axios.create({ baseURL: 'http://localhost:8000' });
  export const getBins = () => api.get('/bins');
  ```
- [ ] `useEffect` ile ilk yüklemede `GET /bins` çağrısı

---

#### Gün 2–3 · 25–26 Mart · BinMarker + Renk Sistemi

- [ ] `BinMarker.jsx` — fill_level'e göre renk:
  ```jsx
  const COLORS = {
    LOW: '#22c55e',     // Tailwind green-500
    MEDIUM: '#eab308',  // Tailwind yellow-500
    HIGH: '#ef4444',    // Tailwind red-500
    OFFLINE: '#6b7280'  // Tailwind gray-500
  };
  // is_active=false → OFFLINE rengi
  ```
- [ ] Her marker'a Popup ekle: `bin_id`, `region`, `fill_level`, `is_active`
- [ ] Tailwind layout: sidebar placeholder + harita tam ekran

---

#### Gün 3–5 · 26–28 Mart · Polling + Dinamik Güncelleme

- [ ] `setInterval` ile her 5 sn `GET /bins` çağrısı
- [ ] `POST /update-fill` ile test: birkaç bin'i MEDIUM/HIGH yap → haritada renk değişiyor mu kontrol
- [ ] Bölge filtresi (`?region=MERCHANTS+QUAY+C`) → sidebar dropdown

---

#### Gün 5–7 · 28–30 Mart · Header + Tailwind Layout

- [ ] `Header.jsx` — proje adı, canlı saat (`setInterval` 1sn)
- [ ] Responsive layout: `flex h-screen`
- [ ] Harita yüklenme süresi tarayıcı DevTools ile ölç → **≤ 1 sn** (300 kutu için optimize)
- [ ] 300 CircleMarker akıcı render → FPS DevTools'dan kontrol

**✅ Faz 1 tamamlandı. Haritada 300 Dublin bin'i görünüyor, renkler fill_level'a göre.**

---

## Faz 2A — IoT Simülatörü + Anomali Motoru
### Hafta 3 · 31 Mart – 6 Nisan

**Hedef:** Canlı sensör simülasyonu ve tam geçiş matrisi ile anomali tespiti.

---

#### Gün 1–2 · 31 Mar – 1 Nis · `anomaly_engine.py`

Tam geçiş matrisi uygulanır (9 durum):

| Sıra | Geçiş | Kamyon? | event_type |
|---|---|---|---|
| 1 | LOW→MEDIUM | — | _(log yok)_ |
| 2 | MEDIUM→HIGH | — | `OVERFLOW_RISK` |
| 3 | LOW→HIGH | — | `FILL_SKIP_ANOMALY` |
| 4 | HIGH→LOW | ✅ | `COLLECTION_COMPLETE` |
| 5 | HIGH→LOW | ❌ | `SUSPICIOUS_EMPTYING` |
| 6 | HIGH→MEDIUM | ✅ | `COLLECTION_COMPLETE` |
| 7 | HIGH→MEDIUM | ❌ | `SUSPICIOUS_EMPTYING` |
| 8 | MEDIUM→LOW | ✅ | `COLLECTION_COMPLETE` |
| 9 | MEDIUM→LOW | ❌ | `SUSPICIOUS_EMPTYING` |

- [ ] Kamyon tespiti: `truck_telemetry` son 15 dk GPS → `ST_DWithin(geom, bin_geom, 100)` — 100m yarıçap
- [ ] `POST /update-fill` endpoint tamamlanıyor
- [ ] `telemetry` tablosuna INSERT (sadece INSERT, UPDATE yok — zaman serisi)
- [ ] `event_log` tablosuna anomali kaydı (JSONB `detail`)

---

#### Gün 2–4 · 1–3 Nis · `iot_simulator.py`

- [ ] Async loop, her 10 sn çalışır
- [ ] `K = total_active_bins × 0.10` — 300 kutu için her turda ~30 kutu güncelle (daha yoğun ama yönetilebilir yük)
- [ ] Zaman profili:
  ```python
  FILL_PROBABILITY = {
      range(0,6): 0.02,   # Gece
      range(6,9): 0.15,   # Sabah yoğunluğu
      range(9,18): 0.08,  # Gündüz
      range(18,22): 0.20, # Akşam yoğunluğu
      range(22,24): 0.05  # Gece geç
  }
  ```
- [ ] Seçilmeyen bin'lere `POST /heartbeat`
- [ ] Simülatör başlatınca haritada bin'ler dolmaya başlıyor

---

#### Gün 4–5 · 3–4 Nis · 8 Event Type — `event_log` Şeması

Tüm event tipleri ve JSONB örnekleri:

| event_type | detail örneği |
|---|---|
| `OVERFLOW_RISK` | `{"previous_fill":"MEDIUM","region":"MERCHANTS QUAY C"}` |
| `FILL_SKIP_ANOMALY` | `{"previous_fill":"LOW","new_fill":"HIGH","reason":"Seviye atlama"}` |
| `SUSPICIOUS_EMPTYING` | `{"previous_fill":"HIGH","new_fill":"LOW","reason":"Kamyon bulunamadı"}` |
| `COLLECTION_COMPLETE` | `{"previous_fill":"HIGH","new_fill":"LOW","verified_by":"truck_proximity"}` |
| `BIN_OFFLINE` | `{"reason":"3 loop heartbeat gelmedi","missed_loops":3}` |
| `BIN_ONLINE` | `{"previous_state":"offline"}` |
| `ROUTE_BLOCKED` | `{"street":"O'Connell St","coords":[-6.26,53.34]}` |
| `ANOMALY_RESOLVED` | `{"resolved_by":"collection"}` |

- [ ] Her event için JSONB detail doğru yazılıyor

---

#### Gün 5–7 · 4–6 Nis · Faz 2A Test Matrisi

- [ ] `tests/test_phase2.py` — ilk 5 test:
  - `test_fill_skip_anomaly` — LOW→HIGH → `FILL_SKIP_ANOMALY`
  - `test_overflow_risk` — MEDIUM→HIGH → `OVERFLOW_RISK`
  - `test_normal_transition` — LOW→MEDIUM → event yok
  - `test_suspicious_no_truck` — HIGH→LOW + kamyon yok → `SUSPICIOUS_EMPTYING`
  - `test_collection_with_truck` — HIGH→LOW + kamyon var → `COLLECTION_COMPLETE`
- [ ] `pytest tests/test_phase2.py::test_fill_skip_anomaly -v` vb.

**✅ Faz 2A tamamlandı. Anomali motoru 9 senaryonun tamamını doğru yönetiyor.**

---

## Faz 2B — Heartbeat Manager + ESP32 Entegrasyonu
### Hafta 4 · 7–13 Nisan

**Hedef:** 3-loop miss counter heartbeat sistemi + gerçek ESP32 ile ilk veri.

---

#### Gün 1–3 · 7–9 Nis · `heartbeat_manager.py` — Conditional Write

```python
# In-memory miss counter
heartbeat_miss: Dict[str, int] = {}

async def tick():
    for bin_id in all_bins:
        if received_heartbeat(bin_id):
            heartbeat_miss[bin_id] = 0
            current = await get_is_active(bin_id)
            if not current:          # False → True: WRITE
                await set_active(bin_id, True)
                await log_event(bin_id, "BIN_ONLINE")
            # True → True: NO WRITE (write optimizasyonu)
        else:
            heartbeat_miss[bin_id] = heartbeat_miss.get(bin_id, 0) + 1
            if heartbeat_miss[bin_id] >= 3:
                current = await get_is_active(bin_id)
                if current:          # True → False: WRITE
                    await set_active(bin_id, False)
                    await log_event(bin_id, "BIN_OFFLINE")
                heartbeat_miss[bin_id] = 3  # cap
```

- [ ] `POST /heartbeat` endpoint tamamlanıyor
- [ ] Tick süresi: 30 sn
- [ ] Write istatistiği: 300 aktif bin = **0 write/tick** (tümü True)

---

#### Gün 3–5 · 9–11 Nis · Write Optimizasyon Testi

- [ ] Heartbeat testleri:
  - `test_heartbeat_true_to_true_no_write` — zaten True olan bin'e HB → DB write YOK
  - `test_heartbeat_false_to_true_write` — False olan bin'e HB → True yap (WRITE)
  - `test_3_loop_miss_offline` — 3 loop miss → `is_active=FALSE` + `BIN_OFFLINE`
  - `test_miss_counter_reset` — 2 loop miss sonrası HB gelirse counter sıfırlanır
- [ ] `pytest tests/test_phase2.py -v` → 9/9 yeşil

---

#### Gün 5–7 · 11–13 Nis · ESP32 İlk Entegrasyonu

- [ ] Arduino IDE kurulumu + ESP32 board kurulumu
- [ ] ArduinoJson + kütüphaneler yüklendi
- [ ] `ecohaul_sensor.ino` firmware yüklendi (bkz. `ESP32_IOT_KATMANI.md`)
- [ ] JSN-SR04T devre kurulumu: TRIG→GPIO5, ECHO→GPIO18 (gerilim bölücü ile)
- [ ] Seri monitör: mesafe ölçümleri görünüyor
- [ ] WiFi bağlanıyor, `POST /heartbeat` başarılı → PostgreSQL'de `is_active=TRUE`
- [ ] Konteynere nesne koyunca fill_level değişiyor → harita güncelleniyor

> **Not:** ESP32 demodan önce **tam test edilmeli**. Demo'da backend yalnızca yazılım simülatöründen beslenmeli, ESP32 bonus/ek gösterim olmalı.

**✅ Faz 2 tamamlandı. Canlı IoT simülasyonu + gerçek ESP32 veri akışı çalışıyor.**

---

## Faz 3A — Optimizasyon Motoru
### Hafta 5 · 14–20 Nisan

**Hedef:** Mass-Aware ve Greedy algoritmalar, KPI karşılaştırması.

---

#### Gün 1–3 · 14–16 Nis · `optimization_engine.py` — Mass-Aware Algoritma

```
Algoritma Adımları:
  1. Başlangıç: Araç depoda, m_current = 0
  2. HIGH bin'ler → zorunlu ziyaret listesi
  3. MEDIUM bin'ler → isteğe bağlı liste
  4. Her iterasyon:
     a. Mevcut konumdan tüm ziyaret edilmemişlere maliyet:
        C_ij = (m_base + m_current) × d_ij × α_ij
     b. En düşük maliyetli bin → ziyaret et
     c. m_current += bin.estimated_mass
     d. Kapasite doldu → depoya dön, m_current = 0
  5. Tüm zorunlu bin'ler tamamlandı → depoya dön
```

Mesafe hesabı PostGIS ile:
```sql
-- metre cinsinden geodesic mesafe
SELECT ST_Distance(
    ST_MakePoint($1,$2)::geography,
    ST_MakePoint($3,$4)::geography
) AS distance_m;
```

- [ ] `optimization_engine.py` sınıfı implemente et
- [ ] `α` katsayısı formülü (ORS response'dan, §6.2):
  $$\alpha_{ij} = 1 + \max(0, \frac{ascent_j - descent_j}{100}) \times 0.15$$
- [ ] Faz 3'te ORS entegre olmadan önce: `α=1.0` sabit kullan (placeholder)

---

#### Gün 3–4 · 16–17 Nis · Greedy Algoritması

- [ ] Greedy: her adımda sadece en yakın ziyaret edilmemiş HIGH bin
- [ ] Kütle, yükseklik, araç yükü göz ardı
- [ ] Her iki algoritma aynı `(bin_list, depot, m_base, capacity)` imzasını alır

---

#### Gün 4–5 · 17–18 Nis · KPI Hesaplama + `/routes/*` Endpoint'leri

- [ ] `kpi_calculator.py`:

  | Metrik | Formül |
  |---|---|
  | Toplam Yakıt | Σ(m_current × d_km × fuel_coeff) |
  | CO₂ | Toplam Yakıt × 2.68 |
  | Toplam Mesafe | Σ d_km |
  | Rota Süresi | Σ (d_km / v_avg=40) |
  | Enerji Verimliliği | kg_atık / litre_yakıt |

- [ ] `GET /routes/greedy`, `GET /routes/ecohaul`, `GET /routes/compare` endpoint'leri
- [ ] `/routes/compare` response:
  ```json
  {
    "bin_count": 47,
    "ecohaul": {"total_distance_km":42.3,"estimated_fuel_liters":18.2,"co2_kg":48.8},
    "greedy":  {"total_distance_km":51.7,"estimated_fuel_liters":24.8,"co2_kg":66.5},
    "savings": {"fuel_percent":26.6,"co2_kg":17.7}
  }
  ```

---

#### Gün 5–7 · 18–20 Nis · Faz 3A Testleri

- [ ] `tests/test_phase3.py` ilk 6:
  - `test_mass_cost_increases_with_load` — yüklü maliyet > boş maliyet
  - `test_ecohaul_beats_greedy_fuel` — deterministik 20-bin seti
  - `test_route_covers_all_high_bins` — tüm HIGH binler rotada
  - `test_elevation_alpha_uphill` — α > 1.0
  - `test_elevation_alpha_downhill` — α = 1.0
  - `test_depot_return_on_capacity` — kapasite dolunca depoya dönüş
- [ ] Test fixture: `tests/fixtures/deterministic_bins.json` — sabit 20 bin seti

**✅ Faz 3A tamamlandı. İki algoritma da KPI üretiyor.**

---

## Faz 3B — ORS Entegrasyonu + Kamyon Simülatörü
### Hafta 6 · 21–27 Nisan

**Hedef:** Gerçek yol geometrisi, avoid_polygons, smooth kamyon animasyonu.

---

#### Gün 1–3 · 21–23 Nis · `routing_service.py` — ORS Public API

- [ ] `POST https://api.openrouteservice.org/v2/directions/driving-hgv/geojson`
- [ ] Header: `Authorization: Bearer {ORS_API_KEY}`
- [ ] Body:
  ```json
  {
    "coordinates": [[-6.27,53.34],[-6.25,53.35],...],
    "elevation": true,
    "options": {"avoid_polygons": {...}}
  }
  ```
- [ ] Response'dan geometry extraction: `response["features"][0]["geometry"]`
- [ ] `segments[].ascent` / `segments[].descent` → α katsayısı güncelleniyor
- [ ] **Route cache**: `Dict[tuple_of_bin_ids, route_geometry]` — ORS limitini yönetmek için aynı rota geometry'si saklanır
- [ ] Rate limit yönetimi: 40 req/dk → gerekirse `asyncio.sleep(1.5)` araya eklenir

---

#### Gün 3–5 · 23–25 Nis · Yol Kapatma (avoid_polygons)

- [ ] Co-Pilot intent'i olmadan da test: `POST /routes/ecohaul?avoid=true` ile
- [ ] GeoJSON Polygon oluştur: kapalı yol koordinatı → buffer → avoid_polygon
- [ ] ORS → yeni rota kapalı yoldan geçmiyor

```
Sürücü: "O'Connell St kapalı"
    │
    ▼
Backend: avoid_polygon oluştur
    │
    ▼
ORS: yeni rota hesapla
    │
    ▼
Frontend: eski polyline sil, yeni çiz
          kırmızı polygon haritada göster
```

- [ ] `AvoidPolygonLayer.jsx` — kırmızı polygon component

---

#### Gün 4–6 · 24–26 Nis · `truck_simulator.py` — Shapely Interpolation

- [ ] ORS GeoJSON koordinatları → Shapely LineString:
  ```python
  from shapely.geometry import LineString
  line = LineString([(lon1,lat1),(lon2,lat2),...])
  pos  = line.interpolate(fraction, normalized=True)
  lat, lon = pos.y, pos.x
  ```
- [ ] Her tick'te `fraction += delta` (rota süresine göre)
- [ ] `truck_telemetry` tablosuna GPS pingleri INSERT
- [ ] 50m yarıçapında bin'e ulaşınca `collection_event` oluştur

---

#### Gün 6–7 · 26–27 Nis · `TruckMarker.jsx` — Leaflet.MovingMarker

- [ ] Leaflet.MovingMarker entegrasyonu:
  ```javascript
  import 'leaflet-moving-marker';
  const marker = L.Marker.movingMarker(latlngs, durations, {autostart:true});
  marker.addTo(map).start();
  ```
- [ ] ORS waypoint dizisi → `latlngs`, segment süreleri → `durations`
- [ ] Kamyon ikon: özel SVG truck ikonu
- [ ] Kamyon bin'e ulaşınca bin marker yeşile döner (animasyonlu)

- [ ] Testler:
  - `test_ors_avoid_polygon` — avoid → bölgeden geçmiyor
  - `test_ors_route_road_snapped` — gerçek yol (düz çizgi değil)

**✅ Faz 3 tamamlandı. Haritada mavi EcoHaul + kırmızı Greedy rota, smooth kamyon hareketi.**

---

## Faz 4A — Random Forest Regressor + Tahmin API'si
### Hafta 7 · 28 Nisan – 4 Mayıs

**Hedef:** 1 yıllık jenerik (sentetik/geçmiş) veri seti üzerinden N saat sonra HIGH tahmini yapabilen basit ama güvenilir bir model.

---

#### Gün 1–2 · 28–29 Nis · 1 Yıllık Jenerik Veri Seti Entegrasyonu

- [ ] Daha önce hazırlanmış 1 yıllık jenerik doluluk veri setini (CSV/Parquet) `data/generic_fill_history.*` olarak projeye ekle
- [ ] Bu veri setini `pandas` ile okuyup aşağıdaki feature'ları üret:
  ```
  hour_of_day           ← 0–23
  day_of_week          ← 0–6
  is_weekend           ← day_of_week in [0,6]
  hours_since_last_empty ← son LOW geçişinden bu yana saat
  region_encoded       ← LabelEncoder
  rolling_fill_rate    ← son 3 ölçümde kaç kez artış olmuş (0–3)
  ```
- [ ] **Hedef değişken:** `hours_until_high` — satırdan sonra kaç saat içinde HIGH'a ulaşacağı (regresyon)
- [ ] Eğitimi bu 1 yıllık veri üzerinde yap, değerlendirmeyi zaman bazlı bir split ile (örneğin son 2 ay test olacak şekilde) kurgula

---

#### Gün 2–4 · 29 Nis – 1 May · `prediction_model.py` — RandomForest Regressor

- [ ] scikit-learn pipeline:
  ```python
  from sklearn.ensemble import RandomForestRegressor
  from sklearn.pipeline import Pipeline
  from sklearn.preprocessing import StandardScaler

  model = Pipeline([
      ('scaler', StandardScaler()),
      ('rf', RandomForestRegressor(n_estimators=100, random_state=42))
  ])
  model.fit(X_train, y_train)
  ```
- [ ] Model değerlendirmesi: MAE (Mean Absolute Error) **≈ 2–4 saat** aralığında olacak şekilde makul bir doğruluk hedefi belirle (jenerik veri olduğu için aşırı beklenti yok)
- [ ] `joblib.dump(model, 'models/fill_predictor.pkl')` — persist
- [ ] Yüklendiğinde tahmin:
  ```python
  y_pred = model.predict(X_live)  # hours_until_high
  # confidence: std of individual trees
  ```

---

#### Gün 4–5 · 1–2 May · `GET /predictions` Endpoint

- [ ] Aktif 300 bin'in canlı feature'larını çek (telemetry + bins + generic model input'ları)
- [ ] Model ile tahmin et
- [ ] Response:
  ```json
  [
    {"bin_id":"WMS4505","predicted_high_in_hours":2.3,"confidence":0.84},
    {"bin_id":"WMS4506","predicted_high_in_hours":0.7,"confidence":0.91}
  ]
  ```
- [ ] `PredictionLayer.jsx` — dolacak bin'ler turuncu halka ile işaret:
  - 0–2 saat: büyük turuncu halka (acil)
  - 2–6 saat: küçük turuncu halka (dikkat)

---

#### Gün 5–7 · 2–4 May · Testler

- [ ] `test_prediction_model_accuracy` — MAE ≤ 2 saat
- [ ] `test_predictions_endpoint` — `GET /predictions` 200, liste boş değil
- [ ] Integration: tahmin edilen HIGH bin'ler rotaya ekleniyor mu kontrol

**✅ Faz 4A tamamlandı. 'BIN-4523 taşmak üzere, ~1.5 saat içinde dolacak' tahmini çalışıyor.**

---

## Faz 5 — Dashboard + 30 Gün Demo Simülasyonu (300 Kutu)
### Hafta 9 · 12–18 Mayıs

**Hedef:** 300 kutuluk sistem için tam KPI paneli, 30 gün hızlandırılmış simülasyon ve temel sistem testleri.

---

#### Gün 1–2 · 12–13 May · `KPIBar.jsx` + `RouteComparePanel.jsx`

- [ ] KPI Bar (üst):
  - Toplam Aktif Bin (300 kutu içinde online olanlar, yeşil badge)
  - HIGH Seviye Bin (kırmızı badge)
  - Bugün Toplanan Atık (kg)
  - EcoHaul vs Greedy Yakıt Tasarrufu (%)
  - CO₂ Tasarrufu (kg)
- [ ] Rota karşılaştırma tablosu (sağ sidebar):
  ```
  ╔═══════════════╦═════════╦════════╗
  ║               ║ EcoHaul ║ Greedy ║
  ╠═══════════════╬═════════╬════════╣
  ║ Mesafe        ║  42.3km ║ 51.7km ║
  ║ Yakıt         ║  18.2L  ║ 24.8L  ║
  ║ CO₂           ║  48.8kg ║ 66.5kg ║
  ║ Süre          ║  2.3sa  ║ 2.9sa  ║
  ╚═══════════════╩═════════╩════════╝
      EcoHaul %26.6 daha verimli ✓
  ```
- [ ] `EventLog.jsx` — canlı anomali listesi, yeni event gelince flash animasyonu

---

#### Gün 2–4 · 13–15 May · `simulation_runner.py` — 30 Gün

```
Simülasyon parametreleri:
  1 gerçek sn = 30 simüle dk
  1 simüle gün = 48 tick = 48 gerçek sn
  30 simüle gün = 1,440 tick ≈ 24 dk (+ ORS overhead ~15 dk)
  Toplam: ~40 dk (tam simülasyon)
  Demo için kısa: 3 gün = ~4 dk
```

- [ ] `DemoSimulator.jsx` — hız kontrolü: 1×, 5×, 10×
- [ ] Gün sayacı: "Gün 1/30"
- [ ] Her simüle 06:00'da: yeni rota hesapla, kamyonu yola çıkar
- [ ] 30 gün sonunda: KPI özet ekranı

---

#### Gün 3–5 · 14–16 May · `validate_simulation.py` + Sistem Testleri

- [ ] V1–V10 doğrulama kontrolleri:
  - `truck_telemetry` > 0 satır
  - `collection_events` > 0 satır
  - ≥ 3 farklı `event_type`
  - `route_id` sayısı ≥ 25
  - EcoHaul toplam yakıt < Greedy toplam yakıt
  - `SUSPICIOUS < COLLECTION_COMPLETE` (anomali oranı mantıklı)
  - `BIN_OFFLINE` oranı < %10

- [ ] `tests/test_system.py` — sistem/performans:
  - `test_get_bins_latency` — `GET /bins` ≤ 200ms
  - `test_concurrent_fill_updates` — 50 eşzamanlı POST → veri kaybı yok
  - `test_30_day_sim_consistency` — 30 gün sonrası DB tutarlı
  - `test_ors_response_time` — 47 durak → ≤ 2 sn

---

#### Gün 5–7 · 16–18 May · Toggle Katmanlar + Final Polish

- [ ] Harita katman toggle'ları (Tailwind checkbox):
  - [x] EcoHaul Rota (mavi)
  - [ ] Greedy Rota (kırmızı)
  - [ ] Sadece HIGH Bin'ler
  - [ ] Tahmin Katmanı (turuncu)
- [ ] Prediction overlay toggle aktif → HIGH'a yaklaşan bin'ler turuncu halka
- [ ] Tüm animasyonlar akıcı (≥ 30 FPS)
- [ ] CORS ayarları production-ready
- [ ] `pytest tests/ -v` → tüm testler yeşil

**✅ Faz 5 tamamlandı. Tam işlevsel dashboard, 30 gün simülasyon çalışıyor.**

---

## Buffer + Demo Hazırlığı
### Hafta 10 · 19–20 Mayıs

**Hedef:** E2E checklist geçmek, demo provası yapmak, son düzeltmeler.

---

#### 19 Mayıs · E2E Demo Checklist (20 Madde)

| # | Kontrol | Kriter |
|---|---|---|
| E1 | Sistem başlatma | `uvicorn` + `npm dev` → tüm servisler ayakta |
| E2 | Harita yüklenme | ≤ 2 sn |
| E3 | 300 bin görünüyor | Yeşil CircleMarker |
| E4 | Popup çalışıyor | bin_id, region, fill_level |
| E5 | Simülasyon başlat | Bin'ler dolmaya başlıyor |
| E6 | İlk HIGH bin | Kırmızı flash + alert |
| E7 | EcoHaul rotası | Mavi, gerçek yol |
| E8 | Greedy rotası | Kırmızı, farklı |
| E9 | KPI panel | ≥ %15 yakıt tasarrufu |
| E10 | Kamyon hareketi | Polyline üzerinde smooth |
| E11 | Kamyon toplama | Bin yeşile döner |
| E12 | Heartbeat offline | 90 sn → gri |
| E13 | Seviye atlama | FILL_SKIP_ANOMALY |
| E14 | Şüpheli döküm | SUSPICIOUS_EMPTYING |
| E15 | Yol kapatma | Yeni rota + kırmızı polygon |
| E16 | Tahmin API'si | `GET /predictions` 200, mantıklı çıktı |
| E17 | Prediction overlay | Dolacak bin'ler turuncu |
| E18 | Rota + tahmin entegrasyonu | Tahmin edilen HIGH bin'ler rota planına eklenmiş |
| E19 | 30 gün simülasyon | KPI özet doğru |
| E20 | Genel akıcılık | Hata/crash yok |

---

#### 20 Mayıs · Son Provası + Teslim

- [ ] Demo akışı (15–20 dk) tam provası — timer tut
- [ ] Ekran kaydı yedek: OBS/Kazam ile kayıt al (demo sırasında teknik sorun olursa)
- [ ] `README.md` güncelle: kurulum adımları, gereksinimler
- [ ] Kod kalitesi: `# TODO` kalmadı, kritik modüllere docstring var
- [ ] GitHub son commit push
- [ ] Demo makinesi kontrolü: pil yeterli, WiFi hazır, tüm port'lar açık

---

## Test Özeti

```
Toplam: 60 test senaryosu

Faz 1  (Unit)        U1–U5    →  5 test  ← 23 Mart'a kadar
Faz 2  (Unit)        U6–U14   →  9 test  ← 13 Nisan'a kadar
Faz 3  (Unit)        U15–U22  →  8 test  ← 27 Nisan'a kadar
Faz 4  (Unit)        U23–U27  →  5 test  ← 11 Mayıs'a kadar
Integration          I1–I9    →  9 test  ← 11 Mayıs'a kadar
Sistem/Performans    S1–S4    →  4 test  ← 18 Mayıs'a kadar
30-Gün Doğrulama     V1–V10   → 10 test  ← 18 Mayıs'a kadar
E2E Demo Checklist   E1–E20   → 20 adet  ← 19 Mayıs'a kadar
```

---

## Risk ve Önlem

| Risk | Olasılık | Etki | Önlem |
|---|---|---|---|
| ORS API rate limit (2K req/gün) | Orta | Yüksek | Route cache; 30 gün sim için pre-computed geometry JSON |
| ESP32 WiFi güvenilirliği (demo) | Yüksek | Orta | Demo'da yazılım simülatörü esas; ESP32 bonus gösterim |
| ML model domain farkı (jenerik veri) | Orta | Orta | 1 yıllık generic veri setini Dublin dağılımına benzer seç; model çıktısını dashboard'da "yardımcı sinyal" olarak sun |
| Faz kayması (birinin gecikmesi) | Orta | Yüksek | Her fazın son günü buffer; Faz 5 frontend'i Faz 3'te başlayabilir |
| PostGIS koordinat hatası | Düşük | Yüksek | `always_xy=True` zorunlu; Faz 1'de test U1 ile erken yakalanır |

---

## Kritik Kararlar Özeti

| # | Karar | Detay |
|---|---|---|
| K1 | PostGIS tek DB | MongoDB kaldırıldı; `$near` → `ST_DWithin`, 2dsphere → `GIST(geom)` |
| K2 | ORS Public API | Self-host Docker yok; route cache ile 2K/gün limit yönetilir |
| K3 | Docker yok | Native kurulum; `psql -f init.sql` tek komutla |
| K4 | RF Regressor | Classifier değil; `hours_until_high` sürekli çıktı daha bilgilendirici |
| K5 | Leaflet.MovingMarker | `requestAnimationFrame` yerine; waypoint + duration listesi, düşük CPU |
| K6 | Conditional write | Heartbeat: sadece False→True değişiminde DB write; %99+ optimizasyon |
| K7 | 3-loop miss | Cron job yerine; 30sn tick × 3 = 90sn offline eşiği |
| K8 | 60sn ESP32 sleep | 90sn limitin altında; 1 paket kaybında BIN_OFFLINE tetiklenmiyor |

---

*Yol haritası proje boyunca güncel tutulacaktır. Her faz tamamlandığında ilgili satırlardaki kutucuklar işaretlenir.*

---

## Kişisel Sprint Planı — 22 Mart 2026 → 22 Mayıs 2026

**Amaç:** 25–31 Mart arasında en az bir ESP32 modülünden backend'e veri akışını sağlamak ve kalan sürede mevcut faz planına paralel ilerlemek.

Bu kişisel plan, yukarıdaki Faz 1–5 yapısını bozmadan senin gerçek zamanlı çalışma takvimine uyarlanmış bir sprint görünümü sağlar.

### Haftalık Özet

```
Hafta  Tarihler        Odak                          İlgili Faz
─────  ─────────────   ───────────────────────────   ─────────────
W1     22–28 Mar       Backend sağlamlaştırma +      Faz 1A/1B
                      ESP32 donanım hazırlığı
W2     29 Mar–4 Nis    ESP32 → Backend veri akışı    Faz 1B → 2B (erken)
W3     5–11 Nis        Heartbeat + temel anomali     Faz 2A/2B
W4     12–18 Nis       IoT simülatörü + harita enteği Faz 2A/2B
W5     19–25 Nis       Optimizasyon motoru (çekirdek) Faz 3A
W6     26 Nis–2 May    ORS + kamyon simülatörü       Faz 3B
W7     3–9 May         RF tahmin modeli + /predictions Faz 4A
W8     10–16 May       Dashboard + KPI polisajı (300 kutu) Faz 5
W9     17–22 May       30g sim + demo + teslim haz.  Faz 5 + Buffer
```

---

### Hafta W1 · 22–28 Mart — DB/API Sağlamlaştırma + ESP32 Donanım

**Hedef:** 29 Mart'a girmeden backend/API tamamen stabil olsun ve ESP32 donanımı masada ölçüm yapabilir hale gelsin.

- [ ] 22–23 Mar · DB + API son kontrolleri
  - [ ] `backend/scripts/*.py` ile cleaning/transform/validate pipeline'ını uçtan uca tekrar çalıştır
  - [ ] `backend/scripts/load_bins_to_db.py` ile PostGIS'e yüklemeyi doğrula (`COUNT(*)` ve bbox)
  - [ ] `uvicorn app.main:app --reload` ile `/api/bins` ve `/api/bins/summary` endpointlerini tarayıcıdan ve Postman'den test et
- [ ] 24–25 Mar · ESP32 + sensör donanım kurulumu
  - [ ] ESP32 board + JSN-SR04T devre bağlantısını [dosyalar/ESP32_IOT_KATMANI.md](dosyalar/ESP32_IOT_KATMANI.md) şemasına göre yap
  - [ ] Level shifter / gerilim bölücü ile ECHO pinini 3.3V seviyesine indir, multimetre ile ölç
  - [ ] 5–6 farklı mesafede (30/50/70 cm) seri monitörden değer okuyup T-H1 doğruluk testini geç
- [ ] 26–28 Mar · Firmware iskeleti
  - [ ] `ecohaul_sensor.ino` içindeki WiFi ve basit mesafe ölçümünü derleyip ESP32'ye yükle
  - [ ] Seri monitörde her boot'ta mesafe ve fill_level (`LOW/MEDIUM/HIGH`) çıktığını gör
  - [ ] WiFi SSID/IP ayarlarını backend çalışacak makinenle aynı LAN'da olacak şekilde netleştir

> Bu haftanın sonunda: **ESP32 donanım olarak hazır**, mesafe ölçüyor ve seri monitörde stabil veri gösteriyor olmalı.

---

### Hafta W2 · 29 Mart – 4 Nisan — ESP32 → Backend Veri Akışı (Kritik)

**Kritik hedef (29–31 Mart):** En az bir ESP32 modülü `/update-fill` ve `/heartbeat` endpointlerine veri gönderecek, PostgreSQL'de `telemetry` ve `bins.is_active` güncellemeleri görülecek.

- [ ] 29–31 Mar · HTTP entegrasyonu
  - [ ] Backend tarafında minimal `/update-fill` ve `/heartbeat` endpointlerini hazırla (gerekirse önce basit loglama ile başla)
  - [ ] Firmware'de `sendFillUpdate` ve `sendHeartbeat` fonksiyonlarını çalışır hale getir (ESP32_IOT_KATMANI.md §7)
  - [ ] Postman/HTTPie ile elle `POST /update-fill` ve `POST /heartbeat` deneyip backend'in doğru cevap verdiğinden emin ol
  - [ ] ESP32'den gelen gerçek istekleri FastAPI loglarında gör; `telemetry` tablosunda satır oluştuğunu SQL ile doğrula
- [ ] 1–2 Nis · Harita ile ilk canlı entegrasyon
  - [ ] `/api/bins` response'unu ESP32'nin güncellediği `fill_level` ve `is_active` alanlarıyla besle
  - [ ] Frontend map üzerinde ilgili bin'in rengi ESP32 hareketine göre değişiyor mu test et (LOW→MEDIUM→HIGH)
- [ ] 3–4 Nis · Hata yönetimi
  - [ ] WiFi kopması durumunda firmware'in exponential backoff ile davrandığını seri monitörden gözlemle
  - [ ] Backend'te bilinmeyen `bin_id` ve invalid `fill_level` için 404/422 cevaplarını netleştir

> Bu haftanın sonunda: **"ESP32 veri alıyor" hedefi gerçekleşmiş olmalı** — fiziksel hareket → harita rengi değişimi zinciri uçtan uca çalışıyor.

---

### Hafta W3 · 5–11 Nisan — Heartbeat + Temel Anomali Motoru

**Hedef:** 3-loop miss counter heartbeat mekanizması ve en az 3 anomali senaryosunun uçtan uca çalışması.

- [ ] 5–7 Nis · Heartbeat manager
  - [ ] `heartbeat_manager.py` içinde 30 sn tick + 3-loop miss mantığını implemente et
  - [ ] ESP32'nin 60 sn sleep süresi ile backend `T_tick=30 sn` senkronizasyonunu test et
  - [ ] `BIN_OFFLINE` ve `BIN_ONLINE` eventlerinin `event_log` tablosunda oluştuğunu SQL ile doğrula
- [ ] 8–9 Nis · Temel anomaly_engine
  - [ ] LOW→MEDIUM (event yok), MEDIUM→HIGH (`OVERFLOW_RISK`), LOW→HIGH (`FILL_SKIP_ANOMALY`) senaryolarını kodla
  - [ ] Simülatör veya ESP32 üzerinden bu üç geçişi tetikleyip dashboard'da gözlemle
- [ ] 10–11 Nis · Küçük test paketi
  - [ ] `tests/test_phase2.py`'den en kritik 4–5 testi önce yaz, sonra çalıştır (özellikle seviye atlama ve overflow)

---

### Hafta W4 · 12–18 Nisan — IoT Simülatörü + Harita Entegrasyonu

**Hedef:** Tüm bin'ler için yazılımsal simülatör çalışsın, ESP32 ise seçili birkaç bin için gerçek veri versin.

- [ ] 12–14 Nis · `iot_simulator.py`
  - [ ] Zaman profilli dolma olasılıkları (gece/sabah/gündüz/akşam) için loop'u yaz
  - [ ] Seçilmiş K adet bin için her 10 sn doluluk/heartbeat üret
- [ ] 15–16 Nis · Hibrit mod
  - [ ] Simülatörün güncellediği bin'ler ile ESP32'nin güncellediği bin'leri SQL'de ayırt edip sorgu yaz (kaynak alanı vs.)
  - [ ] Harita üzerinde ESP32 bin'lerini farklı ikon/renkle işaretlemeyi düşün (opsiyonel)
- [ ] 17–18 Nis · Stabilite turu
  - [ ] Backend/Frontend/Simülatör/ESP32 aynı anda çalışırken 30–60 dk gözlem yap; CPU/RAM, DB büyümesi ve logları incele

---

### Hafta W5 · 19–25 Nisan — Optimizasyon Motoru (Çekirdek)

**Hedef:** Mass-aware ve greedy algoritmaların temel halleri çalışsın, henüz ORS entegrasyonu zorunlu değil.

- [ ] 19–21 Nis · Cost fonksiyonu ve rota veri modeli
  - [ ] `optimization_engine.py` için `C_ij = (m_base + m_current) × d_ij × α_ij` formülünü kodla
  - [ ] Basit sentetik bir bin setiyle (10–20 bin) route çıktısını debug et
- [ ] 22–23 Nis · Greedy baseline
  - [ ] Sadece mesafeye göre en yakın HIGH bin'i seçen greedy algoritmayı yaz
  - [ ] İki algoritmanın aynı interface'i kullandığından emin ol
- [ ] 24–25 Nis · İlk KPI karşılaştırmaları
  - [ ] Yakıt/mesafe/CO₂ metriklerini hesaplayan küçük bir yardımcı modül yaz
  - [ ] Küçük bir senaryoda EcoHaul'un greedy'den daha iyi çıktığını sayısal olarak göster

---

### Hafta W6 · 26 Nisan – 2 Mayıs — ORS + Kamyon Simülatörü

**Hedef:** ORS public API ile gerçek yol geometrisi ve frontend'de hareket eden bir kamyon prototipi.

- [ ] 26–28 Nis · ORS entegrasyonu
  - [ ] `routing_service.py` ile `driving-hgv` endpoint'ini çağırıp GeoJSON polyline al
  - [ ] Basit bir rota için polyline'ı haritada göster
- [ ] 29–30 Nis · Kamyon hareketi
  - [ ] Shapely veya Leaflet MovingMarker ile rota üzerinde hareket eden marker'ı göster
  - [ ] Kamyon bin'e yaklaştığında `collection_event` kaydını DB'ye işle
- [ ] 1–2 May · Mini entegrasyon testi
  - [ ] Bir günlük simülasyon senaryosunda rota, telemetry, event_log ve collection_events tutarlı mı kontrol et

---

### Hafta W7 · 3–9 Mayıs — Random Forest + /predictions

**Hedef:** 1 yıllık jenerik veri setiyle eğitilmiş RF modeli + çalışan `/predictions` endpoint'i.

- [ ] 3–5 May · Feature engineering
  - [ ] `hours_since_last_empty`, `rolling_fill_rate`, `is_weekend` vb. feature'ları hazırlayan script yaz
  - [ ] Eğitim/test split'ini belirleyip ilk modeli eğit
- [ ] 6–7 May · Model entegrasyonu
  - [ ] RF modelini diske kaydedip backend içinde yükle
  - [ ] `GET /predictions` ile canlı tahmin response'u dön
- [ ] 8–9 May · Dashboard overlay
  - [ ] 0–2 saat içinde dolacak kutuları turuncu halka ile işaretleyen katmanı ekle

---

### Hafta W8 · 10–16 Mayıs — Dashboard + KPI Polisajı (300 Kutu)

**Hedef:** 300 kutuluk sistem için dashboard'un demo seviyesine getirilmesi; KPI bar, prediction overlay ve katman toggle'larının son halini almak.

- [ ] 10–12 May · Dashboard performans ve UX
  - [ ] 300 kutu ile harita yüklenme süresi ve FPS değerlerini ölç, gerekiyorsa cluster/virtualization ayarlarını incele
  - [ ] KPI bar ve RouteCompare panelini 300 kutuya göre son haliyle yerleştir
- [ ] 13–14 May · Prediction overlay ve rota entegrasyonu
  - [ ] Prediction overlay'in görsel durumunu (turuncu halkalar) son kez gözden geçir
  - [ ] Tahmin edilen HIGH kutuların rota planlamasına nasıl dahil olduğunu UI üzerinden netleştir
- [ ] 15–16 May · Layout ve görsel polish
  - [ ] Event log, katman toggle'ları ve temel animasyonları toparla (gereksiz karmaşıklığı azalt)

---

### Hafta W9 · 17–22 Mayıs — 30 Gün Simülasyon + Demo/Teslim Hazırlığı

**Hedef:** 30 günlük hızlandırılmış simülasyon, demo provası ve teslim evraklarının tamamlanması.

- [ ] 17–18 May · 30 gün simülasyon koşuları
  - [ ] Simülatörü 30 günlük hızlandırılmış modda en az bir kez çalıştır ve KPI sonuçlarını kaydet
  - [ ] Sistem/performance testlerini (GET /bins latency, concurrent POST vb.) bir kez toplu çalıştır
- [ ] 19–20 May · E2E demo provası
  - [ ] ECOHAUL_TEST_VE_DEMO.md'deki demo akışını baştan sona prova et (15–20 dk)
  - [ ] OBS ile yedek ekran kaydı al
- [ ] 21–22 May · Rapor ve teslim
  - [ ] Yazılı rapor, slayt ve teknik dokümanları (özellikle ESP32_IOT_KATMANI ve ROADMAP) gözden geçir
  - [ ] GitHub son temizlik, README güncelleme ve teslim için gerekli PDF/zip paketini hazırla

