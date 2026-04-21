# EcoHaul — Week 1 Implementation Report (MVP Harita)

**Tarih:** 15 Mart 2026  
**Kapsam:** Sadece Hafta 1 (dataset pipeline + backend API + frontend harita)

---

## 1) Hedef (Planlanan)

Bu hafta hedefi:
- Dataseti temizlemek
- Koordinatları WGS84 formatına dönüştürmek
- Dublin sınır doğrulaması yapmak
- PostgreSQL + PostGIS tablosuna yükleme hattını kurmak
- FastAPI ile bins endpointlerini açmak
- React + Leaflet dashboardda tüm kutuları gri marker olarak göstermek
- Popup içinde: `Bin ID`, `State`, `Region`, `Last Emptied`

---

## 2) Yapılan İşler (Gerçekleşen)

### 2.1 Veri Pipeline

#### A) Data Cleaning
**Dosya:** `backend/scripts/clean_bins.py`

Yapılanlar:
- `bin_id` normalize edildi (karışabilecek karakter dönüşümleri: `O->0`, `I/L->1`, `S->5`, `B/E->8`)
- Boş `bin_id` kayıtları filtrelendi
- `bin_id` duplicate kayıtlar filtrelendi
- Geçersiz koordinat parse hataları filtrelendi
- Çıktı üretildi: `backend/data/clean_bins.csv`
- Rapor üretildi: `backend/data/cleaning_report.json`

**Rapor özeti:**
- `source_rows`: **3424**
- `kept_rows`: **3421**
- `dropped_duplicate_bin_id`: **3**
- diğer drop kalemleri: **0**

> Not: Plan hedefi 3425 idi; mevcut kaynak CSV satır sayısı 3424 görünüyor ve duplicate temizliği sonrası 3421 kalıyor.

#### B) Coordinate Transform (EPSG -> WGS84)
**Dosya:** `backend/scripts/transform_bins_to_wgs84.py`

Yapılanlar:
- `clean_bins.csv` verisi işlendi
- WGS84 dönüşümü için aday CRS denemesi eklendi: `EPSG:2157`, `EPSG:29903`, `EPSG:29902`
- Dublin bbox uyum skoruna göre en iyi CRS otomatik seçildi
- `latitude`, `longitude` alanları üretildi
- `status="OFFLINE"`, `last_emptied_at=null` alanları eklendi
- Çıktı üretildi: `backend/data/bins_wgs84.csv`
- Rapor üretildi: `backend/data/transform_report.json`

**Rapor özeti:**
- `total_records`: **3421**
- `selected_source_crs`: **EPSG:29903**
- lat aralığı: **53.3028644 – 53.4061681**
- lon aralığı: **-6.3772698 – -6.1447397**

#### C) Dublin Boundary Validation
**Dosya:** `backend/scripts/validate_bins.py`

Yapılanlar:
- Bounding box kontrolü uygulandı
  - lat: `53.20 – 53.45`
  - lon: `-6.45 – -6.05`
- Geçersiz satırlar raporlandı
- Çıktı: `backend/data/bins_validation_report.json`

**Rapor özeti:**
- `total_records`: **3421**
- `valid_in_dublin`: **3421**
- `invalid`: **0**

---

### 2.2 Veritabanı (PostgreSQL + PostGIS)

#### A) Şema
**Dosya:** `backend/database/init.sql`

Oluşturulan yapı:
- `bins` tablosu
  - `bin_id` (unique)
  - `latitude`, `longitude`
  - `status` (default `OFFLINE`)
  - `region` (TEXT)
  - `last_emptied_at` (nullable)
  - `geom` (`GEOGRAPHY(Point,4326)`)
- İndeksler:
  - `status`
  - `region`
  - `geom` (GIST)

#### B) DB Load Script
**Dosya:** `backend/scripts/load_bins_to_db.py`

Yapılanlar:
- `bins_wgs84.csv` kayıtları DB’ye upsert ediliyor
- `geom` alanı `ST_SetSRID(ST_MakePoint(lon, lat),4326)::geography` ile dolduruluyor
- `backend/.env` veya `backend/.env.example` üzerinden `DATABASE_URL` okunuyor

---

### 2.3 Backend API (FastAPI)

#### A) API Girişi
**Dosya:** `backend/app/main.py`

Endpointler:
- `GET /health` -> `{ "status": "ok" }`
- `GET /api/bins` -> bins listesi
- `GET /api/bins/summary` -> toplam/offline/region dağılımı

#### B) Service Layer
**Dosya:** `backend/app/services/bins_service.py`

