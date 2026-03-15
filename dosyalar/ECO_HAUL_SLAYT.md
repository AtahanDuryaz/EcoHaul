---
marp: true
theme: default
paginate: true
backgroundColor: #0f172a
color: #f1f5f9
style: |
  section {
    font-family: 'Segoe UI', sans-serif;
    padding: 40px 60px;
  }
  h1 {
    color: #34d399;
    font-size: 2em;
    border-bottom: 2px solid #34d399;
    padding-bottom: 10px;
  }
  h2 {
    color: #6ee7b7;
    font-size: 1.4em;
  }
  h3 {
    color: #a7f3d0;
    font-size: 1.15em;
  }
  table {
    width: 100%;
    border-collapse: collapse;
    font-size: 0.78em;
  }
  th {
    background-color: #1e3a2f;
    color: #34d399;
    padding: 6px 10px;
    text-align: left;
  }
  td {
    padding: 5px 10px;
    border-bottom: 1px solid #1e293b;
    color: #cbd5e1;
  }
  tr:nth-child(even) td {
    background-color: #0f2030;
  }
  code {
    background-color: #1e293b;
    color: #6ee7b7;
    padding: 2px 6px;
    border-radius: 4px;
    font-size: 0.9em;
  }
  blockquote {
    border-left: 4px solid #34d399;
    background-color: #1e293b;
    padding: 12px 20px;
    margin: 10px 0;
    border-radius: 0 8px 8px 0;
    color: #a7f3d0;
    font-style: normal;
  }
  ul li {
    margin-bottom: 6px;
    color: #cbd5e1;
  }
  .tag {
    background: #1e3a2f;
    color: #34d399;
    padding: 2px 8px;
    border-radius: 12px;
    font-size: 0.8em;
  }
  section.title {
    display: flex;
    flex-direction: column;
    justify-content: center;
    align-items: center;
    text-align: center;
  }
  section.title h1 {
    font-size: 3em;
    border: none;
    margin-bottom: 10px;
  }
  section.title h2 {
    font-size: 1.2em;
    color: #94a3b8;
    font-weight: normal;
    border: none;
  }
---

<!-- _class: title -->

# 🌿 EcoHaul AI

## Yapay Zeka ve IoT Tabanlı Dinamik Atık Yönetim Sistemi

---
**CSE-492 Bitirme Projesi — Mart 2026**

---

## Proje Özeti

EcoHaul AI, şehir çöp toplama süreçlerini **gerçek zamanlı sensör verisi**, **makine öğrenimi tahmini** ve **fizik tabanlı rotalama** ile optimize eden akıllı bir yönetim sistemidir.

> **Temel Yenilik**
> Araç kütlesini yakıt maliyetine dahil eden **Mass-Aware Routing** algoritması — Greedy ve Static Route ile yan yana karşılaştırılır.

### Neden EcoHaul?

| Problem | EcoHaul Çözümü |
|---|---|
| Statik, sabit belediye rotaları | Gerçek zamanlı doluluk tabanlı dinamik rota |
| Araç kütlesi yakıt hesabına dahil değil | $C_{ij} = (m_{base} + m_{current}) \times d_{ij} + P_{stop}$ |
| Sensör arızaları fark edilmiyor | Otomatik anomali tespiti ve bakım listesi |
| Sürücüye bilgi erişimi yok | Text-to-SQL karar destek arayüzü |

---

## Sistem Mimarisi (Pipeline)

```
KATMAN 0   Dublin Open Data CSV  →  3.425 konteyner  →  EPSG:2157
    │
KATMAN 1   EPSG:2157  →  WGS84  →  PostgreSQL + PostGIS
    │
KATMAN 2   containers │ telemetry │ event_log │ road_blocks
    │
KATMAN 3   Median Filter → Enum Sınıflandırma → Anomali Tespiti
    │
    ├── KATMAN 4  Optimizasyon (EcoHaul vs Greedy vs Static)
    ├── KATMAN 5  AI Tahmin + Text-to-SQL Co-Pilot
    └── Google Maps API (Trafik + Yol Durumu)
    │
KATMAN 6   Dashboard (React + Leaflet) — KPI Karşılaştırma
```

> **7 katmanlı pipeline** — Ham CSV'den interaktif harita simülasyonuna

---

## Katman 0–2: Veri Temeli

