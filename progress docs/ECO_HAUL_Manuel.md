# EcoHaul — Teknik Referans Kılavuzu

> Dublin şehri için akıllı atık toplama optimizasyon simülasyonu.
> 3.424 gerçek çöp kutusu verisi, iki paralel dünya (DPET vs. sabit rota), canlı KPI karşılaştırması.

---

## İçindekiler

1. [Proje Genel Bakış](#1-proje-genel-bakış)
2. [Mimari Harita](#2-mimari-harita)
3. [Veri Seti ve Başlangıç Konfigürasyonu](#3-veri-seti-ve-başlangıç-konfigürasyonu)
4. [Environment Modülü — Kentsel Atık Dinamikleri](#4-environment-modülü--kentsel-atık-dinamikleri)
5. [FillPredictor — Coğrafi Zonelama ve ETF Öğrenmesi](#5-fillpredictor--coğrafi-zonelama-ve-etf-öğrenmesi)
6. [DPET Algoritması — 6 Katmanlı Dispatch](#6-dpet-algoritması--6-katmanlı-dispatch)
7. [SimulationEngine — Ana Simülasyon Motoru](#7-simulationengine--ana-simülasyon-motoru)
8. [Sabit Rota Dünyası (Fixed World)](#8-sabit-rota-dünyası-fixed-world)
9. [Anomali Sistemi](#9-anomali-sistemi)
10. [API ve Servis Katmanı](#10-api-ve-servis-katmanı)
11. [Frontend Mimarisi](#11-frontend-mimarisi)
12. [KPI Kataloğu — Her Metrik Detaylı](#12-kpi-kataloğu--her-metrik-detaylı)
13. [Parametre Referansı — Tüm Sabitler](#13-parametre-referansı--tüm-sabitler)
14. [Simülasyon Akış Diyagramı](#14-simülasyon-akış-diyagramı)
15. [Karar Gerekçeleri](#15-karar-gerekçeleri)

---

## 1. Proje Genel Bakış

EcoHaul, Dublin Belediyesi (DCC) açık veri setindeki 3.424 çöp kutusunu kullanarak iki farklı atık toplama stratejisini **aynı anda** simüle eder ve karşılaştırır:

| Dünya | Strateji | Açıklama |
|-------|----------|----------|
| **algo** | DPET (Dynamic Priority & Efficient Truck) | ETF, trafik, kapasite ve yoğunluk bazlı dinamik dispatch |
| **fixed** | Sabit Rota (Sweep Heuristic) | Her gün 06:00'da önceden hesaplanmış TSP rotaları |

Simülasyon çıktısı: her iki dünya için CO2, yakıt, maliyet ve taşma metrikleri. Fark = DPET'in sağladığı tasarruf.

---

## 2. Mimari Harita

```
backend/app/
├── main.py                ← FastAPI uygulama girişi, lifespan, CORS
├── database.py            ← PostgreSQL bağlantısı (SQLAlchemy)
├── schemas.py             ← Pydantic veri modelleri (BinOut, AnomalyEventOut …)
├── environment.py         ← Kentsel dolum dinamikleri (district, saat profili, event)
├── predictor.py           ← K-means zonelama + ETF öğrenme (FillPredictor)
├── dpet.py                ← 6 katmanlı dispatch algoritması
├── simulation_engine.py   ← Tüm dünyaları yöneten ana motor (SimulationEngine)
├── routers/
│   └── simulation.py      ← /api/simulation/* REST endpoint'leri
└── services/
    ├── anomaly_service.py ← DB'ye anomali yazma
    └── bins_service.py    ← IoT telemetri (heartbeat, state-change)

frontend/src/
├── main.jsx               ← React Router kurulumu
├── App.jsx                ← Ana harita (Leaflet + TomTom trafik)
├── components/
│   ├── SimulationPage.jsx ← İkili dashboard (algo | fixed)
│   ├── AnomaliesPage.jsx  ← Anomali log tablosu
│   ├── MapView.jsx        ← Leaflet cluster haritası
│   └── BinPopup.jsx       ← Kutu popup detayı
└── services/api.js        ← Axios HTTP istemcisi
```

---

## 3. Veri Seti ve Başlangıç Konfigürasyonu

### 3.1 Kaynak Veri

- **Dosya:** `backend/data/bins_wgs84.csv`
- **Kaynak:** Dublin City Council açık veri (DCC)
- **Kayıt sayısı:** 3.424 çöp kutusu
- **Koordinat dönüşümü:** ITM (Irish Transverse Mercator) → WGS84 (lat/lon)
- **Alanlar:** `Bin_ID`, `Electoral_Area`, `Bin_Type`, `latitude`, `longitude`

### 3.2 `load_bins()` — Başlangıç Atamaları

`simulation_engine.py` → `SimulationEngine.load_bins()`

Her bin için startup'ta **rastgele** atanan özellikler:

| Özellik | Değerler | Atama Mantığı |
|---------|----------|---------------|
| `fill_label` | A / B / C | CSV'den veya varsayılan C |
| `fill_rate` | A: 12–16, B: 4–8, C: 0.5–1.5 %/sim-saat | `fill_label`'a göre `random.uniform` |
| `distance_label` | 1 / 2 / 3 | CSV'den veya varsayılan 2 |
| `district_type` | RESIDENTIAL / OFFICE / MALL / UNIVERSITY / TOURIST | `assign_district(region)` fonksiyonu |

**Kritik karar:** Her iki dünya (algo + fixed) aynı `fill_rate` değerini paylaşır. Böylece karşılaştırma adil olur; fiziksel kutu değişmiyor, yalnızca dispatch stratejisi değişiyor.

### 3.3 `_compute_depot()` — Depo Konumu

```python
northernmost = max(algo_bins.values(), key=lambda b: b.lat)
depot_lat = northernmost.lat + 0.005   # ~550m kuzey
depot_lon = northernmost.lon
```

**Karar gerekçesi:** Depoyu en kuzey kutunun biraz kuzeyine koymak, tüm şehri güneye doğru kapsayan mantıklı bir çıkış noktası sağlar. Gerçek Dublin atık depolarının da şehir kuzeyinde olduğu gözlemlenmiştir.

### 3.4 `FILL_RATE_RANGES` — Dolum Hızı Dağılımı

```
A (30%): 12–16 %/sim-saat  → 6–8 sim saatte dolar
B (40%): 4–8  %/sim-saat  → 12–25 sim saatte dolar
C (30%): 0.5–1.5 %/sim-saat → 67–200 sim saatte dolar
```

**Simülasyondaki önemi:** ÇOK YÜKSEK.
- A-label kutular DPET'in ETF avantajını görünür kılar: erken müdahale taşmayı önler.
- C-label kutular fixed rotanın zayıflığını gösterir: her gün o kutuya git, boş bul.
- Karma dağılım (A%30 + B%40 + C%30) gerçekçi şehir profiline yakın.

---

## 4. Environment Modülü — Kentsel Atık Dinamikleri

**Dosya:** `backend/app/environment.py`

Bu modül, her saatlik dolum tick'inde bir kutunun ne kadar dolacağını belirler. Dört katmanlı bir model kullanır.

### 4.1 Katman 1 — DistrictType (Bölge Tipi)

```python
class DistrictType(str, Enum):
    RESIDENTIAL = "residential"   # Konut — akşam piki
    OFFICE      = "office"        # İş merkezi — sabah piki
    MALL        = "mall"          # AVM — öğleden sonra/akşam piki
    UNIVERSITY  = "university"    # Kampüs — ders saatleri piki
    TOURIST     = "tourist"       # Turizm — öğle/akşam çift pik
```

**Simülasyondaki önemi:** ORTA.
District tipi saatlik çarpanı belirler. Farklı bölgelerdeki kutular aynı saatte farklı hızlarda dolar — bu gerçekçi davranış DPET'in bölgeye duyarlı dispatch'i için zemin sağlar.

### 4.2 Katman 2 — HourlyProfiles (Saatlik Profiller)

`HOURLY_PROFILES` sözlüğü, her district tipi için 24 elemanlı çarpan dizisi tutar.

#### Saatlik Çarpan Tablosu (özet):

| Saat | RESIDENTIAL | OFFICE | MALL | UNIVERSITY | TOURIST |
|------|-------------|--------|------|-----------|---------|
| 00-05 | 0.2 | 0.1 | 0.1 | 0.1 | 0.2–0.3 |
| 06-11 | 0.6–0.9 | 0.9–1.9 | 0.1–1.2 | 0.6–1.9 | 0.4–1.7 |
| 12-17 | 0.5–1.2 | 0.7–1.6 | 1.4–2.3 | 1.5–1.9 | 1.9–2.1 |
| 18-23 | 0.4–2.0 | 0.1–0.2 | 0.1–2.4 | 0.1–0.4 | 0.6–2.1 |

**Pik saatler özeti:**
- **RESIDENTIAL:** Saat 18-20 (max 2.0) — akşam eve dönüş
- **OFFICE:** Saat 08-09 (max 1.9) — kahvaltı/öğle saatleri
- **MALL:** Saat 17-19 (max 2.4) — alışveriş akşamı
- **UNIVERSITY:** Saat 09-13 (max 1.9) — ders saatleri
- **TOURIST:** Saat 13-15 ve 18-20 (max 2.1) — öğle yemeği ve gece hayatı

#### `hourly_multiplier(district, hour)` metodu

```python
def hourly_multiplier(district: DistrictType, hour: int) -> float:
    return HOURLY_PROFILES[district][hour % 24]
```

**Simülasyondaki önemi:** YÜKSEK.
Bu çarpan, bir kutunun saate göre daha hızlı veya yavaş dolmasını sağlar. `% 24` güvenlik önlemi (0–23 dışı değerlere karşı).

### 4.3 Katman 3 — NoiseModel (Gürültü Modeli)

```python
_NOISE_STD = 0.10  # ±%10 standart sapma

def apply_noise(value: float) -> float:
    noise_factor = 1.0 + random.gauss(0.0, _NOISE_STD)
    return max(0.0, value * noise_factor)
```

**Ne yapar:** Her fill tick'te dolum hızına Gaussian gürültü ekler. `max(0.0, ...)` ile negatif hız engellenmiş.

**Simülasyondaki önemi:** ORTA.
Gürültü olmadan simülasyon deterministik olur; her run aynı sonucu üretir. Gürültü, gerçek hayattaki belirsizliği (hava durumu, beklenmedik yoğunluk) temsil eder. DPET'in tahmin gücünü test etmek için gereklidir.

### 4.4 Katman 4 — Event System (Etkinlik Sistemi)

#### `Event` dataclass'ı

| Alan | Tip | Açıklama |
|------|-----|----------|
| `event_id` | str | EVT_0001, EVT_0002 ... |
| `event_type` | str | "concert", "match", "festival", "sale", "weekend" |
| `start_sim_s` | float | Başlangıç sim saniyesi |
| `end_sim_s` | float | Bitiş sim saniyesi |
| `affected_districts` | list[DistrictType] | Etkilenen bölge tipleri |
| `multiplier` | float | Dolum hızı çarpanı |

#### Event Şablonları

| Tip | Etkilenen Bölgeler | Çarpan | Süre |
|-----|--------------------|--------|------|
| concert | TOURIST, RESIDENTIAL | 1.8–3.0x | 4 saat |
| match | TOURIST, MALL | 2.0–3.5x | 3 saat |
| festival | TOURIST, MALL, RESIDENTIAL | 1.5–2.5x | 8 saat |
| sale | MALL | 1.5–2.0x | 6 saat |
| weekend | Tüm tipler | 1.2–1.6x | 48 saat |

#### `EventManager` sınıfı

**`tick(sim_s)`:** Her ana döngü tick'inde çağrılır. Süresi dolmuş eventleri temizler, yeni event zamanı geldiyse `_spawn()` çağırır.

**`_spawn(sim_s)`:** Şablonlardan rastgele birini seçer, çarpanı `random.uniform` ile belirler, Event objesi oluşturur, sonraki spawn zamanını 12–48 sim saat sonrasına ayarlar.

**`active(sim_s)`:** O an aktif eventleri döndürür (başlangıç ≤ şimdi ≤ bitiş).

**`_cleanup(sim_s)`:** Bellek kontrolü — süresi dolmuş eventler listeden çıkarılır.

**Simülasyondaki önemi:** ORTA-YÜKSEK.
Etkinlikler ani talep artışlarını simüle eder. DPET bu artışları ETF hesabındaki fill_rate üzerinden yakalar ve önceden müdahale eder. Fixed rota bu artışlara kör kalır.

### 4.5 `assign_district(region)` — District Atama

```python
_REGION_KEYWORDS = {
    UNIVERSITY: ["univ", "college", "campus", "tech"],
    MALL:       ["mall", "shop", "centre", "center", "retail"],
    TOURIST:    ["hotel", "tourist", "museum", "temple bar"],
    OFFICE:     ["office", "business", "corp", "dock", "ifsc"],
}
```

Önce region string'de anahtar kelime arar. Bulamazsa Dublin'in gerçek bölge dağılımına göre ağırlıklı rastgele atar:
- RESIDENTIAL %40, OFFICE %20, MALL %15, UNIVERSITY %15, TOURIST %10

### 4.6 `effective_fill_rate(base_rate, district, hour, events)` — Ana Hesap

```
rate = base_rate × hourly_multiplier(district, hour) × max_event_multiplier × gaussian_noise(σ=0.10)
```

**Birden fazla event varsa:** En yüksek çarpan alınır (en kötü senaryo).

**Simülasyondaki önemi:** ÇOK YÜKSEK.
Bu fonksiyon, her kutu için her saatlik tick'te çağrılan merkezi dolum hesabıdır. Tüm dinamizm buradan kaynaklanır.

---

## 5. FillPredictor — Coğrafi Zonelama ve ETF Öğrenmesi

**Dosya:** `backend/app/predictor.py`

### 5.1 Temel Sorumluluklar

1. **Coğrafi Zone Ataması:** K-means++ ile 3.424 kutuyu 12 coğrafi bölgeye böler.
2. **Fill Rate Öğrenmesi:** EMPTIED/OVERFLOW olaylarından gerçek dolum hızını öğrenir.
3. **ETF Tahmini:** Mevcut doluluk + öğrenilen hızla taşmaya kalan saati tahmin eder.
4. **Zone Sorguları:** Dispatch kararları için zone bazında hazır kutu listesi üretir.

### 5.2 `assign_zones(bins, n_zones=12)` — K-means++ Zone Ataması

**Algoritma adımları:**

1. **K-means++ Başlangıç:** İlk centroid rastgele seçilir. Her sonraki centroid, mevcut centroid'lere uzaklık karesiyle orantılı olasılıkla seçilir (en dağınık noktayı tercih eder).
2. **Lloyd İterasyonları (25 tur):** Her kutu en yakın centroid'e atanır, centroid'ler cluster ortalamasına güncellenir.
3. **Final Atama:** Her kutu kalıcı zone ID'si alır.

**Parametreler:**

| Parametre | Değer | Açıklama |
|-----------|-------|----------|
| `N_ZONES` | 12 | Zone sayısı |
| `KMEANS_ITERATIONS` | 25 | Lloyd iterasyon sayısı |

**Neden 12 zone?** 3.424 kutu / 12 ≈ 285 kutu/zone. Bu, zone başına yeterli kutu yoğunluğu sağlarken dispatch'i yönetilebilir tutar. Daha fazla zone = daha küçük, daha sık seferler; daha az zone = daha büyük, seyrek seferler.

**Simülasyondaki önemi:** YÜKSEK.
Zonelama olmadan dispatch algoritması tüm 3.424 kutuda skor hesaplamak zorunda kalır. Zone filtreleme hem hızı artırır hem de coğrafi mantık katar (aynı mahalle kutularını birlikte topla).

**Kritik karar:** Zone ataması `reset()` sırasında **yeniden yapılmaz** — kutu koordinatları değişmediği için gereksiz.

### 5.3 `record_event(event, bin_id, sim_s)` — Fill History Besleme

```
EMPTIED  → son boşaltma zamanını kaydet
OVERFLOW → cycle = şimdi − son_EMPTIED → rolling window'a ekle
```

**Rolling window:** Her kutu için en son `MAX_CYCLES=8` cycle süresi saklanır. Eski veri atılır.

**Önemli kısıt:** Yalnızca `"algo"` dünyasından beslenir. Fixed dünya predictor'ı kirletmez.

**Simülasyondaki önemi:** ORTA.
İlk birkaç cycle'dan sonra gerçek gözlemlere geçer. Başlangıçta `fallback_rate` (konfigüre edilmiş fill_rate) kullanılır.

### 5.4 `predicted_fill_rate_h(bin_id, fallback_rate)` — Hız Tahmini

```python
cycles = self._cycles.get(bin_id, [])
if len(cycles) < 2:
    return fallback_rate  # yeterli gözlem yok
avg_s = sum(cycles) / len(cycles)
return 100.0 / (avg_s / 3600.0)  # %100 / ortalama_dolumsaati
```

**Fallback kuralı:** 2'den az gözlem varsa konfigüre edilmiş oran kullanılır.

**Simülasyondaki önemi:** YÜKSEK.
Bu tahmin ETF hesabının temelidir. Gerçek dolum geçmişi kullanıldıkça tahmin kalitesi artar.

### 5.5 `predicted_etf_h(bin_id, fill_pct, fallback_rate)` — ETF Hesabı

```
ETF = (100 - fill_pct) / predicted_fill_rate_h
```

Birim: **sim-saat** (simulation hours). ETF=3 → 3 sim saatte dolacak.

**Simülasyondaki önemi:** ÇOK YÜKSEK.
DPET'in kalbi. ETF sayesinde algoritma taşmadan **önce** müdahale eder. Fixed rota ETF bilmez.

### 5.6 `zone_ready_bins(available, lookahead_h=7.0)` — Zone Dispatch Tetikleme

`LOOKAHEAD_H=7` sim saat içinde dolacağı tahmin edilen kutular listelenir. Zone başına `MIN_ZONE_BINS=6` veya daha fazla "hazır" kutu varsa o zone döndürülür.

**Simülasyondaki önemi:** YÜKSEK.
Dispatch'i proaktif yapar. Kutular henüz taşmadan toplanmaya başlanır.

### 5.7 `urgent_zone_bins(available, etf_threshold_h=2.0, min_bins=4)` — Acil Zone

ETF ≤ 2 sim saat olan zone'lar. Parametre açık, zone_ready'den daha sert eşik.

**Simülasyondaki önemi:** ÇOK YÜKSEK.
Tier-1 dispatch tetikleyicisi. Bu eşik aşılmadan taşma önlenemez.

### 5.8 `coverage_zone_bins(available, zone_id, min_fill=50.0)` — Coverage Rotation

Belirtilen zone'da %50 üzeri dolu kutular. Coverage rotation dispatch'i için.

**Simülasyondaki önemi:** ORTA.
Yavaş dolan C-label kutularının düzenli toplanmasını sağlar. Yoksa bu kutular sonsuza kadar bekler.

### 5.9 `adaptive_coverage_interval_s(zone_id, available, base_interval_s=72000)` — Adaptif Aralık

Zone'daki kutular medyan ETF'ine göre ziyaret sıklığı ayarlanır:
```
ratio = clamp(0.25, 3.0, median_etf / base_h)
interval = base_interval_s × ratio
```

**Sonuç:** Hızlı dolan zone'lar daha sık (base/4 kadar), yavaş dolan zone'lar daha seyrek (base×3 kadar) ziyaret edilir.

**Simülasyondaki önemi:** YÜKSEK.
Bu adaptasyon yakıt ve km tasarrufu sağlar. Gereksiz ziyaretleri keser.

### 5.10 `reset()` — Sıfırlama

Öğrenilen cycle verilerini ve son boşaltma zamanlarını siler. **Zone atamaları korunur.**

---

## 6. DPET Algoritması — 6 Katmanlı Dispatch

**Dosya:** `backend/app/dpet.py`

DPET (Dynamic Priority & Efficient Truck), dispatch kararını altı bağımsız katmana böler. Her katman bir sorunu çözer.

### 6.1 Katman 1 — TrafficModel (Trafik Modeli)

```python
_RUSH_HOURS = {7, 8, 9, 17, 18, 19}   # sabah/akşam piki
_PEAK_HOURS = {6, 10, 16, 20}          # yoğun olmayan ama dikkatli

def traffic_score(hour: int) -> float:
    if hour in _RUSH_HOURS: return 0.80
    if hour in _PEAK_HOURS: return 0.50
    return 0.20
```

**Döndürdüğü değer:** 0.0 (boş yol) → 1.0 (tam tıkanıklık)

**Simülasyondaki önemi:** ORTA.
Trafik skoru iki yerde kullanılır:
1. `BinSelector`'da rush eşiğini 70% → 85%'e yükseltir (trafikteyken sadece acilleri al)
2. `BinScorer`'da `traffic_ok = 1 - traffic` bileşeni (az trafik = iyi fırsat, %12 ağırlık)

### 6.2 Katman 2 — BinScorer (Kutu Puanlama)

Her kutunun öncelik skoru şu formülle hesaplanır:

```
skor = 0.40 × fill_urgency
     + 0.35 × etf_urgency
     + 0.12 × traffic_ok
     + 0.08 × density_norm
     + 0.05 × proximity
```

#### Bileşenler Detaylı:

**fill_urgency** (ağırlık: %40)
```python
fill_urgency = (fill_pct / 100.0) ** 2
if fill_pct >= 85.0:
    boost = (fill_pct - 85.0) / 15.0
    fill_urgency += boost * (1.0 - fill_urgency)  # kritik kutular ekstra baskı
```
Kare alma: %50 dolu kutu 0.25 puan, %90 dolu kutu 0.81 puan. 85%+ için ek baskı.

**etf_urgency** (ağırlık: %35)
```python
etf = (100 - fill_pct) / fill_rate   # sim-saat
etf_urgency = max(0.0, 1.0 - etf / 24.0)
```
ETF_HORIZON = 24 sim saat. 24+ saat kalan kutu → 0.0 puan. 0 saat kalan → 1.0 puan.

**proximity** (ağırlık: %5)
```python
proximity = 1.0 - (distance_label - 1) / 2.0
# label 1 → 1.0, label 2 → 0.5, label 3 → 0.0
```
Yakın kutu hafif avantajlı. Kasıtlı düşük ağırlık — uzak ama kritik kutuyu elemez.

**traffic_ok** (ağırlık: %12)
```python
traffic_ok = 1.0 - traffic_score(hour)
```
Gece → 0.8, rush saat → 0.2. Az trafik = yüksek skor = o saatte gitmeye değer.

**density_norm** (ağırlık: %8)
```python
nearby = count_nearby_bins(lat, lon, bins, radius_km=1.0, min_fill=65.0)
density_norm = min(1.0, nearby / 10.0)
```
1 km yarıçap içinde %65+ dolu 10+ kutu varsa tam puan. Toplu toplama verimini artırır.

**Simülasyondaki önemi:** ÇOK YÜKSEK.
Ağırlık dengesi kritik bir tasarım kararıdır. ETF (%35) + fill (%40) = %75; algoritma önce doluluk baskısına, sonra zaman baskısına bakıyor. Proximity düşük tutulmuş çünkü uzak ama kritik kutu önemlidir.

### 6.3 Katman 3 — BinSelector (Kutu Seçimi)

```python
_MIN_FILL_NORMAL = 70.0   # normal saatlerde eşik
_MIN_FILL_RUSH   = 85.0   # rush saatlerde eşik
ETF_LEAD_TIME    = 3.0    # ≤3 sim saat kalan → her zaman dahil
_EMERGENCY_FILL  = 88.0   # %88+ → eşiği bypass et
MIN_DISPATCH     = 8      # en az 8 kutu seçilemezse bekle
```

**`select_bins()` seçim mantığı (öncelik sırası):**

1. `is_anomaly == True` → her zaman atla
2. `fill_pct >= 88.0` → **daima dahil et** (acil override)
3. `etf <= 3.0 sim-saat` → **daima dahil et** (ETF kritik)
4. `fill_pct >= min_fill` → normal/rush eşiğini geç
5. Skora göre sırala, en iyi `max_stops × available_slots` kutuu döndür

**`MIN_DISPATCH=8` kuralı:** Acil kutu yoksa ve 8'den az kutu seçildiyse dispatch yapma. Tek kutuluk seferler yakıt israfıdır.

**Simülasyondaki önemi:** ÇOK YÜKSEK.
Bu katman, hangi kutuların bu tick'te dispatch'e girebileceğini filtreler. Rush saatte eşiği 85%'e yükseltmek gereksiz trafik maliyetini önler.

### 6.4 Katman 4 — RouteBuilder (Rota Oluşturma)

**Pipeline:** NN sıralama → kapasite kırpma → tam 2-opt

#### `_nn_route(scored, depot_lat, depot_lon)` — Nearest-Neighbor

Depoyı başlangıç noktası olarak alır. Her adımda kalan kutular arasından en yakınını seçer. O(n²) ama n küçük (max 40).

**Karar gerekçesi:** NN tek başına iyi bir başlangıç noktası verir, 2-opt bunu iyileştirir. Random başlangıç 2-opt'un kötü local minimuma takılma riskini artırır.

#### `_trim_by_capacity(nn_ordered)` — Kapasite Kırpma

```python
TRUCK_CAPACITY      = 1.0   # normalize
BIN_VOLUME_FRACTION = 0.05  # %100 dolu kutu = kamyonun %5'i
```

%100 dolu 20 kutu = kamyon kapasitesi. Daha az dolu kutular daha az yer kaplar. NN sıralamasında kapasiteyi aşan ilk kutuda dur.

**Simülasyondaki önemi:** YÜKSEK.
Hacimsel model gerçekçi kamyon kapasitesi simüle eder. %50 dolu kutu %100'lük kadar yer kaplamaz.

#### `_full_2opt(stops, depot_lat, depot_lon)` — 2-opt TSP

**Standart km yerine ağırlık-duyarlı yakıt maliyeti minimize edilir:**

```python
def _fuel_aware_dist(stops, dlat, dlon):
    # İlk bacak: boş kamyon, standart yakıt
    cost = km(depot → stop[0])
    for i, stop in enumerate(stops[1:]):
        w_factor = (i+1) / n           # 0 → 1 arası artar
        cost += km(i → i+1) × (1 + 0.8 × w_factor)
    # Dönüş: tam dolu kamyon
    cost += km(last → depot) × 1.8
```

**2-opt döngüsü:** Her (i, j) çifti için rotanın i–j arasını ters çevirir. Maliyet düşerse güncelle. Gelişme kalmayınca dur.

**Karar gerekçesi:** Ağırlık-duyarlı 2-opt sadece mesafeyi kısaltmaz, aynı zamanda kamyonun hafif yükle uzun bacak, ağır yükle kısa bacak yapmasını teşvik eder. Bu gerçek dünya yakıt optimizasyonuna daha yakın.

**Simülasyondaki önemi:** YÜKSEK.
2-opt olmadan rotalar %15–30 daha uzun olabilir. Km tasarrufu doğrudan CO2 ve yakıt metriklerine yansır.

### 6.5 Katman 5 — RouteEfficiency (Rota Verimliliği)

```python
_MIN_ROUTE_EFFICIENCY = 0.20  # minimum bin/km

def route_efficiency(stops, depot_lat, depot_lon):
    return len(stops) / total_route_distance_km
```

0.20 bin/km = 5 km'de 1 kutu. Bu eşiğin altındaki rotalar "boşa gidiş" sayılır.

**Veto kuralı:** Rota verimsizse ve acil kutu yoksa bu rota atlanır.

**Simülasyondaki önemi:** YÜKSEK.
Verimliliksiz rotaların engellenmesi, km ve yakıt tasarrufunun önemli bir kaynağıdır. Fixed rotalar bu kontrolden geçmez.

### 6.6 Katman 6 — Dispatcher (Ana Dispatch Fonksiyonu)

**`dpet_dispatch(bins, active_truck_count, hour, depot_lat, depot_lon, max_fleet, max_stops)`**

**Karar akışı:**

```
1. available_slots = max_fleet - active_truck_count
   slots ≤ 0 → boş liste döndür (filo dolu)

2. traffic = traffic_score(hour)

3. selected = select_bins(bins, traffic, depot, max_stops × slots)

4. has_any_urgent = 88%+ veya ETF ≤ 3h olan kutu var mı?
   len(selected) < 8 ve urgent yok → boş döndür (toplu bekleme)

5. Her max_stops boyutunda chunk için:
   a. Chunk acil değil ve < 8 kutu → dur (kalan chunkları da atla)
   b. build_route(chunk, depot) → NN + kapasite kırpma + 2-opt
   c. route_efficiency(route) < 0.20 ve acil değil → bu rotayı atla
   d. routes.append(route)
   e. len(routes) >= slots → dur

6. routes döndür
```

**Simülasyondaki önemi:** ÇOK YÜKSEK.
Bu fonksiyon tüm 6 katmanı bir araya getiren orchestrator'dır. Her 1 sim saatte çağrılır.

---

## 7. SimulationEngine — Ana Simülasyon Motoru

**Dosya:** `backend/app/simulation_engine.py`

### 7.1 Singleton Pattern

```python
engine = SimulationEngine()  # dosya sonunda oluşturulur
```

Uygulama genelinde tek bir engine instance'ı vardır. Tüm API endpoint'leri bu objeyi kullanır.

### 7.2 Simülasyon Saati (Virtual Clock)

```python
_sim_epoch = datetime(2024, 1, 1, tzinfo=timezone.utc)
_sim_s: float = 0.0

@property
def virtual_clock(self) -> datetime:
    return _sim_epoch + timedelta(seconds=_sim_s)
```

**Tick sistemi:**
```python
TICK_REAL_S = 0.2  # 0.2 gerçek saniye = 1 tick

async def _loop(self):
    while is_running:
        _sim_s += 0.2 × speed_multiplier
        ... (tüm job'lar)
        await asyncio.sleep(0.2)
```

| Hız | 1 gerçek dakika | 1 gerçek saat |
|-----|-----------------|---------------|
| 1x | 1 sim dakika | 1 sim saat |
| 60x | 1 sim saat | 60 sim saat (2.5 gün) |
| 3600x | 60 sim saat | 3600 sim saat (150 gün) |
| 86400x | 1440 sim saat | 86400 sim saat (9.86 yıl) |

### 7.3 `BinState` Dataclass

| Alan | Tip | Açıklama |
|------|-----|----------|
| `bin_id` | str | Kutu ID (ör. WMS4505) |
| `lat`, `lon` | float | WGS84 koordinatları |
| `region` | str | Dublin electoral area |
| `fill_label` | str | A/B/C (dolum hızı kategorisi) |
| `distance_label` | int | 1/2/3 (depoya uzaklık) |
| `district_type` | DistrictType | Saatlik profil için |
| `fill_rate` | float | Temel hız (%/sim-saat) |
| `fill_pct` | float | Anlık doluluk [0.0 – 100.0] |
| `status` | str | EMPTY / FULL / CRITICAL_FULL / SENSOR_ERROR / OFFLINE |
| `is_anomaly` | bool | True → fill job atlar, dispatch seçmez |
| `overflow_start_s` | float | %100'e ilk geçiş sim_s (aging için) |
| `last_emptied_sim_s` | float | Son boşaltım sim_s |

**`refresh_status()`:** `fill_pct`'e göre status günceller.
- ≥85% → CRITICAL_FULL
- ≥50% → FULL
- <50% → EMPTY

**`empty(sim_s)`:** Kutuyu sıfırlar, `last_emptied_sim_s` kaydeder, anomali bayrağını temizler.

### 7.4 `TruckRoute` Dataclass

| Alan | Açıklama |
|------|----------|
| `truck_id` | Artan sayaç |
| `route_type` | "algo" veya "fixed" |
| `stops` | Stop listesi (sıralı duraklar) |
| `full_latlons` | [depot, ...stops, depot] — tam rota çizimi için |
| `current_stop_idx` | Şu an hedeflenen durak indeksi |
| `lat`, `lon` | Anlık konum (interpolasyon ile) |
| `status` | "en_route" / "servicing" / "returning" / "done" |
| `progress` | [0.0, 1.0] mevcut bacaktaki ilerleme |
| `capacity_used` | Normalize doluluk [0.0, 1.0] |

### 7.5 `_job_fill()` — Dolum Job'u

Her `FILL_JOB_INTERVAL_S=3600` sim saniyede bir çalışır.

```python
for world in (algo_bins, fixed_bins):
    for b in world.values():
        if b.is_anomaly: continue
        rate = effective_fill_rate(b.fill_rate, b.district_type, hour, events)
        old_pct = b.fill_pct
        b.fill_pct = min(100.0, b.fill_pct + rate)
        if b.fill_pct >= 100.0:
            kpis["overflow_events"] += 1
            if old_pct < 100.0:
                kpis["overflow_count"] += 1  # yeni taşma (ilk geçiş)
        b.refresh_status()
```

**overflow_events vs overflow_count ayrımı:**
- `overflow_events`: Her tick %100'de olan kutu sayar (birikim)
- `overflow_count`: %100'e ilk geçiş sayar (kaç farklı taşma oldu)

**Simülasyondaki önemi:** ÇOK YÜKSEK.
Bu job olmadan simülasyon anlamsız. Her saatlik adımda tüm kutular güncellenir.

### 7.6 `_job_dispatch_algo()` — DPET Dispatch Job'u

Her `DISPATCH_ALGO_INTERVAL_S=3600` sim saniyede çalışır. Birkaç aşamalı dispatch hiyerarşisi:

#### Tier 0 — Priority Aging (Öncelikli Yaşlanma)

```python
AGING_THRESHOLD_S = 4 * 3600   # 4 sim saat %100'de kalırsa
AGING_MIN_BINS    = 3           # en az 3 "yaşlı" kutu

aged_bins = [b for b in available if b.overflow_start_s >= 0
             and sim_s - b.overflow_start_s >= AGING_THRESHOLD_S]
```

4 sim saat %100'de kalan ve sayı ≥3 olan kutular için normal filonun önünde ekstra kamyon gönderilir.

**Simülasyondaki önemi:** YÜKSEK.
Uzun süre taşan kutuların ihmal edilmesini önler. Bu tier olmadan zone kısıtları bazı kritik kutuları geciktirebilir.

#### Tier 1 — Acil Zone (ETF ≤ 2 saat)

```python
urgent_zones = predictor.urgent_zone_bins(available, etf_threshold_h=2.0, min_bins=4)
for zone_id, zone_bins in urgent_zones.items():
    _dispatch_zone_bins(zone_id, zone_bins)
```

**Simülasyondaki önemi:** ÇOK YÜKSEK.
Taşmayı önleyen birincil mekanizma. ETF 2 saatten azsa o zone hemen servis alır.

#### Tier 2 — Coverage Rotation (Adaptif Zone Ziyareti)

```python
for zone_id in range(predictor.n_zones()):
    last_visit = _last_zone_visit.get(zone_id, -COVERAGE_INTERVAL_S)
    adaptive_interval = predictor.adaptive_coverage_interval_s(zone_id, available, COVERAGE_INTERVAL_S)
    if sim_s - last_visit < adaptive_interval:
        continue
    zone_bins = predictor.coverage_zone_bins(available, zone_id, COVERAGE_MIN_FILL=50%)
    if zone_bins:
        _dispatch_zone_bins(zone_id, zone_bins)
```

**Simülasyondaki önemi:** YÜKSEK.
C-label kutular acil zone tetiklemeyebilir ama coverage rotation onları yakalar. Adaptif interval yakıt tasarrufu sağlar.

#### Acil Fallback (Tier 0–2 dispatch yoksa)

Hiç dispatch yapılmadıysa ve %90+ dolu kutu varsa, bunlar için son çare dpet_dispatch çağrısı yapılır.

#### `_try_extend_truck(urgent_bins)` — Mevcut Kamyona Ekleme

Yeni sefer açmadan acil kutuları mevcut aktif kamyonlara eklemeye çalışır.

```python
for b in urgent_bins:
    for truck in algo_trucks:
        extra_km, pos = _insertion_km(truck, new_stop, depot)
        if extra_km / rem_km <= MAX_DETOUR_RATIO(0.30):
            truck.stops.insert(pos, new_stop)
```

**Neden önemli:** Yeni kamyon = DISPATCH_COST_TL 2000 TL + yakıt. Mevcut kamyona ekleme sadece ek yakıt.

**Simülasyondaki önemi:** YÜKSEK.
Bu mekanizma, KPI'da "dispatch_count" metriğini düşürür, dolayısıyla operasyonel maliyet tasarrufu sağlar.

#### `_corridor_bins()` — Koridor Fırsatçı Toplama

Aktif kamyon rotalarının bacaklarına `CORRIDOR_RADIUS_KM=0.65` km içinde ve `CORRIDOR_MIN_FILL=70%` üzeri olan kutular tespit edilir, mevcut kamyonlara eklenir.

**Simülasyondaki önemi:** ORTA-YÜKSEK.
"Bedava" kutu toplar — zaten o yoldan geçilirken. Bu mekanizma yük/km metriğini iyileştirir.

### 7.7 `_job_dispatch_fixed()` — Sabit Rota Job'u

Her gün `FIXED_DISPATCH_HOUR=06:00`'da bir kez çalışır.

```python
vc = virtual_clock
day_key = (year, month, day)
if last_fixed_day_key == day_key: return  # bu gün zaten gönderildi
# Yeni gün: first min(12, route_count) kamyonu gönder
```

Kamyon rotasını bitirince `_dispatch_next_fixed_route()` ile sıradaki rota devreye girer (conveyor belt).

**Simülasyondaki önemi:** ÇOK YÜKSEK.
Fixed dünya referans noktasıdır. Bu job olmazsa karşılaştırma yapılamaz.

### 7.8 `_step_truck(truck, sim_s, world_bins)` — Kamyon Fiziksel Hareketi

Üç durum makinesi:

**`en_route`:** `leg_end_sim_s`'e ulaştıysa hedefe ilerle → `servicing` geç. Yoksa lineer interpolasyon ile ara konum hesapla.

**`servicing`:** `service_end_sim_s`'e ulaştıysa:
- Bin'i boşalt (`b.empty(sim_s)`)
- KPI'ya `bins_collected` ve `load_collected` ekle
- Sonraki durağa git → `en_route` geç
- Durak kalmadıysa depoya dön → `returning` geç

**`returning`:** Depoya ulaşınca `done` yap.

**Parametre:**
```python
TRUCK_SPEED_KMH  = 30.0    # km/saat
SERVICE_SIM_MIN  = 5       # dakika/durak servis süresi
```

**Simülasyondaki önemi:** ÇOK YÜKSEK.
Fiziksel hareket olmadan front-end haritada kamyon gösterilemez, gerçekçi zaman tahminleri yapılamaz.

### 7.9 `_weighted_fuel(stops, depot_lat, depot_lon)` — Ağırlık-Duyarlı Yakıt

```python
FUEL_PER_KM      = 0.35   # L/km boş kamyon
WEIGHT_MULTIPLIER = 0.8   # tam dolu = %80 fazla yakıt

fuel_km_i = FUEL_PER_KM × (1 + 0.8 × i/n)
```

Kamyon her kutuyu topladıkça ağırlaşır, yakıt tüketimi artar. Dönüş bacağında kamyon tam dolu: `FUEL_PER_KM × 1.8`.

**Simülasyondaki önemi:** YÜKSEK.
Bu model, yakıt tasarrufunun gerçekçi hesaplanmasını sağlar. Sadece km hesabı yakıtı %30–40 hafife alır.

### 7.10 `_insertion_km(truck, new_stop, depot)` — En Ucuz Ekleme Noktası

Mevcut rotanın her bacağı için `extra_km = dist(A→new) + dist(new→B) - dist(A→B)` hesaplar. En düşük ekleme maliyetli pozisyonu ve ek km'yi döndürür.

**Kısıt:** En_route iken mevcut hedef değiştirilemez (mid-leg yönlendirme yok).

### 7.11 `_dist_to_segment_km(p, a, b)` — Noktanın Segmente Mesafesi

Flat-earth yaklaşımıyla P noktasının A→B segment'ine olan mesafesini hesaplar. Koridor algoritması için kullanılır.

**Karar gerekçesi:** Haversine yerine flat-earth — kısa mesafelerde (< 2 km) hata ihmal edilebilir, hesap çok daha hızlı.

### 7.12 `_precompute_fixed_routes()` — Sabit Rota Ön Hesaplama

**Sweep (Sector) Heuristic:**

```python
def _angle_from_depot(b):
    return math.atan2(b.lon - depot_lon, b.lat - depot_lat)

all_bins = sorted(fixed_bins.values(), key=_angle_from_depot)
for i in range(0, len(all_bins), FIXED_ROUTE_SIZE=20):
    chunk = all_bins[i:i+20]
    nn_order = _nearest_neighbor(chunk, depot)
    route = _two_opt_route(nn_order_stops, depot)
    _fixed_routes.append(route)
```

**Akademik temel:** Gillett & Miller (1974) sweep algorithm for VRP.

Depot'tan her kutunun açısı hesaplanır, açıya göre sıralanıp 20'lik gruplara bölünür. Her grup radyal bir dilim kapsar.

**Neden bu yöntem?** Gerçek belediye sistemlerinde rotalar genellikle belirli bir yönde çalışır (kuzey rotası, güney rotası vs.). Sweep bu davranışı temsil eder. NN+2-opt eklenince sonuç TSP-kalitesinde sabit rota olur.

**Fixed dünyanın dezavantajı:** Uzak bir kutunun o yönde grupta olması o rotayı uzatır. Kutunun o gün dolup dolmaması önemli değil — rota her gün aynı.

**Simülasyondaki önemi:** ÇOK YÜKSEK.
Fixed rota referans sistemidir; ne kadar iyi kurulursa DPET'in tasarrufu o kadar anlamlı ölçülür.

### 7.13 `state_snapshot()` ve `kpis_snapshot()` — Frontend Veri Hazırlama

**`state_snapshot()`:** Her `GET /api/simulation/live-state` isteğine yanıt. Tüm bin ve kamyon verilerini JSON'a dönüştürür.

**`kpis_snapshot()`:**
```python
return {
    "algo":  {co2, fuel, cost, dispatch_count, overflow_count, ...},
    "fixed": {co2, fuel, cost, dispatch_count, overflow_count, ...},
    "savings": {
        "co2_kg":        fixed_co2 - algo_co2,
        "fuel_l":        fixed_fuel - algo_fuel,
        "cost_tl":       fixed_cost - algo_cost,
        "overflow_diff": fixed_overflow - algo_overflow,
    }
}
```

---

## 8. Sabit Rota Dünyası (Fixed World)

Fixed dünya, gerçek dünyadaki "manuel planlama" yaklaşımını temsil eder. Özellikler:

- Her gün saat 06:00'da tüm rotalar aynı sırayla gönderilir
- Kutunun dolu olup olmadığı umursamaz — rota her gün aynı
- ETF bilgisi kullanmaz
- Trafik durumunu görmezden gelir
- Mevcut kamyonlara ekleme yapmaz
- Priority aging uygulamaz

**Tasarım amacı:** Geleneksel atık yönetim sistemlerinin verimsizliğini görünür kılmak.

**Sweep heuristiği seçiminin gerekçesi:** Rastgele ya da sadece NN yerine sweep seçildi çünkü sweep, radyal rota yapısıyla gerçek şehir belediye rotalarını temsil eder. Bu sayede karşılaştırma daha adil ve gerçekçidir.

---

## 9. Anomali Sistemi

### 9.1 Simülasyon İçi Anomaliler

`simulation_engine.py` → `_job_anomaly()` — her 5–20 sim dakikada bir çalışır.

| Anomali Tipi | Ne Yapar | Süre |
|--------------|----------|------|
| `OVERFLOW_RISK` | Rastgele bir kutunun doluluk %95'e çıkar (yalnızca 1 dünyada) | Anlık |
| `FILL_ANOMALY` | Kutu aniden sıfırlanır (yetkisiz boşaltma simülasyonu) | Anlık |
| `SENSOR_FIXED_VALUE_ERROR` | Kutu `is_anomaly=True`, status="SENSOR_ERROR", 5–15 dk | 5–15 sim dakika |
| `BIN_OFFLINE` | Kutu `is_anomaly=True`, status="OFFLINE", 5–15 dk | 5–15 sim dakika |

**`_heal_anomalies()`:** Her tick'te `anomaly_end_sim_s` geçmişse anomali bayrağını kaldırır, status'u yeniler.

**Simülasyondaki önemi:** ORTA.
Anomaliler simülasyona rastgelelik katar ve DPET'in `is_anomaly` kontrolünü (dispatch'ten dışlama) test eder. KPI'ı doğrudan etkilemez ama overflow metriğini hafifçe bozabilir (OVERFLOW_RISK).

### 9.2 Gerçek IoT Anomali Servisi

`services/anomaly_service.py` — gerçek cihazlardan gelen telemetri için.

**Algılama kuralları:**
- `OVERFLOW_RISK`: CRITICAL_FULL geçişi
- `SENSOR_ERROR`: Cihaz SENSOR_ERROR enum'u bildirdi
- `SENSOR_FIXED_VALUE_ERROR`: Son 3 örnekte ham mesafe < 0.2 cm değişti
- `FILL_ANOMALY`: 15 dk içinde EMPTY→CRITICAL_FULL→EMPTY döngüsü
- `BIN_OFFLINE`: Son heartbeat > 24 saat önce

---

## 10. API ve Servis Katmanı

### 10.1 `main.py` — FastAPI Kurulumu

**Lifespan:** Uygulama başladığında CSV'den bin verisi yüklenir, engine'e beslenir.

**CORS:** Tüm origin'lere izin verilmiş (development ortamı).

### 10.2 Simulation Router (`routers/simulation.py`)

| Endpoint | Method | Açıklama |
|----------|--------|----------|
| `/api/simulation/start` | POST | `engine.start()` — async task başlatır |
| `/api/simulation/stop` | POST | `engine.stop()` — task iptal |
| `/api/simulation/reset` | POST | `engine.reset()` — tüm state sıfırla |
| `/api/simulation/speed` | PATCH | `{multiplier: "1x"/"60x"/"3600x"/"86400x"}` |
| `/api/simulation/live-state` | GET | Bin + kamyon snapshot (her 1–2 sn frontend'den çekilir) |
| `/api/simulation/live-kpis` | GET | KPI snapshot + savings |
| `/api/simulation/anomalies` | GET | Son 50 anomali |
| `/api/simulation/export-csv` | GET | Fill history CSV indir |

### 10.3 Bins Router

| Endpoint | Açıklama |
|----------|----------|
| `GET /api/bins` | Tüm bin'lerin listesi (DB'den) |
| `GET /api/bins/summary` | Bölge bazında kutu sayıları |
| `GET /api/anomalies` | Son anomaliler (DB) |
| `POST /api/devices/{bin_id}/state-change` | IoT telemetri — doluluk güncelle |
| `POST /api/devices/{bin_id}/heartbeat` | IoT canlı sinyal |

---

## 11. Frontend Mimarisi

### 11.1 Ana Harita (`App.jsx`)

- **Leaflet** harita + OpenStreetMap tile
- Kutu marker'ları doluluk rengine göre (yeşil→sarı→turuncu→kırmızı)
- `MarkerCluster` ile yoğun bölgelerde kümeleme
- **TomTom Traffic API** ile isteğe bağlı trafik overlay
- **OpenRouteService API** ile rota planlama (gerçek navigasyon)
- Özet istatistikler (toplam kutu, offline sayısı)

### 11.2 Simülasyon Sayfası (`SimulationPage.jsx`)

**Çift kolon düzeni:** Sol = DPET (algo), Sağ = Fixed

**Her kolon için:**
- Canlı Leaflet haritası (bin'ler + kamyonlar)
- KPI chip'leri: CO2 (kg), Yakıt (L), Maliyet (TL), Sistem Skoru (%)
- Aktif kamyon listesi: emoji durumu (🚛 = en_route, 🗑 = servicing), ilerleme, durak sayısı
- Tüm rota (kesik çizgi, düşük opaklık) + kalan rota (düz çizgi)
- Depo marker (parlak mor)

**Kontroller:**
- Start / Stop / Reset butonları
- Hız seçici (1x, 60x, 3600x, 86400x)
- Trafik overlay toggle

**Tasarruf Şeridi:** Fixed − Algo farkı:
- CO2 tasarrufu (kg)
- Yakıt tasarrufu (L)
- Maliyet tasarrufu (TL)
- Taşma farkı (adet)

### 11.3 Anomaliler Sayfası (`AnomaliesPage.jsx`)

Tablo: timestamp, bin_id, event_type, details (JSON). Filtreler: bin_id, tarih aralığı.

### 11.4 `services/api.js` — Axios İstemcisi

`VITE_API_URL` env değişkeninden base URL alır. Tüm endpoint wrapper'ları buradadır.

---

## 12. KPI Kataloğu — Her Metrik Detaylı

Aşağıda sistemdeki tüm metrikler, nasıl hesaplandıkları ve simülasyondaki önemleri açıklanmıştır.

---

### 12.1 `co2_kg` — CO2 Emisyonu

**Hesap:**
```
co2_kg += total_route_km × CO2_PER_KM (0.28 kg/km)
```
Kamyon oluşturulduğunda `_weighted_fuel()` fonksiyonundan gelen `total_km` kullanılır. Rota genişletmelerinde ek mesafe için ayrı eklenir.

**Birim:** kg  
**Simülasyondaki önemi:** ÇOK YÜKSEK.
Bu metrik DPET'in çevresel faydanın ana göstergesidir. Daha az km = daha az CO2. CO2 tasarrufu = fixed_co2 - algo_co2.

---

### 12.2 `fuel_l` — Yakıt Tüketimi

**Hesap:**
```python
fuel_km_i = FUEL_PER_KM (0.35 L/km) × (1 + WEIGHT_MULTIPLIER(0.8) × i/n)
# Dönüş bacağı: 0.35 × 1.8
total_fuel = Σ (dist_i × fuel_km_i)
```
Ağırlık-duyarlı model: kamyon dolukça yakıt sarfiyatı artar.

**Birim:** Litre  
**Simülasyondaki önemi:** ÇOK YÜKSEK.
Hem maliyet hesabına girer hem de çevre metriği olarak bağımsız önemi var. Yakıt tasarrufu = fixed_fuel - algo_fuel.

---

### 12.3 `cost_tl` — Operasyonel Maliyet

**Hesap:**
```
cost_tl += DISPATCH_COST_TL (2000 TL) + total_fuel × FUEL_PRICE_TL (45 TL/L)
```

Her dispatch (yani her yeni kamyon çıkışı) 2000 TL sabit maliyet ekler.

**Birim:** Türk Lirası (TL)  
**Simülasyondaki önemi:** ÇOK YÜKSEK.
En kolay anlaşılan iş metriği. Karar vericiler için: "DPET bu kadar para tasarruf etti." Maliyet tasarrufu = fixed_cost - algo_cost.

---

### 12.4 `dispatch_count` — Sefer Sayısı

**Hesap:** Her `_create_truck()` çağrısında +1.

**Birim:** Adet (kamyon seferi)  
**Simülasyondaki önemi:** YÜKSEK.
Dispatch sayısı, cost_tl'ye (2000 TL × dispatch) direkt etki eder. DPET toplu dispatch ve mevcut kamyona ekleme ile bu sayıyı düşürür.

---

### 12.5 `distance_km` — Toplam Mesafe

**Hesap:** Her yeni kamyon oluştururken `_weighted_fuel()` return değerinin `total_km` kısmı. Rota genişletmelerinde `best_extra_km` eklenir.

**Birim:** Kilometre  
**Simülasyondaki önemi:** YÜKSEK.
CO2 ve yakıt metriklerinin temeli. Ayrıca `route_efficiency` hesabında kullanılır.

---

### 12.6 `overflow_count` — Taşma Olayı Sayısı

**Hesap:** Bir kutunun `fill_pct` ilk kez `>= 100.0`'a ulaştığı an +1.

```python
if b.fill_pct >= 100.0:
    if old_pct < 100.0:
        kpis["overflow_count"] += 1  # ilk geçiş
```

**Birim:** Adet (benzersiz taşma olayı)  
**Simülasyondaki önemi:** ÇOK YÜKSEK.
DPET'in asıl amacı taşmayı önlemek. `overflow_diff = fixed_overflow - algo_overflow` pozitifse DPET başarılıdır. Bu metrik sistemin kalitesini özetler.

---

### 12.7 `overflow_events` — Taşma Tick Sayısı

**Hesap:** Her fill tick'te %100'de olan kutu başına +1.

**Birim:** Tick (kutu-tick birimi)  
**Simülasyondaki önemi:** ORTA.
`overflow_count`'tan farkı: bir kutu 10 tick %100'de kalırsa `overflow_count` 1, `overflow_events` 10 artar. Uzun süreli taşmaların ağırlığını ölçer. Dashboard'da doğrudan gösterilmez ama iç hesaplarda kullanılır.

---

### 12.8 `bins_collected` — Toplanan Kutu Sayısı

**Hesap:** Her `servicing` → `b.empty()` geçişinde +1.

**Birim:** Adet  
**Simülasyondaki önemi:** ORTA.
Verimliliği ölçmek için `distance_km` ile birlikte kullanılır. Tek başına anlamlı değil.

---

### 12.9 `load_collected` — Toplanan Yük

**Hesap:** Her boşaltımda `+= b.fill_pct` (boşaltma anındaki doluluk yüzdesi).

**Birim:** Yüzde toplam (% cinsinden)  
**Simülasyondaki önemi:** ORTA.
`load_per_km = load_collected / distance_km` hesabında kullanılır. Kamyon boş kutuları topluyorsa bu değer düşük kalır (fixed rotanın sorunu).

---

### 12.10 `load_per_km` — Yük/km Verimliliği (Türev Metrik)

**Hesap:**
```python
load_per_km = load_collected / distance_km
```

**Birim:** % / km  
**Simülasyondaki önemi:** YÜKSEK.
Bir km'de ne kadar gerçek yük toplandığını gösterir. Fixed rotalar boş kutulara da gider → düşük load_per_km. DPET sadece dolu kutulara gider → yüksek load_per_km.

---

### 12.11 `system_score` — Sistem Skoru (Frontend Türev)

**Hesap (frontend SimulationPage.jsx):**
```javascript
const loadPerKm = kpis.load_collected / kpis.distance_km;
const systemScore = Math.min(100, (loadPerKm / 0.80) * 100);
```

**Normalleştirme:** 0.80 %/km = %100 skor (ortalama %80 dolu kutu, km başına 1 kutu).

**Birim:** % (0–100)  
**Simülasyondaki önemi:** ORTA.
Hızlı kıyaslama için özetlenmiş verimlilik skoru. Akademik metrik değil, dashboard okunabilirliği için.

---

### 12.12 Savings (Tasarruf Metrikleri)

```python
"savings": {
    "co2_kg":        fixed_co2 - algo_co2,
    "fuel_l":        fixed_fuel - algo_fuel,
    "cost_tl":       fixed_cost - algo_cost,
    "overflow_diff": fixed_overflow_count - algo_overflow_count,
}
```

**Simülasyondaki önemi:** ÇOK YÜKSEK.
Projenin ana çıktısı. Pozitif değer = DPET kazanıyor. Dashboard'un "Tasarruf Şeridi" buradan beslenir.

---

## 13. Parametre Referansı — Tüm Sabitler

### 13.1 Environment Sabitleri

| Sabit | Değer | Açıklama |
|-------|-------|----------|
| `_NOISE_STD` | 0.10 | Gaussian gürültü standart sapması (±%10) |
| `_EVENT_MIN_GAP_S` | 43200 (12h) | Eventler arası minimum bekleme |
| `_EVENT_MAX_GAP_S` | 172800 (48h) | Eventler arası maksimum bekleme |

### 13.2 Predictor Sabitleri

| Sabit | Değer | Açıklama |
|-------|-------|----------|
| `N_ZONES` | 12 | K-means zone sayısı |
| `KMEANS_ITERATIONS` | 25 | Lloyd iterasyon sayısı |
| `MAX_CYCLES` | 8 | Rolling window boyutu |
| `LOOKAHEAD_H` | 7.0 | Zone-ready için bakış penceresi (sim-saat) |
| `MIN_ZONE_BINS` | 6 | Zone dispatch tetiklemek için minimum kutu |

### 13.3 DPET Sabitleri

| Sabit | Değer | Açıklama |
|-------|-------|----------|
| `_W_FILL` | 0.40 | Fill urgency ağırlığı |
| `_W_ETF` | 0.35 | ETF urgency ağırlığı |
| `_W_TRAFFIC` | 0.12 | Trafik fırsatı ağırlığı |
| `_W_DENSITY` | 0.08 | Yoğunluk bonus ağırlığı |
| `_W_PROXIMITY` | 0.05 | Yakınlık ağırlığı |
| `_ETF_HORIZON` | 24.0 | ETF normalizasyon penceresi (sim-saat) |
| `_DENSITY_RADIUS_KM` | 1.0 | Yoğunluk hesabı yarıçapı |
| `_DENSITY_MAX_BINS` | 10 | Yoğunluk normalizasyon tavanı |
| `_DENSITY_MIN_FILL` | 65.0 | Yoğunluğa sayılacak min doluluk |
| `_RUSH_THR` | 0.70 | Rush saat trafik eşiği |
| `_MIN_FILL_NORMAL` | 70.0 | Normal saatte min doluluk |
| `_MIN_FILL_RUSH` | 85.0 | Rush saatte min doluluk |
| `ETF_LEAD_TIME` | 3.0 | Kritik ETF eşiği (sim-saat) |
| `_EMERGENCY_FILL` | 88.0 | Acil override doluluk eşiği |
| `MIN_DISPATCH` | 8 | Minimum kutu sayısı (toplu dispatch) |
| `TRUCK_CAPACITY` | 1.0 | Normalize kamyon kapasitesi |
| `BIN_VOLUME_FRACTION` | 0.05 | %100 dolu kutu = kamyonun %5'i |
| `FUEL_WEIGHT_FACTOR` | 0.80 | Tam dolu kamyon = %80 fazla yakıt |
| `_MIN_ROUTE_EFFICIENCY` | 0.20 | Minimum bin/km oranı |

### 13.4 Simulation Engine Sabitleri

| Sabit | Değer | Açıklama |
|-------|-------|----------|
| `DEPOT_NORTH_OFFSET` | 0.005 | ~550m kuzey offset |
| `CO2_PER_KM` | 0.28 | kg CO2 / km |
| `FUEL_PER_KM` | 0.35 | L yakıt / km (boş kamyon) |
| `WEIGHT_MULTIPLIER` | 0.80 | Tam dolu = %80 fazla yakıt |
| `TRUCK_SPEED_KMH` | 30.0 | Kamyon hızı (km/saat) |
| `SERVICE_SIM_MIN` | 5 | Durak servis süresi (sim-dakika) |
| `FULL_THRESHOLD` | 50.0 | FULL status sınırı |
| `CRITICAL_THRESHOLD` | 85.0 | CRITICAL_FULL status sınırı |
| `DISPATCH_COST_TL` | 2000 | Sefer başına sabit maliyet |
| `FUEL_PRICE_TL` | 45 | TL/Litre yakıt fiyatı |
| `FILL_JOB_INTERVAL_S` | 3600 | Fill tick aralığı (1 sim-saat) |
| `DISPATCH_ALGO_INTERVAL_S` | 3600 | Dispatch tick aralığı (1 sim-saat) |
| `ANOMALY_MIN_INTERVAL_S` | 300 | Min anomali aralığı (5 sim-dakika) |
| `ANOMALY_MAX_INTERVAL_S` | 1200 | Max anomali aralığı (20 sim-dakika) |
| `ALGO_MAX_STOPS` | 40 | Kamyon başına max durak (DPET) |
| `FIXED_ROUTE_SIZE` | 20 | Sabit rota başına kutu sayısı |
| `FIXED_DISPATCH_HOUR` | 6 | Sabit rota çıkış saati (06:00) |
| `MAX_FLEET_SIZE` | 12 | Dünya başına max kamyon |
| `MAX_FILL_HISTORY` | 10000 | Bellekteki max fill event sayısı |
| `EXTENSION_FILL_THRESHOLD` | 90.0 | Mevcut kamyona ekleme eşiği |
| `MAX_DETOUR_RATIO` | 0.30 | Max sapma oranı (ekleme için) |
| `OPPORTUNISTIC_FILL_THRESHOLD` | 55.0 | Fırsatçı toplama eşiği |
| `FALLBACK_EMERGENCY_FILL` | 90.0 | Fallback scatter eşiği |
| `URGENT_ZONE_ETF_H` | 2.0 | Tier-1 acil ETF eşiği |
| `URGENT_ZONE_MIN_BINS` | 4 | Tier-1 minimum kutu sayısı |
| `COVERAGE_INTERVAL_S` | 72000 (20h) | Coverage rotation baz aralığı |
| `COVERAGE_MIN_FILL` | 50.0 | Coverage rotunda min doluluk |
| `CORRIDOR_RADIUS_KM` | 0.65 | Koridor toplama yarıçapı |
| `CORRIDOR_MIN_FILL` | 70.0 | Koridor toplama min doluluk |
| `MAX_CORRIDOR_DETOUR_RATIO` | 0.25 | Koridor ekleme sapma oranı |
| `COVERAGE_MAX_INTERVAL_S` | 129600 (36h) | Coverage maks bekleme tavanı |
| `AGING_THRESHOLD_S` | 14400 (4h) | Priority aging eşiği |
| `AGING_MIN_BINS` | 3 | Aging için min kutu sayısı |

---

## 14. Simülasyon Akış Diyagramı

```
Uygulama Başlangıcı
        │
        ▼
load_bins() → fill_label, fill_rate, district_type atama
        │
        ▼
_compute_depot() → en kuzey kutu + 0.005° offset
        │
        ├──► _precompute_fixed_routes() → Sweep(20) + NN + 2-opt → _fixed_routes[]
        └──► predictor.assign_zones() → K-means++(12 zone, 25 iter)
        │
        ▼
engine.start() → asyncio.create_task(_loop())
        │
        ▼
━━━━━━━━━━━━━━━━━━━━━ ANA DÖNGÜ (her 0.2 gerçek saniye) ━━━━━━━━━━━━━━━━
        │
        ├── _sim_s += 0.2 × speed_multiplier
        │
        ├── _job_events() → EventManager.tick() → yeni event üret / temizle
        │
        ├── _job_fill() [her 3600 sim-s]
        │       └─ algo + fixed her kutu için:
        │           effective_fill_rate() → fill_pct += rate
        │           overflow_count/events güncelle
        │
        ├── _job_dispatch_algo() [her 3600 sim-s]
        │       ├── claimed = aktif kamyonlardaki kutular
        │       ├── _try_extend_truck(90%+) → mevcut kamyona ekle
        │       ├── _corridor_bins() → rota yakınındaki kutular
        │       ├── Tier-0: aged_bins (4h %100'de) → dpet_dispatch()
        │       ├── Tier-1: urgent_zone_bins (ETF≤2h) → dpet_dispatch()
        │       ├── Tier-2: coverage_zone (adaptif interval) → dpet_dispatch()
        │       └── Fallback: 90%+ kalan bin → dpet_dispatch()
        │
        ├── _job_dispatch_fixed() [günde bir kez, 06:00]
        │       └─ _fixed_routes[] sırasıyla 12'ye kadar kamyon gönder
        │
        ├── _job_anomaly() [her 5-20 sim-dakika]
        │       └─ OVERFLOW_RISK / FILL_ANOMALY / SENSOR_ERROR / BIN_OFFLINE
        │
        ├── _heal_anomalies() → süresi dolmuş anomalileri temizle
        │
        └── _advance_trucks() → tüm kamyonlar için _step_truck()
                └─ en_route → servicing → returning → done → listeden çıkar
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        │
        ▼
GET /live-state → state_snapshot() → frontend harita güncelle
GET /live-kpis  → kpis_snapshot()  → dashboard KPI'ları güncelle
```

---

## 15. Karar Gerekçeleri

Bu bölümde tasarım sürecindeki kritik kararlar ve gerekçeleri özetlenmiştir.

### Neden iki paralel dünya?

Aynı kutu verisini iki farklı stratejiyle çalıştırmak, kontrollü bir A/B testi yapar. Kutu fizikleri (fill_rate, konum) sabit olduğu için tüm fark dispatch stratejisinden kaynaklanır. Bu, "algo daha iyi mi?" sorusunu nesnel olarak yanıtlar.

### Neden K-means ile 12 zone?

Zone sayısı, dispatch granülaritesini belirler. 12 zone = 3424/12 ≈ 285 kutu/zone. Çok az zone (örn. 3) → çok büyük gruplar, verimsiz rota. Çok fazla zone (örn. 50) → küçük gruplar, sık dispatch, yüksek sabit maliyet. 12, Dublin'in coğrafi ölçeğine ve 3424 kutu yoğunluğuna uygun bir orta yoldur.

### Neden ETF Horizon = 24 sim-saat?

A-label kutular 6–8 saatte dolar, B 12–25, C 67+. 24 saatlik ufuk tüm tipleri kapsar ama çok uzağa bakıp gürültülü tahminler üretmez. ETF > 24h kutular skor = 0 alır, dispatch önceliği dışında kalır.

### Neden fill_urgency kare?

Linear (fill_pct / 100) ile %90 dolu kutu %45 dolu kutudan yalnızca 2x puanlı olur. Kare ile 4x puanlı. Kritik doluluk gerçekten kritik hissettirmeli; kare bu sezgiyi matematiksel olarak yansıtır.

### Neden ağırlık-duyarlı 2-opt?

Standart 2-opt km minimize eder. Ağırlık-duyarlı 2-opt, kamyonun hafif yükle uzun bacak, ağır yükle kısa bacak yapmasını tercih eder. Gerçek dizel kamyonlarda yük ağırlığı yakıt tüketimini ciddi etkiler. Bu model sadece km değil gerçek yakıt maliyetini minimize eder.

### Neden Sweep heuristic sabit rotalar için?

Rastgele ya da salt-NN grupları gerçek belediye rotalarını temsil etmez. Sweep, radyal rota yapısıyla (kuzey rotası, güney rotası…) gerçek şehir atık operasyonlarını taklit eder. Bu sayede karşılaştırma "gerçekçi bir alternatife karşı" yapılmış olur.

### Neden MIN_DISPATCH = 8?

Tek kutuluk sefer: 2000 TL sabit + ~15 km yakıt ≈ 2200 TL. 8 kutuluk sefer: 2000 TL + yakıt ≈ 2050 TL (kutu başına ~256 TL). Toplu dispatch ekonomik.
Ama eşik çok yüksek olursa (ör. 20) taşmalar beklerken birikiyor. 8, ekonomi ile taşma önleme arasında pratik bir denge.

### Neden fixed dünya predictor'a beslenmez?

Predictor'ı yalnızca algo dünyasından beslemek iki amaca hizmet eder:
1. DPET'in kendi dispatch geçmişinden öğrenme döngüsü gerçekçidir.
2. Fixed dünyanın "kör" dispatch'i kirletilmeden temsil edilir.

---

*Bu belge EcoHaul projesinin tüm kaynak kodundan türetilmiştir. Son güncelleme: 2026-05-16.*