Yapılanlar:
- DB’den sorgu yapılıyor
- DB bağlantı/sorgu hatasında fallback olarak `backend/data/bins_wgs84.csv` okunuyor
- Böylece Postgres kapalı olsa bile demo/harita veri alabiliyor

#### C) Şema/Model Çıktısı
**Dosya:** `backend/app/schemas.py`

`/api/bins` response alanları:
- `bin_id`
- `lat`
- `lon`
- `status`
- `region`
- `last_emptied_at`

`/api/bins/summary` response alanları:
- `total_bins`
- `offline_bins`
- `regions`

---

### 2.4 Frontend Dashboard (React + Leaflet)

#### A) App ve Data Fetch
**Dosya:** `frontend/src/App.jsx`

Yapılanlar:
- İlk yüklemede `/api/bins` ve `/api/bins/summary` paralel çekiliyor
- Loading ve hata durumu yönetimi var
- Header’da toplam ve offline sayısı gösteriliyor

#### B) Harita
**Dosya:** `frontend/src/components/MapView.jsx`

Yapılanlar:
- Dublin merkez: `53.3498, -6.2603`
- OpenStreetMap tile layer
- Tüm kayıtlar marker olarak çiziliyor
- Marker rengi gri (`status=OFFLINE`)
- Hover’da popup aç/kapa davranışı var
- Performans için `react-leaflet-cluster` eklendi

#### C) Popup
**Dosya:** `frontend/src/components/BinPopup.jsx`

Gösterilen alanlar:
- Bin ID
- State (`status`)
- Region
- Last Emptied (`null` ise `Belirlenecek`)

#### D) API Client
**Dosya:** `frontend/src/services/api.js`

Yapılanlar:
- `axios` base URL: `VITE_API_URL` veya varsayılan `http://localhost:8000`

#### E) Build Doğrulaması
- `npm run build` komutu başarılı (Exit Code: 0)

---

## 3) Kullanılan Teknolojiler

### Backend
- FastAPI
- SQLAlchemy
- Psycopg (PostgreSQL driver)
- Pandas
- GeoPandas
- PyProj
- Python-Dotenv

### Frontend
- React 18
- Vite
- Leaflet
- React-Leaflet
- React-Leaflet-Cluster
- Axios

---

## 4) Çalıştırma Akışı (Week 1)

### 4.1 Backend
```powershell
cd backend
../.venv/Scripts/python.exe -m pip install -r requirements.txt
cd ..
.venv/Scripts/python.exe backend/scripts/clean_bins.py
.venv/Scripts/python.exe backend/scripts/transform_bins_to_wgs84.py
.venv/Scripts/python.exe backend/scripts/validate_bins.py
# DB kullanacaksan:
.venv/Scripts/python.exe backend/scripts/load_bins_to_db.py
cd backend
../.venv/Scripts/python.exe -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### 4.2 Frontend
```powershell
cd frontend
npm install
npm run dev
```

---

## 5) Week 1 Kabul Kontrolü — Gerçek Durum

- [x] Dataset temizleme scripti var ve rapor üretiyor
- [x] WGS84 dönüşüm scripti var ve çalışıyor
- [x] Dublin doğrulama raporu var (`invalid = 0`)
- [x] FastAPI endpointleri çalışıyor
- [x] Harita dashboard ve popup alanları çalışıyor
- [x] Marker cluster eklendi
- [x] Frontend build başarılı

**Sayısal durum (mevcut veri ile):**
- Toplam işlenen kayıt: **3421**
- Dublin içinde geçerli: **3421**
- Geçersiz: **0**
- Offline durum: **tüm kayıtlar OFFLINE**

---

## 6) Plan-Hedef Farkı (Week 1)

Planlanan hedefte 3425 kayıt geçiyordu; mevcut kaynak dosya + temizleme sonrası aktif kayıt sayısı 3421 oldu.

Muhtemel nedenler:
1. Kaynak CSV satır sayısı 3424 (beklenen 3425 değil)
2. `bin_id` duplicate temizliğinde 3 kayıt düşüyor

Bu fark dokümante edildi; pipeline tutarlı şekilde çalışıyor ve Dublin validasyonu %100.

---

## 7) Sonuç

Week 1 MVP, kapsam içindeki hedefleri teknik olarak karşılıyor:
- Veri pipeline kurulmuş durumda
- API ve frontend entegre çalışıyor
- Harita üstünde gri marker + popup bilgileri görüntüleniyor
- DB varsa PostGIS’ten, yoksa CSV fallback ile sistem çalışabiliyor

Hafta 2’ye geçiş için temel altyapı hazır.
