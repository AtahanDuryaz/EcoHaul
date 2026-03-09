# EcoHaul AI — Teknik Proje Dokümantasyonu

**Konu:** Yapay Zeka ve IoT Tabanlı Kütle Duyarlı (Mass-Aware) Dinamik Atık Yönetim Sistemi  
**Ders:** CSE-492 Bitirme Projesi  
**Tarih:** Mart 2026  

---

## İçindekiler

1. [Proje Vizyonu ve Problem Tanımı](#1-proje-vizyonu-ve-problem-tanımı)
2. [Sistem Mimarisi — Genel Bakış](#2-sistem-mimarisi--genel-bakış)
3. [Veri Pipeline Katmanları](#3-veri-pipeline-katmanları)
4. [Faz 1 — Veri Altyapısı ve Dijital İkiz](#4-faz-1--veri-altyapısı-ve-dijital-i̇kiz)
5. [Faz 2 — IoT Katmanı ve Anomali Tespiti](#5-faz-2--iot-katmanı-ve-anomali-tespiti)
6. [Faz 3 — Optimizasyon Motoru](#6-faz-3--optimizasyon-motoru)
7. [Faz 4 — Tahminleme ve AI Agent](#7-faz-4--tahminleme-ve-ai-agent)
8. [Faz 5 — Dashboard ve Demo](#8-faz-5--dashboard-ve-demo)
9. [Veritabanı Şemaları (Tam)](#9-veritabanı-şemaları-tam)
10. [API Kontratı (Tam)](#10-api-kontratı-tam)
11. [Frontend Mimari](#11-frontend-mimari)
12. [Test Stratejisi](#12-test-stratejisi)
13. [KPI Metrikleri ve Başarı Kriterleri](#13-kpi-metrikleri-ve-başarı-kriterleri)
14. [Teknoloji Yığını](#14-teknoloji-yığını)
15. [Proje Dosya Yapısı (Tam)](#15-proje-dosya-yapısı-tam)

---

## 1. Proje Vizyonu ve Problem Tanımı

### 1.1 Mevcut Durum ve Sorun

Geleneksel şehir çöp toplama sistemleri iki temel verimsizlik modelinden birini kullanır:

- **Sabit Takvim Modeli:** Binalar haftanın belirli günlerinde, dolu olsun boş olsun, boşaltılır. Kapasitenin %30–40 doluyken yapılan toplamalarda yakıt, iş gücü ve araç ömrü gereksiz tüketilir.
- **Greedy (Açgözlü) Model:** Araç, her zaman kendine en yakın bin'e gider. Fiziksel gerçekliği (yüklü araç daha fazla yakıt harcar, yokuş aşağı gitmek daha verimlidir) tamamen görmezden gelir.

Her iki model de aşağıdaki maliyetlere yol açar:

| Sorun | Sonuç |
|---|---|
| Boş bin'lerin toplanması | Gereksiz yakıt ve CO₂ emisyonu |
| Yüklü araçla uzak mesafelere gitmek | F = m × a nedeniyle katlanarak artan enerji sarfiyatı |
| Taşan bin'lerin geç tespiti | Sağlık riski, şikayet, para cezası |
| Sürücünün anlık trafik/yol durumunu sisteme iletememesi | Rota güncellemelerinin saatler sürmesi |

### 1.2 EcoHaul AI'nin Cevabı

EcoHaul AI bu sorunları üç temel inovasyon ile çözer:

**1. Fizik Tabanlı Rotalama (Mass-Aware Routing)**

Klasik rota optimizasyonu mesafeyi minimize eder. EcoHaul, buna ek olarak araç kütlesinin yakıt maliyetine olan etkisini hesaba katar:

$$F = m \times a$$

$$E_{segment} = F \times d = m_{vehicle} \times a \times d_{segment}$$

$$C_{total} = \sum_{i=1}^{n} (m_{base} + m_{collected,i}) \times d_i \times \alpha_{elevation,i}$$

Burada:
- $m_{base}$ = boş araç kütlesi (kg)
- $m_{collected,i}$ = $i$. segmente kadar toplanan toplam atık kütlesi (kg)
- $d_i$ = $i$. rota segmentinin mesafesi (km)
- $\alpha_{elevation,i}$ = yükseklik farkı ceza katsayısı (düz yol = 1.0, %10 eğim = 1.15)

Bu formül şu fiziksel gerçeği modeller: **araç ne kadar doluysa, o kadar fazla yakıt harcar. Dolayısıyla araç boşken uzak ve yüksek noktalara gitmeli, dolarken merkeze yaklaşmalıdır.**

**2. Dijital İkiz (Digital Twin)**

Şehirdeki tüm konteynerlerin gerçek zamanlı durumu GIS haritasında canlı olarak izlenir. Her konteyner bir "dijital ikiz" nesnesine sahiptir: fiziksel durumu (doluluk seviyesi, aktiflik, bölge) anlık olarak yansıtılır.

**3. AI Co-Pilot**

Sürücü, doğal dilde asistanla konuşabilir:
- *"Neden bu rotaya gidiyoruz?"* → XAI (Explainable AI) açıklama
- *"Şu yol kapalı"* → Anlık rota yeniden hesaplama
- *"Bugün kaç bin doldu?"* → Veri sorgusu

---

## 2. Sistem Mimarisi — Genel Bakış

```
┌─────────────────────────────────────────────────────────────────┐
│                        EcoHaul AI                               │
│                                                                 │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────────┐  │
│  │  IoT Layer   │    │  Data Layer  │    │ Intelligence     │  │
│  │              │    │              │    │ Layer            │  │
│  │ • Ultrasonic │───▶│ • MongoDB    │───▶│ • Mass-Aware     │  │
│  │   Sensors    │    │   (GIS/      │    │   Router         │  │
│  │ • Heartbeat  │    │   Static)    │    │ • Anomaly Engine │  │
│  │ • Simulator  │    │              │    │ • ML Predictor   │  │
│  │              │    │ • PostgreSQL │    │ • LLM Co-Pilot   │  │
│  └──────────────┘    │   (Telemetry │    └──────────────────┘  │
│                      │   /Events)   │             │             │
│                      └──────────────┘             │             │
│                                                   ▼             │
│                      ┌──────────────────────────────────────┐  │
│                      │         FastAPI Gateway               │  │
│                      │  /bins  /update-fill  /heartbeat     │  │
│                      │  /routes/ecohaul  /routes/greedy     │  │
│                      └──────────────────────────────────────┘  │
│                                   │                             │
│                                   ▼                             │
│                      ┌──────────────────────────────────────┐  │
│                      │     React + Leaflet Dashboard         │  │
│                      │  GIS Map  │  KPI Panel  │  Co-Pilot   │  │
│                      └──────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

### 2.1 Katmanlar Arası Veri Akışı

```
Dublin CSV
    │
    ▼
[seed_dublin.py]
    │  pyproj: EPSG:2157 → EPSG:4326
    │
    ├──▶ MongoDB: containers (statik master data)
    └──▶ PostgreSQL: telemetry (başlangıç fill_level = 'LOW')
              │
              │  (simülatör / gerçek IoT)
              ▼
[IoT Simulator / Sensor]
    │  POST /update-fill
    ▼
[FastAPI: anomaly_engine.py]
    │  fill_level → 'LOW'/'MEDIUM'/'HIGH'
    │  'HIGH' ise event_log'a yaz
    ▼
PostgreSQL: telemetry + event_log
    │
    ├──▶ [optimization_engine.py]
    │        Mass-Aware rota hesaplama
    │        Greedy karşılaştırması
    │
    ├──▶ [prediction_model.py]
    │        Geçmiş veriden dolma tahmini
    │
    └──▶ [FastAPI GET /bins, GET /routes/*]
              │
              ▼
         React Dashboard
         Leaflet GIS Harita
```

---

## 3. Veri Pipeline Katmanları

EcoHaul, 6 katmanlı bir veri pipeline üzerine inşa edilmiştir. Her katman bir sonrakine veri sağlar ve bağımsız olarak test edilebilir.

### Katman 0 — Ham Veri (Raw Data Layer)

**Kaynak:** Dublin City Council açık veri portalı  
**Dosya:** `data/dcc_public_bin_locations.csv`  
**Boyut:** 3,425 satır  
**Format:** CSV, Irish Transverse Mercator koordinat sistemi (EPSG:2157)

Ham CSV kolonları:

| Kolon | Tip | Örnek | Açıklama |
|---|---|---|---|
| `Bin_ID` | string | `WMS4505` | Benzersiz konteyner kimliği |
| `ELectoral_Area` | string | `MERCHANTS QUAY C` | Dublin seçim bölgesi |
| `Bin_Type` | string | `Cast Iron` | Fiziksel tip (şemaya alınmıyor) |
| `Irish_X` | float | `314303.38` | ITM easting (metre) |
| `Irish_Y` | float | `233302.39` | ITM northing (metre) |

**Kritik Not:** `Irish_X` ve `Irish_Y` kolonları WGS84 (latitude/longitude) değil; Irish Transverse Mercator (ITM, EPSG:2157) koordinat sistemidir. Leaflet.js WGS84 gerektirir; bu dönüşüm pipeline'ın ilk adımıdır.

### Katman 1 — Dönüşüm ve Yükleme (Ingestion & Transform Layer)

**Sorumlu Modül:** `backend/scripts/seed_dublin.py`  
**Teknoloji:** Python, pandas, pyproj, Motor (async MongoDB driver)

Bu katman şu dönüşümleri gerçekleştirir:

```
Irish Grid (EPSG:2157)           WGS84 (EPSG:4326)
(Irish_X, Irish_Y)    ─────▶     (longitude, latitude)
(314303.38, 233302.39) ─────▶    (-6.2697, 53.3418)
```

Dönüşüm için `pyproj.Transformer.from_crs("EPSG:2157", "EPSG:4326", always_xy=True)` kullanılır.

Her kayıt için üretilen veri:
- `bin_id` ← CSV `Bin_ID`
- `location` ← GeoJSON Point `{"type": "Point", "coordinates": [lon, lat]}`
- `region` ← CSV `ELectoral_Area`
- `is_active` ← `True` (sabit)
- `fill_level` ← `"LOW"` (başlangıç seed değeri)

`Bin_Type` bu katmanda **bilerek düşürülür** — şema bunu saklamaz.

### Katman 2 — Depolama (Storage Layer)

**Hibrit veri tabanı mimarisi:** statik ve dinamik veri farklı sistemlerde tutulur.

```
MongoDB                          PostgreSQL
────────────────────────         ────────────────────────────────
containers (collection)          telemetry (table)
  bin_id                           id, bin_id
  location (GeoJSON)               fill_level (enum)
  region                           status
  is_active           ◀──join──▶   recorded_at
                                 
                                 event_log (table)
                                   id, bin_id
                                   event_type
                                   detail (JSONB)
                                   created_at
```

**Neden bu ayrım?**

MongoDB'nin GeoJSON ve `$near`, `$geoWithin` gibi coğrafi sorgu operatörleri statik lokasyon verisi için idealdir. Rota hesaplama sırasında "X km yarıçapındaki tüm aktif bin'ler" gibi sorgular milisaniyelerde döner.

PostgreSQL'in ACID garantisi ve güçlü zaman serisi yetenekleri anlık telemetri ve olay logları için uygundur. Geçmiş veriden ML modeli eğitmek için SQL aggregation'ları (GROUP BY, WINDOW FUNCTIONS) hızlı ve okunabilirdir.

### Katman 3 — İşleme (Processing Layer)

**Sorumlu Modüller:** `backend/api/anomaly_engine.py`, `backend/api/heartbeat_manager.py`

Bu katman ham sensör verisini anlamlı olaylara dönüştürür:

**Anomali Tespiti:**
- `fill_level = 'HIGH'` → `status = 'ANOMALY'` + `event_log` kaydı
- Faz 2'de: Beklenmedik ani dolma (normal akış: LOW → MEDIUM → HIGH; tek seferde LOW → HIGH = şüpheli boşaltım tespiti)

**Heartbeat Yönetimi:**
- Sensör her N dakikada bir `POST /heartbeat` atar
- MongoDB'de `is_active = True` güncellenir
- Heartbeat tabloya **yazılmaz** — `telemetry.recorded_at` son aktivite zamanı olarak kullanılır
- Faz 2'de: Belirli süre heartbeat gelmeyen bin'ler için `is_active = False` set eden cron job

### Katman 4 — Optimizasyon (Optimization Layer)

**Sorumlu Modül:** `backend/services/optimization_engine.py`

Faz 3'te devreye girer. İki algoritma paralel çalışır:

**EcoHaul Algoritması (Mass-Aware):**
Her rota adımında maliyet fonksiyonu hesaplanır:

$$C_{ij} = (m_{base} + m_{current}) \times d_{ij} \times \alpha_{ij}$$

Araç dolmaya başladıkça uzak noktalara gitmenin maliyeti artar; algoritma otomatik olarak depoya yakın, dolu bin'leri önceliklendirir.

**Greedy Algoritması (Karşılaştırma için):**
Her adımda sadece mesafe minimize edilir — kütle ve yükseklik göz ardı edilir. Aynı bin seti için her iki algoritmanın ürettiği rota KPI olarak karşılaştırılır.

### Katman 5 — Zeka (Intelligence Layer)

**Sorumlu Modüller:** `backend/ai/prediction_model.py`, `backend/ai/copilot.py`

Faz 4'te devreye girer.

**Doluluk Tahmin Modeli:**
PostgreSQL `telemetry` tablosundaki geçmiş veriden her bin için dolma hız profili çıkarılır. Özellikler:
- Günün saati
- Haftanın günü
- Bölge (`region`)
- Son 3 ölçümün trendi

Çıktı: "Bu bin yaklaşık X saat içinde HIGH seviyesine ulaşacak" tahmini.

**LLM Co-Pilot (AI Sürücü Asistanı):**
- Doğal dil input → intent parsing → sistem sorgusu → doğal dil yanıt
- XAI: "Neden bu rotayı seçtik?" sorusuna F = m × a formülünü referans alarak Türkçe açıklama üretme
- Anlık rota revizyonu: Sürücüden "şu sokak kapalı" girdisi gelince optimization_engine yeniden çalışır

### Katman 6 — Sunum (Presentation Layer)

**Sorumlu Modül:** `frontend/`

React + react-leaflet tabanlı dashboard. Veri kaynağı yalnızca FastAPI — frontend hiçbir zaman veritabanına doğrudan bağlanmaz.

---

## 4. Faz 1 — Veri Altyapısı ve Dijital İkiz

**Süre:** Hafta 1  
**Hedef:** Dublin bin verilerini GIS haritasında canlı görmek.

### 4.1 Bu Fazda Yapılacaklar

- [ ] Proje iskeletini ve Docker ortamını oluştur
- [ ] MongoDB şemasını ve index'leri yaz
- [ ] `seed_dublin.py` ile 3,425 Dublin bin'ini dönüştürüp yükle
- [ ] `GET /bins` endpoint'ini yaz
- [ ] React + Leaflet ile Dublin haritasını ayağa kaldır
- [ ] Renkli `CircleMarker` ikonları ve popup sistemi ekle

### 4.2 Koordinat Dönüşümü Detayı

Dublin CSV'deki Irish Grid koordinatları doğrudan kullanılamaz. `pyproj` kütüphanesi ile dönüşüm:

```python
from pyproj import Transformer

transformer = Transformer.from_crs("EPSG:2157", "EPSG:4326", always_xy=True)
lon, lat = transformer.transform(irish_x, irish_y)
```

`always_xy=True` parametresi kritiktir — bazı CRS'lerde koordinat sırası (lat, lon) yerine (lon, lat) olabilir; bu flag her zaman (x=lon, y=lat) sırasını garantiler.

Dublin'in beklenen WGS84 aralığı:
- Latitude: `53.20° – 53.45°`
- Longitude: `-6.45° – -6.05°`

Dönüşüm sonrası tüm noktalar bu aralıkta olmalı — `test_coordinate_bounds.py` bunu doğrular.

### 4.3 Docker Compose Yapılandırması

Bu fazda iki servis:

**mongodb:**
- Image: `mongo:7`
- Port: `27017:27017`
- Named volume: `mongo_data` (konteyner silinse de veri korunur)
- Environment: `MONGO_INITDB_DATABASE=ecohaul`

**backend:**
- Build: `./backend`
- Port: `8000:8000`
- Depends on: mongodb
- Command: `uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload`
- Volume mount: `./backend:/app` (hot-reload için)

PostgreSQL Faz 2'de eklenir — bu fazda karmaşıklık gereksiz.

### 4.4 Faz 1 Test Matrisi

| Test | Dosya | Ne Kontrol Ediyor |
|---|---|---|
| `test_coordinate_bounds` | `tests/test_phase1.py` | Tüm koordinatlar Dublin bbox içinde |
| `test_bin_count` | `tests/test_phase1.py` | MongoDB'de tam 3,425 doküman var |
| `test_geojson_format` | `tests/test_phase1.py` | `location` alanı geçerli GeoJSON Point |
| `test_get_bins_response` | `tests/test_phase1.py` | `GET /bins` 200 döner, liste boş değil |
| `test_fill_level_default` | `tests/test_phase1.py` | Tüm bin'ler başlangıçta `fill_level='LOW'` |

---

## 5. Faz 2 — IoT Katmanı ve Anomali Tespiti

**Süre:** Hafta 2–3  
**Hedef:** Canlı sensör simülasyonu, heartbeat mekanizması ve anomali tespiti.

### 5.1 PostgreSQL Entegrasyonu

Faz 2'de `docker-compose.yml`'e PostgreSQL eklenir:

**postgres:**
- Image: `postgres:16`
- Port: `5432:5432`
- Init script: `database/init.sql` (tablolar otomatik oluşur)
- Named volume: `pg_data`

`telemetry` ve `event_log` tabloları bu fazda aktif hale gelir. `seed_dublin.py` güncellenerek her bin için başlangıç telemetri kaydı da PostgreSQL'e yazılır.

### 5.2 IoT Sensör Simülatörü

**Dosya:** `backend/scripts/iot_simulator.py`

**Çalışma modu:** Async loop, her N saniyede bir çalışır.

Her döngüde:
1. MongoDB'den rastgele K adet aktif bin seç (`K = total_bins * 0.05` — günde tüm bin'ler birkaç kez güncellenir)
2. Her seçili bin için:
   - Mevcut `fill_level`'ı al
   - `random.random() < fill_probability[time_of_day]` ile dolma simüle et
   - Dolma olursa: `LOW → MEDIUM` veya `MEDIUM → HIGH` geçişi yap
   - `POST /update-fill` çağrısı yap
3. Seçilmemiş bin'ler için `POST /heartbeat` at

**fill_probability zaman profili:**

| Zaman Dilimi | Dolma Olasılığı | Açıklama |
|---|---|---|
| 00:00 – 06:00 | 0.02 | Gece, az kullanım |
| 06:00 – 09:00 | 0.15 | Sabah yoğunluğu |
| 09:00 – 18:00 | 0.08 | Gündüz normal akış |
| 18:00 – 22:00 | 0.20 | Akşam yoğunluğu |
| 22:00 – 00:00 | 0.05 | Gece geç |

### 5.3 Anomali Tespiti Detayı

**Dosya:** `backend/api/anomaly_engine.py`

**Anomali 1: Taşan Bin**
- Tetikleyici: `fill_level = 'HIGH'`
- İşlem: `status = 'ANOMALY'`, `event_log`'a `event_type = 'OVERFLOW_RISK'` yazılır
- Dashboard: İkon kırmızı, alert gösterilir

**Anomali 2: Şüpheli Ani Boşaltım**
- Tetikleyici: `HIGH → LOW` geçişi 5 dakikadan kısa sürede gerçekleşirse
- Bu gerçek bir toplama olabilir, ama kayıtsız boşaltım da olabilir
- İşlem: `event_type = 'SUSPICIOUS_EMPTYING'` logu atılır, manuel doğrulama beklenir

**Anomali 3: Offline Bin**
- Tetikleyici: Son `telemetry.recorded_at` değeri eşik süreden (2 saat) eskiyse
- Faz 2 cron job: Her 30 dakikada bir bu sorguyu çalıştırır:
  ```sql
  SELECT bin_id FROM telemetry 
  WHERE recorded_at < NOW() - INTERVAL '2 hours'
  GROUP BY bin_id;
  ```
- İşlem: MongoDB'de `is_active = False` güncellenir
- Dashboard: Gri ikon

### 5.4 Faz 2 Test Matrisi

| Test | Ne Kontrol Ediyor |
|---|---|
| `test_heartbeat_updates_mongo` | Heartbeat sonrası MongoDB `is_active = True` |
| `test_fill_update_postgres` | `POST /update-fill` sonrası PostgreSQL'e kayıt eklendi |
| `test_anomaly_high_fill` | `fill_level = 'HIGH'` → `event_log`'da kayıt var |
| `test_suspicious_emptying` | HIGH→LOW geçişi < 5dk → `SUSPICIOUS_EMPTYING` eventi |
| `test_offline_detection` | 2 saat heartbeat yok → `is_active = False` |
| `test_hybrid_db_sync` | MongoDB `bin_id` kümesi = PostgreSQL `DISTINCT bin_id` kümesi |

---

## 6. Faz 3 — Optimizasyon Motoru

**Süre:** Hafta 4–5  
**Hedef:** Mass-Aware rota algoritmasını kodlamak ve Greedy ile karşılaştırmak.

### 6.1 Algoritma Tasarımı

**Girdi:**
- Aktif bin listesi: `[(bin_id, lat, lon, fill_level)]`
- Araç parametreleri: `m_base` (kg), `fuel_per_km_per_kg` (L/km/kg)
- Depo koordinatı (başlangıç ve bitiş noktası)

**EcoHaul Mass-Aware Algoritması Adımları:**

```
1. Başlangıç: Araç depoda, m_current = 0
2. Tüm HIGH fill_level bin'leri zorunlu ziyaret listesine al
3. MEDIUM fill_level bin'leri isteğe bağlı listeye al (kapasite varsa)
4. Her iterasyonda:
   a. Mevcut konumdan tüm ziyaret edilmemiş bin'lere maliyet hesapla:
      C_ij = (m_base + m_current) × d_ij × α_ij
   b. En düşük maliyetli bin'e git
   c. m_current += bin.estimated_mass
   d. Araç kapasitesi doluysa depoya dön, boşalt, m_current = 0
5. Tüm zorunlu bin'ler ziyaret edilince depoya dön
```

**Yükseklik Katsayısı (α):**
Dublin topoğrafyasında yükseklik farkı `elevation API` (OpenElevation veya Mapbox) ile alınır:

$$\alpha_{ij} = 1 + \max\left(0, \frac{elevation_j - elevation_i}{100}\right) \times 0.15$$

Yokuş aşağı: `α = 1.0` (ceza yok), Yokuş yukarı %10: `α ≈ 1.15`

### 6.2 Greedy Algoritması (Karşılaştırma)

```
1. Başlangıç: Araç depoda
2. Her adımda: Sadece mesafe bazlı en yakın ziyaret edilmemiş HIGH bin'e git
3. Kütle, yükseklik, araç yükü hesaba katılmaz
```

### 6.3 KPI Karşılaştırma Metrikleri

| Metrik | Formül | Birim |
|---|---|---|
| Toplam Yakıt | Σ(m_current × d_i × fuel_coeff) | Litre |
| CO₂ Emisyonu | Toplam Yakıt × 2.68 | kg CO₂ |
| Toplam Mesafe | Σ d_i | km |
| Rota Süresi | Σ (d_i / v_avg) | Dakika |
| Enerji Verimliliği | Toplanan Atık / Toplam Yakıt | kg/Litre |

### 6.4 Endpoint'ler

**`GET /routes/ecohaul`**
- Mass-Aware algoritması çalıştırılır
- Response: sıralı koordinat listesi + maliyet breakdown

**`GET /routes/greedy`**
- Greedy algoritması çalıştırılır
- Response: sıralı koordinat listesi + toplam mesafe

**`GET /routes/compare`**
- Her iki algoritma aynı bin seti için çalıştırılır
- Response: KPI karşılaştırma tablosu

### 6.5 Faz 3 Test Matrisi

| Test | Ne Kontrol Ediyor |
|---|---|
| `test_mass_aware_cost` | Yüklü araç için hesaplanan maliyet > boş araç maliyeti |
| `test_greedy_vs_ecohaul_fuel` | EcoHaul daha az yakıt harcar (deterministik test seti ile) |
| `test_route_covers_all_high_bins` | Rotada tüm HIGH bin'ler ziyaret ediliyor |
| `test_elevation_penalty` | Yokuş yukarı segmentte α > 1.0 |
| `test_depot_return_on_full` | Araç kapasitesi dolunca rota depoya dönüyor |

---

## 7. Faz 4 — Tahminleme ve AI Agent

**Süre:** Hafta 6–7  
**Hedef:** Geçmiş veriden doluluk tahmini yapan model ve LLM tabanlı sürücü asistanı.

### 7.1 Doluluk Tahmin Modeli

**Dosya:** `backend/ai/prediction_model.py`  
**Teknoloji:** scikit-learn (RandomForestClassifier veya LightGBM)

**Eğitim Verisi:**
PostgreSQL `telemetry` tablosundan extract edilir:
```sql
SELECT 
  bin_id,
  fill_level,
  EXTRACT(HOUR FROM recorded_at) AS hour,
  EXTRACT(DOW FROM recorded_at) AS day_of_week,
  recorded_at
FROM telemetry
ORDER BY bin_id, recorded_at;
```

**Feature Engineering:**
- `hour_of_day` (0–23)
- `day_of_week` (0–6)
- `is_weekend` (binary)
- `hours_since_last_empty` (son LOW geçişinden bu yana geçen süre)
- `region_encoded` (one-hot veya label encoding)
- `rolling_fill_rate` (son 3 ölçümün dolma hızı)

**Hedef Değişken:** Şu andan N saat sonra `fill_level = 'HIGH'` olacak mı? (Binary classification)

**Çıktı:** `GET /predictions` → `[{bin_id, predicted_high_in_hours, confidence}]`

### 7.2 LLM Co-Pilot

**Dosya:** `backend/ai/copilot.py`  
**Teknoloji:** LLM API (sağlayıcı Faz 4'te netleştirilecek)

**Mimari: RAG-lite (Retrieval-Augmented Generation)**

LLM her sorguda sisteme inject edilen bir "context window" alır:

```
[SYSTEM PROMPT]
Sen EcoHaul AI çöp toplama sisteminin sürücü asistanısın.
Aşağıdaki gerçek zamanlı veri sana verilmiştir:

Mevcut Aktif Bin Sayısı: {total_active}
HIGH Seviye Bin Sayısı: {high_count}
Araç Mevcut Yükü: {current_mass} kg
Önümüzdeki Rota: {next_3_stops}
Günün Saati: {time}

Sürücü soruyor: {user_question}
```

**Desteklenen Intent'ler:**

| Kullanıcı Girdisi | Intent | Sistem Aksiyonu |
|---|---|---|
| "Neden bu yola gidiyoruz?" | `EXPLAIN_ROUTE` | XAI: maliyet hesabını açıkla |
| "Şu sokak kapalı" | `ROAD_BLOCKED` | Rotayı o segmenti çıkararak yeniden hesapla |
| "Kaç tane dolu bin var?" | `STATUS_QUERY` | `GET /bins` sorgula, sayı döndür |
| "Bugün ne kadar yakıt kullandık?" | `KPI_QUERY` | PostgreSQL'den günlük maliyet hesapla |
| "En yakın boşaltma istasyonu nerede?" | `FACILITY_QUERY` | GIS sorgusu |

**XAI Açıklama Örneği:**
```
"Bu rotada önce Ballybough bölgesine gidiyoruz çünkü: 
  1. İki HIGH seviye bin var — acil toplama gerekiyor.
  2. Araç şu an boş (0 kg yük), bu yüzden uzağa gitmenin 
     enerji maliyeti düşük. F = m × a formülüne göre 
     156 kg yüklü araçla bu mesafeye gitmek şu ankinden 
     %23 daha pahalı olurdu.
  3. Bölge yüksekte, sizi boşken oraya göndermek 
     doluyken gitmekten 340 kcal enerji tasarrufu sağlar."
```

---

## 8. Faz 5 — Dashboard ve Demo

**Süre:** Hafta 8–9  
**Hedef:** Tam işlevsel KPI paneli, canlı simülasyon ve final demo.

### 8.1 Dashboard Bileşenleri

**KPI Kartları (üst bar):**
- Toplam Aktif Bin
- HIGH Seviye Bin Sayısı (kırmızı badge)
- Bugün Toplanan Atık (kg)
- EcoHaul vs Greedy: Yakıt Tasarrufu (%)
- CO₂ Tasarrufu (kg)

**GIS Harita (ana panel):**
- Dublin haritası, tüm aktif bin'ler CircleMarker ile
- Renk kodu: LOW=yeşil, MEDIUM=sarı, HIGH=kırmızı, OFFLINE=gri
- Popup: bin_id, region, fill_level, son güncelleme zamanı
- Katmanlar (toggle):
  - [x] EcoHaul Rota (mavi Polyline)
  - [ ] Greedy Rota (kırmızı Polyline)
  - [ ] Sadece HIGH bin'ler
  - [ ] Tahmin katmanı (dolacak bin'ler, turuncu)

**Rota Karşılaştırma Paneli (sağ sidebar):**
```
╔══════════════════════════════════╗
║     ROTA KARŞILAŞTIRMASI         ║
╠═══════════════╦══════════════════╣
║               ║ EcoHaul │ Greedy ║
╠═══════════════╬═════════╪════════╣
║ Toplam Mesafe ║  42.3km │ 51.7km ║
║ Tahmini Yakıt ║  18.2L  │ 24.8L  ║
║ CO₂ Emisyonu  ║  48.8kg │ 66.5kg ║
║ Rota Süresi   ║  2.3sa  │ 2.9sa  ║
║ Enerji Veriml ║ 11.2    │  8.1   ║
╚═════════════════════════╧════════╝
        EcoHaul %26.6 daha verimli ✓
```

**AI Co-Pilot Chat (alt panel):**
- Gerçek zamanlı chat arayüzü
- Sürücü mesaj gönderir, Co-Pilot yanıtlar
- Yanıtta formül veya sayı varsa vurgulu gösterilir

### 8.2 Canlı Demo Simülasyonu

**DemoSimulator** bileşeni:
- "Simülasyonu Başlat" butonu
- Her 3 saniyede rastgele bin'ler güncellenir
- Bir bin HIGH'a ulaşınca haritada kırmızı flash animasyonu
- Co-Pilot otomatik uyarı üretir: *"BIN-4523 taşmak üzere, rotanıza eklendi."*
- "Canlı Yeniden Rotalama" butonu: tüm mevcut HIGH bin'ler için optimize rota hesaplanır

---

## 9. Veritabanı Şemaları (Tam)

### 9.1 MongoDB — `containers` Collection

```json
{
  "_id": "ObjectId(...)",
  "bin_id": "WMS4505",
  "location": {
    "type": "Point",
    "coordinates": [-6.2697, 53.3418]
  },
  "region": "MERCHANTS QUAY C",
  "is_active": true,
  "fill_level": "LOW"
}
```

**Index'ler:**
```javascript
db.containers.createIndex({ "location": "2dsphere" })          // GIS sorguları
db.containers.createIndex({ "bin_id": 1 }, { unique: true })   // ID lookup
db.containers.createIndex({ "region": 1 })                     // Bölge filtreleme
db.containers.createIndex({ "fill_level": 1 })                 // Doluluk filtreleme
```

**GeoJSON Sorgu Örneği:**
```javascript
// 1 km yarıçapında bin'ler (rota hesaplama için)
db.containers.find({
  location: {
    $near: {
      $geometry: { type: "Point", coordinates: [lon, lat] },
      $maxDistance: 1000
    }
  },
  is_active: true
})
```

### 9.2 PostgreSQL — `telemetry` Tablosu

```sql
CREATE TABLE telemetry (
    id           SERIAL PRIMARY KEY,
    bin_id       VARCHAR(20) NOT NULL,
    fill_level   VARCHAR(10) NOT NULL 
                 CHECK (fill_level IN ('LOW', 'MEDIUM', 'HIGH')),
    status       VARCHAR(10) NOT NULL DEFAULT 'OK'
                 CHECK (status IN ('OK', 'ANOMALY', 'OFFLINE')),
    recorded_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_telemetry_bin_id     ON telemetry(bin_id);
CREATE INDEX idx_telemetry_recorded   ON telemetry(recorded_at DESC);
CREATE INDEX idx_telemetry_bin_time   ON telemetry(bin_id, recorded_at DESC);
```

**Kritik Tasarım Kararı:** `telemetry` sadece INSERT alır, UPDATE almaz. Her sensör ölçümü yeni bir satır olarak eklenir. Bu zaman serisi analizini ve ML eğitimini mümkün kılar.

### 9.3 PostgreSQL — `event_log` Tablosu

```sql
CREATE TABLE event_log (
    id          SERIAL PRIMARY KEY,
    bin_id      VARCHAR(20) NOT NULL,
    event_type  VARCHAR(30) NOT NULL,
    detail      JSONB,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- event_type değerleri:
-- 'OVERFLOW_RISK'       → fill_level HIGH'a ulaştı
-- 'SUSPICIOUS_EMPTYING' → HIGH→LOW geçişi < 5 dakika
-- 'BIN_OFFLINE'         → 2 saat heartbeat gelmedi
-- 'ROUTE_BLOCKED'       → Sürücü yol kapalı bildirdi
-- 'ANOMALY_RESOLVED'    → Bin toplandı, status OK'a döndü

CREATE INDEX idx_event_log_bin_id  ON event_log(bin_id);
CREATE INDEX idx_event_log_type    ON event_log(event_type);
CREATE INDEX idx_event_log_created ON event_log(created_at DESC);
```

`detail` JSONB alanı event türüne göre değişken payload tutar:
```json
// OVERFLOW_RISK eventi için:
{ "previous_fill": "MEDIUM", "region": "MERCHANTS QUAY C" }

// ROUTE_BLOCKED için:
{ "street": "O'Connell St", "reported_by": "driver_001", "coords": [-6.26, 53.34] }
```

---

## 10. API Kontratı (Tam)

### 10.1 Base URL

```
http://localhost:8000
```

### 10.2 Endpoint Listesi

#### `GET /bins`

Tüm bin'lerin anlık durumunu döner.

**Query Params:**
- `?region=MERCHANTS+QUAY+C` → Bölge filtresi
- `?fill_level=HIGH` → Sadece belirli seviye
- `?active_only=true` → Sadece aktif bin'ler

**Response:**
```json
[
  {
    "bin_id": "WMS4505",
    "lat": 53.3418,
    "lon": -6.2697,
    "region": "MERCHANTS QUAY C",
    "fill_level": "LOW",
    "is_active": true,
    "recorded_at": "2026-03-09T21:45:00Z"
  }
]
```

---

#### `POST /update-fill`

Sensörden gelen doluluk güncellemesi.

**Request Body:**
```json
{
  "bin_id": "WMS4505",
  "fill_level": "HIGH"
}
```

**Response:**
```json
{
  "bin_id": "WMS4505",
  "fill_level": "HIGH",
  "status": "ANOMALY",
  "anomaly_detected": true,
  "event_id": 1234
}
```

**Hata Durumları:**
- `422 Unprocessable Entity`: `fill_level` enum dışında bir değer (`"FULL"`, `"75"` vb.)
- `404 Not Found`: `bin_id` MongoDB'de yok

---

#### `POST /heartbeat`

Sensörden canlılık sinyali.

**Request Body:**
```json
{ "bin_id": "WMS4505" }
```

**Response:**
```json
{
  "bin_id": "WMS4505",
  "acknowledged": true,
  "timestamp": "2026-03-09T21:45:00Z"
}
```

**Not:** Bu endpoint PostgreSQL'e **yazmaz**. Sadece MongoDB `is_active = True` günceller.

---

#### `GET /routes/greedy`

Nearest-Neighbor (Greedy) algoritması ile rota.

**Query Params:**
- `?depot_lat=53.340&depot_lon=-6.260`
- `?fill_filter=HIGH`

**Response:**
```json
{
  "algorithm": "greedy",
  "route": [
    { "bin_id": "DEPOT",   "lat": 53.340, "lon": -6.260, "order": 0 },
    { "bin_id": "WMS1274", "lat": 53.345, "lon": -6.248, "order": 1 }
  ],
  "metrics": {
    "total_distance_km": 51.7,
    "estimated_duration_min": 174
  }
}
```

---

#### `GET /routes/ecohaul`

Mass-Aware algoritması ile rota. *(Faz 3)*

**Response:** Greedy ile aynı format + enerji metrikleri:
```json
{
  "algorithm": "ecohaul",
  "route": [ ... ],
  "metrics": {
    "total_distance_km": 42.3,
    "estimated_fuel_liters": 18.2,
    "co2_kg": 48.8,
    "energy_efficiency": 11.2
  }
}
```

---

#### `GET /routes/compare`

Her iki algoritmanın KPI karşılaştırması. *(Faz 3)*

**Response:**
```json
{
  "bin_count": 47,
  "ecohaul": { "total_distance_km": 42.3, "estimated_fuel_liters": 18.2, "co2_kg": 48.8 },
  "greedy":  { "total_distance_km": 51.7, "estimated_fuel_liters": 24.8, "co2_kg": 66.5 },
  "savings": {
    "fuel_liters": 6.6,
    "fuel_percent": 26.6,
    "co2_kg": 17.7,
    "distance_km": 9.4
  }
}
```

---

## 11. Frontend Mimari

### 11.1 Bileşen Hiyerarşisi

```
App.jsx
├── Header.jsx                    (proje adı, canlı saat)
├── KPIBar.jsx                    (Faz 5)
│   ├── KPICard.jsx               (Active Bins)
│   ├── KPICard.jsx               (HIGH Level Count)
│   └── KPICard.jsx               (Fuel Saved %)
├── MainLayout.jsx
│   ├── MapView.jsx               ★ Ana component
│   │   ├── BinMarker.jsx         (her bin için CircleMarker)
│   │   ├── GreedyLayer.jsx       (Greedy rota Polyline)
│   │   ├── EcoHaulLayer.jsx      (Faz 3)
│   │   └── PredictionLayer.jsx   (Faz 4)
│   └── Sidebar.jsx               (Faz 5)
│       ├── RouteComparePanel.jsx
│       └── EventLog.jsx
├── DemoSimulator.jsx             (demo kontrol paneli)
└── CoPilotChat.jsx               (Faz 4)
```

### 11.2 State Yönetimi

Faz 1–3 için React `useState` + `useEffect` yeterlidir. Faz 4–5'te karmaşıklık artarsa **Zustand** (lightweight) kullanılır.

**Global State Yapısı:**
```javascript
{
  bins: [],
  selectedBin: null,
  activeLayers: {
    greedy: false,
    ecohaul: false,
    predictions: false
  },
  kpi: {
    activeCount: 0,
    highCount: 0,
    fuelSaved: 0
  },
  simulatorRunning: false
}
```

### 11.3 Harita Performans Notları

3,425 nokta için `Marker` değil `CircleMarker` kullanılır. `Marker` her nokta için DOM elementi oluşturur; `CircleMarker` Canvas renderer üzerinde çalışır ve 10K+ nokta için dahi akıcıdır.

Faz 5'te ihtiyaç duyulursa `react-leaflet-markercluster` ile yakın bin'ler cluster'lanır.

**Veri Yenileme Stratejisi:**
- Faz 1: Manuel refresh veya sayfa yenileme
- Faz 2: `setInterval` ile her 5 saniyede `GET /bins` (polling)
- Faz 5 (opsiyonel): WebSocket ile real-time push

---

## 12. Test Stratejisi

### 12.1 Test Piramidi

```
        /▲\
       / E2E \          ← Faz 5: Tarayıcıda demo akışı (Playwright)
      /────────\
     / Integration \    ← API + DB birlikte (pytest + httpx)
    /──────────────\
   /   Unit Tests   \   ← Her modül izole (pytest)
  /──────────────────\
```

### 12.2 Backend Test Konfigürasyonu

`pytest` + `httpx` (async test client) + `pytest-asyncio`

Test veritabanı: `docker-compose.test.yml` ile ayrı MongoDB/PostgreSQL instance. Test sonunda otomatik temizlenir.

### 12.3 Faz Bazında Tam Test Listesi

**Faz 1:**
- `test_coordinate_bounds` — Tüm koordinatlar Dublin WGS84 bbox içinde
- `test_bin_count` — MongoDB'de tam 3,425 doküman
- `test_geojson_valid` — `location.type == "Point"`, koordinatlar float
- `test_get_bins_200` — `GET /bins` 200 OK döner, liste boş değil
- `test_fill_level_default_low` — Tüm bin'ler başlangıçta `fill_level='LOW'`

**Faz 2:**
- `test_heartbeat_activates_bin` — Heartbeat → MongoDB `is_active = True`
- `test_invalid_fill_level_422` — `"FULL"` gönder → 422 al
- `test_high_fill_creates_event` — HIGH güncelleme → `event_log`'da kayıt
- `test_hybrid_sync` — MongoDB bin_id kümesi = PostgreSQL bin_id kümesi
- `test_offline_after_timeout` — 2 saat sessiz → `is_active = False`

**Faz 3:**
- `test_mass_cost_increases_with_load` — Yüklü araç > boş araç maliyeti
- `test_ecohaul_beats_greedy` — Deterministik test seti: EcoHaul daha az yakıt
- `test_route_completeness` — Tüm HIGH bin'ler rotada yer alıyor
- `test_elevation_alpha` — Yüksek segment α > 1.0
- `test_depot_return_on_full` — Araç dolu → depoya dönüş rotada

**Faz 4:**
- `test_prediction_model_accuracy` — Test setinde ≥ %75 doğruluk
- `test_copilot_intent_explain` — "Neden?" sorusu → `EXPLAIN_ROUTE` intent
- `test_copilot_road_blocked` — "Yol kapalı" → rota yeniden hesaplanıyor

---

## 13. KPI Metrikleri ve Başarı Kriterleri

### 13.1 Sistem Başarı Kriterleri

| KPI | Hedef | Ölçüm Yöntemi |
|---|---|---|
| EcoHaul vs Greedy Yakıt Tasarrufu | ≥ %15 | `GET /routes/compare` |
| EcoHaul vs Greedy CO₂ Tasarrufu | ≥ %15 | Yakıt × 2.68 |
| Anomali Tespit Doğruluğu | ≥ %90 | Test seti precision |
| Doluluk Tahmin Doğruluğu | ≥ %75 | ML model accuracy (Faz 4) |
| API Yanıt Süresi `GET /bins` | ≤ 200ms | Locust / k6 yük testi |
| Harita Yükleme Süresi | ≤ 2 saniye | Browser DevTools |

### 13.2 Final Demo Senaryosu

```
1. Sistem başlatılır — haritada 3,425 Dublin bin'i görülür (hepsi yeşil)
2. DemoSimulator başlatılır — bin'ler dolmaya başlar
3. 10 bin HIGH'a ulaşır — haritada kırmızı uyarılar, alert paneli güncellenir
4. "EcoHaul Rotası Hesapla" tıklanır — mavi rota çizilir
5. "Greedy Rotası Göster" tıklanır — kırmızı rota çizilir
6. KPI karşılaştırma paneli: "EcoHaul %26 daha az yakıt kullandı"
7. Co-Pilot: "Neden bu rotaya gidiyoruz?" sorusu sorulur
8. XAI açıklaması: F = m × a formülü referanslı Türkçe yanıt ekranda
```

---

## 14. Teknoloji Yığını

| Katman | Teknoloji | Versiyon | Amaç |
|---|---|---|---|
| **Veri Dönüşüm** | pyproj | 3.6+ | Irish Grid → WGS84 koordinat dönüşümü |
| **Veri İşleme** | pandas | 2.x | CSV okuma ve transform |
| **API Framework** | FastAPI | 0.110+ | REST API gateway |
| **ASGI Server** | Uvicorn | 0.27+ | FastAPI runtime |
| **Async Mongo Driver** | Motor | 3.x | MongoDB async client |
| **Async PG Driver** | asyncpg | 0.29+ | PostgreSQL async client |
| **NoSQL DB** | MongoDB | 7 | Statik konteyner verisi + GIS index |
| **SQL DB** | PostgreSQL | 16 | Telemetri zaman serisi + event log |
| **Container** | Docker Compose | v2 | Ortam yönetimi |
| **Frontend Build** | Vite | 5.x | React dev server + build |
| **UI Framework** | React | 18 | Component tabanlı UI |
| **Harita** | react-leaflet | 4.x | GIS harita, CircleMarker, Polyline |
| **HTTP Client** | axios | 1.x | API çağrıları |
| **Test** | pytest + httpx | — | Backend unit + integration testleri |
| **ML** | scikit-learn | 1.4+ | Doluluk tahmini (Faz 4) |
| **LLM** | TBD | — | Co-Pilot sürücü asistanı (Faz 4) |

---

## 15. Proje Dosya Yapısı (Tam)

```
eco_haul/
│
├── docker-compose.yml              # MongoDB + PostgreSQL + Backend servisleri
├── docker-compose.test.yml         # Test ortamı (ayrı portlar, izole DB)
├── .env                            # Gerçek credentials (.gitignore'da)
├── .env.example                    # Template — takıma paylaşılır
├── requirements.txt                # Python bağımlılıkları
├── .gitignore
│
├── data/
│   └── dcc_public_bin_locations.csv    # Ham Dublin verisi (3,425 bin)
│
├── backend/
│   ├── Dockerfile
│   │
│   ├── api/
│   │   ├── __init__.py
│   │   ├── main.py                 # FastAPI app, tüm route'lar, CORS
│   │   ├── anomaly_engine.py       # Anomali tespit mantığı (Faz 2)
│   │   └── heartbeat_manager.py   # Heartbeat ve offline tespiti (Faz 2)
│   │
│   ├── database/
│   │   ├── __init__.py
│   │   ├── schema.py               # Motor client, collection ref, index init
│   │   └── init.sql                # PostgreSQL CREATE TABLE script
│   │
│   ├── scripts/
│   │   ├── seed_dublin.py          # Dublin CSV → WGS84 dönüşüm → MongoDB seed
│   │   └── iot_simulator.py        # Sensör simülasyonu async loop (Faz 2)
│   │
│   ├── services/
│   │   ├── optimization_engine.py  # Mass-Aware + Greedy algoritmaları (Faz 3)
│   │   └── kpi_calculator.py       # KPI karşılaştırma hesaplamaları (Faz 3)
│   │
│   └── ai/
│       ├── prediction_model.py     # Doluluk tahmin ML modeli (Faz 4)
│       ├── copilot.py              # LLM Co-Pilot entegrasyonu (Faz 4)
│       └── xai_explainer.py        # Rota kararı açıklama / XAI (Faz 4)
│
├── frontend/
│   ├── index.html
│   ├── package.json
│   ├── vite.config.js
│   │
│   └── src/
│       ├── main.jsx
│       ├── App.jsx
│       │
│       ├── components/
│       │   ├── MapView.jsx             # Ana harita container (Faz 1)
│       │   ├── BinMarker.jsx           # Renkli CircleMarker + Popup (Faz 1)
│       │   ├── GreedyLayer.jsx         # Greedy rota Polyline (Faz 1)
│       │   ├── EcoHaulLayer.jsx        # Mass-Aware rota Polyline (Faz 3)
│       │   ├── PredictionLayer.jsx     # Tahmin katmanı, turuncu ikonlar (Faz 4)
│       │   ├── KPIBar.jsx              # Üst KPI kartları (Faz 5)
│       │   ├── RouteComparePanel.jsx   # Algoritma karşılaştırma tablosu (Faz 5)
│       │   ├── DemoSimulator.jsx       # Demo kontrol paneli (Faz 2+)
│       │   └── CoPilotChat.jsx         # AI sürücü asistanı chat (Faz 4)
│       │
│       └── services/
│           └── api.js                  # axios instance, tüm API çağrıları merkezi
│
└── tests/
    ├── conftest.py                 # pytest fixtures: test DB, API client, mock data
    ├── test_phase1.py              # Koordinat sınırları, seed, GET /bins
    ├── test_phase2.py              # Heartbeat, anomali tespiti, hybrid DB sync
    ├── test_phase3.py              # Optimizasyon algoritmaları, KPI karşılaştırma
    └── test_phase4.py              # ML model doğruluğu, Co-Pilot intent parsing
```

---

*Bu doküman proje boyunca güncel tutulacaktır. Her faz tamamlandığında ilgili bölümler gerçek implementasyon notları ile güncellenir.*