### Katman 0 — Ham Veri
- **Kaynak:** Dublin City Council Açık Veri Portalı
- **3.425 konteyner** — koordinat, bölge, kimlik
- Format: CSV / EPSG:2157 (Irish Transverse Mercator)

### Katman 1 — Dönüşüm
`pyproj` ile EPSG:2157 → WGS84 (lat/lon) → `asyncpg` ile PostgreSQL'e yükleme

### Katman 2 — Depolama (PostgreSQL + PostGIS)

| Tablo | İçerik |
|---|---|
| `containers` | bin_id, koordinat (POINT), bölge, aktiflik |
| `telemetry` | fill_level (enum), ham_cm, zaman damgası |
| `event_log` | Anomali logları — event_type, JSONB detay |
| `road_blocks` | Manuel / Google Maps yol kapatmaları |

---

## Katman 3: İşleme ve Anomali Tespiti

**Veri işleme zinciri:**
`Ham mesafe (cm)` → **Median Filter** → **Moving Average** → `Enum` → `Anomali kontrolü`

### Doluluk Enum Sınıflandırması

| Ham Ölçüm | Enum | Açıklama |
|---|---|---|
| 0 – 60 cm | `EMPTY` | Boş — rota dışı |
| 60 – 90 cm | `FULL` | Toplanmalı |
| 90+ cm | `CRITICAL` | Taşma riski — acil |

### Implicit Heartbeat
Ayrı `/heartbeat` sinyali yok — her `POST /update-fill` çağrısı otomatik canlılık sinyali olarak kabul edilir. **2 saat** veri gelmezse → `BIN_OFFLINE`

---

## Katman 3: Anomali Türleri

| Anomali | Tetikleyici | Kod |
|---|---|---|
| Taşma riski | fill_level → CRITICAL | `OVERFLOW_RISK` |
| Yetkisiz boşaltım | Rota dışında HIGH→EMPTY | `SUSPICIOUS_EMPTYING` |
| Offline sensör | 2 saat Implicit Heartbeat yok | `BIN_OFFLINE` |
| Rota dışı boşaltım | GPS mesafesi > 20 metre **veya** rota segmenti eşleşmiyor | `UNAUTHORIZED_EMPTY` |
| Anormal dolum hızı | Habit Tracking'den %X sapma (karton kutu vb.) | `FILL_ANOMALY` |
| Sensör sağlık hatası | 24 saat boyunca veri değişmedi — sensör donmuş/bozuk | `SENSOR_FIXED_VALUE_ERROR` |

> `SENSOR_FIXED_VALUE_ERROR` → Konteyner rotadan çıkarılır, `maintenance_queue`'ya eklenir

---

## Katman 4: Mass-Aware Rotalama

### Maliyet Fonksiyonu

$$C_{ij} = (m_{base} + m_{current}) \times d_{ij} + P_{stop}$$

| Terim | Açıklama |
|---|---|
| $m_{base}$ | Kamyonun boş ağırlığı (sabit) |
| $m_{current}$ | Şu ana kadar toplanan çöp kütlesi (artar) |
| $d_{ij}$ | $i$ → $j$ mesafesi |
| $P_{stop}$ | Rölanti + fren + ivme kaynaklı sabit durma maliyeti |

> Kamyon doldukça $m_{current}$ artar → sistem **depoya yakın** noktaları tercih eder.
> $P_{stop}$, az dolu kutularda "durmak mı, geçmek mi?" kararını maliyet olarak modeller.

---

## Katman 4: Karşılaştırma Modelleri

| Model | Kütle | Trafik | Idling | Dinamik Rota |
|---|---|---|---|---|
| **Static Route** (Belediye) | ❌ | ❌ | ❌ | ❌ |
| **Greedy** | ❌ | ❌ | ❌ | ✅ |
| **EcoHaul** | ✅ | ✅ | ✅ | ✅ |

### Manuel Yol Kapatma
Operatör haritadan segmenti kapatır → `road_blocks` tablosuna yazılır → optimizasyon motoru bu segmenti rota hesabından anında dışlar.

> **Hedef:** EcoHaul, Greedy'ye kıyasla ≥ **%15 yakıt** ve ≥ **%15 CO₂** tasarrufu

---

## Katman 5: Yapay Zeka

### Doluluk Tahmin Modeli
`scikit-learn` — Random Forest / LightGBM

| Özellik | Açıklama |
|---|---|
| `hour_of_day` | Günün saati (0–23) |
| `day_of_week` | Haftanın günü (0–6) |
| `is_weekend` | Hafta sonu ikili değişken |
| `hours_since_last_empty` | Son boşaltımdan bu yana süre |
| `rolling_fill_rate` | Son 3 ölçümün dolma hız trendi |

**Çıktı:** *"Bu konteyner yaklaşık X saat içinde CRITICAL'e ulaşacak"*

### AI Co-Pilot — Text-to-SQL
Sürücü operasyonel sorgu yazar → sistem SQL'e çevirir → yapılandırılmış yanıt döner.
*"En yakın kritik konteyner nerede?"* | *"Bu bölgede kaç FULL kutu var?"*

---

## Katman 6: Dashboard

### İkili Harita Simülasyonu

| Harita A — Greedy | Harita B — EcoHaul |
|---|---|
| Kırmızı rota çizgisi | Mavi rota çizgisi |
| Aynı konteyner seti | Aynı konteyner seti |
| Kütle & trafik yok | Mass-Aware + trafik |

### KPI Karşılaştırma Paneli

| KPI | Static Route | Greedy | EcoHaul |
|---|---|---|---|
| Toplam Mesafe (km) | — | — | — |
| Tahmini Yakıt (L) | — | — | — |
| CO₂ Emisyonu (kg) | — | — | — |
| Rota Süresi (dk) | — | — | — |
| Enerji Verimliliği (Ton-km/yakıt) | — | — | — |

---

## IoT Katmanı: ESP32 + HC-SR04

**3 fiziksel modül** — gerçek çöp kutularına entegre  
**3.422 sanal konteyner** — `iot_simulator.py` ile simüle edildi

### Olay Tabanlı Örnekleme (Deep Sleep)

```
[Saat başı uyanma]
  → HC-SR04: 30 sn / 10 ölçüm
  → Median Filter (gürültü eleme — doğrudan cihazda)
  → Enum dönüşümü (EMPTY / FULL / CRITICAL)
  → POST /update-fill  ←  Implicit Heartbeat
  → Deep Sleep  (sonraki saate kadar)
```

> Sürekli ölçüm yok → **pil ömrü maksimize edilir**

---

## IoT Katmanı: Hata Toleransı

| Mekanizma | Davranış |
|---|---|
| **Exponential Backoff** | HTTP 200 gelmezse 3 deneme: 1 sn → 2 sn → 4 sn |
| **SPIFFS / LittleFS** | Tüm denemeler başarısız → veri flash belleğe yazar, bağlantıda gönderir |
| **Hardware WDT** | Bağlantı 20 sn aşarsa cihaz otomatik reset → operasyon devam eder |
| **Edge Processing** | Median Filter doğrudan ESP32'de → backend yükü azalır |

---

## Başarı Kriterleri Özeti

| Kriter | Hedef |
|---|---|
| Yakıt Tasarrufu (EcoHaul vs Greedy) | ≥ %15 |
| CO₂ Emisyonu Azaltımı | ≥ %15 |
| Anomali Tespit Doğruluğu | ≥ %90 |
| Yanlış Pozitif Oranı | ≤ %10 |
| Doluluk Tahmin Doğruluğu | ≥ %75 |
| Co-Pilot Intent Doğruluğu | ≥ %85 |
| API Yanıt Süresi | ≤ 200 ms |
| Harita Yükleme Süresi | ≤ 2 saniye |
| IoT Fiziksel Modül Uptime | ≥ %95 |

---

## Genel Teknoloji Yığını

| Katman | Teknoloji |
|---|---|
| **Backend** | Python, FastAPI, Uvicorn |
| **Veritabanı** | PostgreSQL 16, PostGIS |
| **IoT Fiziksel** | ESP32, HC-SR04, MicroPython |
| **IoT Simülasyon** | Python `iot_simulator.py` |
| **Veri İşleme** | pandas, pyproj |
| **Harita & Trafik** | Google Maps Directions API, react-leaflet |
| **Yapay Zeka** | scikit-learn (Random Forest / LightGBM), LLM API |
| **Frontend** | React 18, Vite 5, react-leaflet 4, Zustand |
| **Test** | pytest, httpx, pytest-asyncio |

