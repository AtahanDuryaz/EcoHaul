# EcoHaul AI
## Yapay Zeka ve IoT Tabanlı Dinamik Atık Yönetim Sistemi

---

## Proje Özeti

EcoHaul AI, şehir çöp toplama süreçlerini gerçek zamanlı sensör verisi, makine öğrenimi tahmini ve fizik tabanlı rotalama ile optimize eden akıllı bir yönetim sistemidir.  
Temel yenilik: araç kütlesini yakıt maliyetine dahil eden **Mass-Aware Routing** algoritması ile Greedy algoritmanın seçilen zaman aralığında yan yana simüle edilerek karşılaştırılması.

> **F = m × a** — Ne kadar dolu araç, o kadar fazla enerji.

---

## Sistem Katmanları (Pipeline)

```
┌──────────────────────────────────────────────────────────────────────────┐
│  KATMAN 0 — Ham Veri                                                     │
│  Dublin Open Data CSV  →  3.425 konteyner  →  EPSG:2157 koordinatları   │
└─────────────────────────────────┬────────────────────────────────────────┘
                                  │ pandas + pyproj
┌─────────────────────────────────▼────────────────────────────────────────┐
│  KATMAN 1 — Dönüşüm ve Yükleme                                          │
│  EPSG:2157  →  WGS84 (lat/lon)  →  PostgreSQL + PostGIS                 │
└─────────────────────────────────┬────────────────────────────────────────┘
                                  │ asyncpg
┌─────────────────────────────────▼────────────────────────────────────────┐
│  KATMAN 2 — Depolama (PostgreSQL + PostGIS)                             │
│  containers │ telemetry │ event_log │ road_blocks                        │
└──────┬──────────────────────────┬───────────────────────────────────────┘
       │ ESP32 / Simülatör         │ FastAPI
       │ POST /update-fill         │ GET /bins
       │ POST /heartbeat           │
┌──────▼────────────────────────────────────────────────────────────────── ┐
│  KATMAN 3 — İşleme ve Anomali Tespiti                                   │
│  Enum sınıflandırma │ Heartbeat izleme │ Anomali tespiti │ Event loglama │
└─────────────────────────────────┬────────────────────────────────────────┘
                                  │
       ┌──────────────────────────┼─────────────────────────┐
       │                          │                         │
┌──────▼──────────┐  ┌────────────▼──────────┐  ┌──────────▼──────────────┐
│  KATMAN 4       │  │  KATMAN 5             │  │  Google Maps API        │
│  Optimizasyon   │  │  Veri Analizi & AI    │  │  Trafik + Yol Durumu   │
│  Greedy vs      │  │  1 yıllık generic set │  │  Manuel Yol Kapatma    │
│  EcoHaul        │  │  Fill tahmini + LLM   │  │  road_blocks tablosu   │
└──────┬──────────┘  └────────────┬──────────┘  └──────────┬──────────────┘
       └──────────────────────────┼────────────────────────┘
                                  │ FastAPI Gateway
┌─────────────────────────────────▼────────────────────────────────────────┐
│  KATMAN 6 — Dashboard (React + Leaflet)                                 │
│  Harita A: Greedy Simülasyonu  │  Harita B: EcoHaul Simülasyonu        │
│  Tıklanabilir kutular (random event)  │  KPI Karşılaştırma Paneli      │
└──────────────────────────────────────────────────────────────────────────┘
```

---

### Katman 0 — Ham Veri
**Kaynak:** Dublin City Council Açık Veri Portalı  
**İçerik:** 3.425 çöp konteyneri — konteyner kimliği, bölge adı, koordinatlar  
**Format:** CSV — Irish Transverse Mercator koordinat sistemi (EPSG:2157)

| Teknoloji | Görev |
|---|---|
| Dublin City Council Open Data | Veri kaynağı |
| pandas | CSV okuma ve temizleme |

**Ölçüm Kriteri:** 3.425 satır eksiksiz okundu mu? Eksik / bozuk koordinat kaydı var mı?

---

### Katman 1 — Veri Dönüşümü ve Yükleme
Ham CSV'deki Irish Grid koordinatları (EPSG:2157) harita için gereken WGS84 formatına (latitude/longitude) dönüştürülür ve PostgreSQL veritabanına yüklenir.

| Teknoloji | Görev |
|---|---|
| Python | Dönüşüm ve yükleme scripti |
| pandas | CSV okuma, temizleme ve dönüşüm |
| pyproj | EPSG:2157 → EPSG:4326 koordinat dönüşümü |
| asyncpg | PostgreSQL'e async yazma |

**Ölçüm Kriteri:** Dönüştürülen tüm koordinatlar Dublin WGS84 sınırları içinde mi? (lat: 53.20°–53.45°, lon: -6.45°– -6.05°) — Veri kaybı sıfır mı?

---

### Katman 2 — Depolama
Tüm statik ve dinamik veriler tek bir PostgreSQL veritabanında, farklı tablolarda tutulur. PostGIS eklentisi ile coğrafi sorgular (koordinat arama, alan içi sorgulama) doğrudan veritabanı üzerinden çalışır. Sistem local ortamda çalışır.

| Teknoloji | Görev |
|---|---|
| PostgreSQL 16 | Tüm veri katmanı: statik konteyner verisi, telemetri, olay logları, yol kapatmaları |
| PostGIS | PostgreSQL üzerinde coğrafi veri desteği (POINT, yakınlık sorguları) |
| asyncpg | Python'dan async PostgreSQL erişimi |

**Tablolar ve içerikleri:**

| Tablo | İçerik |
|---|---|
| `containers` | bin_id, koordinat (POINT), bölge, aktiflik durumu |
| `telemetry` | Sensör ölçümleri — bin_id, fill_level (enum), ham_cm değeri, zaman damgası (append-only) |
| `event_log` | Anomali ve sistem olayları — event_type, JSONB detay, zaman damgası |
| `road_blocks` | Manuel ve Google Maps kaynaklı yol kapatmaları — segment koordinatları, kaynak, aktiflik durumu |

**Ölçüm Kriteri:** `GET /bins` yanıt süresi ≤ 200 ms — Coğrafi yakınlık sorgusu (1 km yarıçap) ≤ 50 ms

---

### Katman 3 — İşleme ve Anomali Tespiti
Sensörden gelen ham mesafe verisi önce **Median Filter** ve **Moving Average** ile gürültüden arındırılır, ardından enum sınıfına dönüştürülür; anormal durumlar otomatik olarak tespit edilip loglanır. Implicit Heartbeat mekanizması ile sensörlerin çevrimiçi durumu izlenir.

| Teknoloji | Görev |
|---|---|
| FastAPI | REST API gateway, endpoint yönetimi |
| Uvicorn | ASGI uygulama sunucusu |
| asyncpg | PostgreSQL async erişimi |
| Python | Enum sınıflandırması, anomali tespit mantığı |

**Doluluk Enum Sınıflandırması (örnek: 1 metrelik konteyner):**

| Ham Ölçüm (cm) | Enum Değeri | Açıklama |
|---|---|---|
| 0 – 60 cm | `EMPTY` | Konteyner büyük oranda boş |
| 60 – 90 cm | `FULL` | Toplanmalı — rota önceliğine girer |
| 90+ cm | `CRITICAL` | Taşma riski — acil toplama |

> Eşik değerleri konteyner boyutuna göre konfigüre edilebilir. Her bin için `capacity_cm` parametresi veritabanında saklanır; enum hesabı bu değere göre yapılır.

**Implicit Heartbeat (Örtük Canlılık Sinyali):**
- Ayrı bir `POST /heartbeat` sinyali gönderilmez; her doluluk güncellemesi (`POST /update-fill`) otomatik olarak bir **Implicit Heartbeat** olarak kabul edilir
- Son doluluk verisi zamanı `telemetry.recorded_at` üzerinden canlılık sinyali olarak takip edilir
- 2 saat veri gelmezse `is_active = False` güncellenir, dashboard'da gri gösterilir

**Tespit edilen anomali türleri:**

| Anomali | Tetikleyici | Log Kaydı |
|---|---|---|
| Taşma riski | fill_level → CRITICAL | `OVERFLOW_RISK` |
| Yetkisiz boşaltım | Kamyon rotasında olmayan bir noktada HIGH→EMPTY geçişi | `SUSPICIOUS_EMPTYING` |
| Offline sensör | 2 saat Implicit Heartbeat (doluluk verisi) gelmemesi | `BIN_OFFLINE` |
| Rota dışı boşaltım | Tamamlanan boşaltım rota segmentiyle eşleşmiyor **veya** kamyonun anlık GPS konumu ile konteyner konumu arasındaki mesafe > 20 metre | `UNAUTHORIZED_EMPTY` |
| Anormal dolum hızı | Doluluk artış hızı, geçmiş **Habit Tracking** verisinden %X daha yüksek (karton kutu, yanlış atım vb.) | `FILL_ANOMALY` |
| Sensör sağlık hatası | Bir konteynerden gelen verinin 24 saat boyunca dolum trendine aykırı şekilde hiç değişmemesi — sensör donmuş / bozuk olabilir | `SENSOR_FIXED_VALUE_ERROR` |

> `SENSOR_FIXED_VALUE_ERROR` tetiklendiğinde ilgili konteyner otomatik olarak aktif rotadan çıkarılır ve bakım listesine (`maintenance_queue`) eklenir.

**Ölçüm Kriteri:** Anomali tespit doğruluğu ≥ %90 — Yanlış pozitif oranı ≤ %10 — Heartbeat kaybı tespiti ≤ 2 dakika

---

### Katman 4 — Optimizasyon ve Trafik Yönetimi
İki farklı rotalama algoritması, kullanıcının seçtiği zaman aralığı için aynı konteyner seti üzerinde paralel çalıştırılır ve karşılaştırılır. Rota hesabına gerçek zamanlı trafik ve manuel yol kapatmaları dahil edilir.

| Teknoloji | Görev |
|---|---|
| Python | Algoritma implementasyonu |
| FastAPI | `/routes/ecohaul`, `/routes/greedy`, `/routes/compare` endpoint'leri |
| Google Maps Directions API | Gerçek zamanlı trafik — yol kapatmaları, yoğunluk, seyahat süresi |
| Google Maps Roads API | Segment bazlı hız limiti ve trafik durumu |
| PostgreSQL `road_blocks` | Manuel / Google Maps kaynaklı kapalı segmentlerin saklanması |

**EcoHaul (Mass-Aware) Algoritması:**  
Araç kütlesi sefer boyunca birikerek maliyet fonksiyonunu etkiler. Araç boşken uzak / doluluk oranı yüksek noktalara, dolarken depoya yakın noktalara yönlendirilir.

$$C_{ij} = (m_{base} + m_{current}) \times d_{ij} + P_{stop}$$

> **$P_{stop}$** — Idling (Dur-Kalk) Katsayısı: Kamyonun her konteyner noktasında durması motor rölantisi, frenleme ve yeniden ivmelenme kaynaklı ek yakıt tüketimi doğurur. Bu sabit maliyet terimi her ziyaret noktası için toplam maliyete eklenir.
>
> Bu parametre, algoritmanın **"az dolu" kutular için durma maliyetini gitme maliyetiyle kıyaslamasını** sağlar: eğer bir konteynerin doluluk oranı düşükse ve $P_{stop}$ bu noktada durmayı toplam maliyet açısından kârsız kılıyorsa, algoritma o konteyneri atlayarak rotayı optimize eder. Böylece gereksiz dur-kalk manevraları hem yakıt hem zaman kaybı olarak maliyet fonksiyonuna yansıtılmış olur.

**Karşılaştırma Modelleri:**

| Model | Açıklama |
|---|---|
| **Greedy** | Yalnızca mesafe minimize edilir — araç kütlesi, trafik ve idling maliyeti göz ardı edilir; deterministik karşılaştırma referansı |
| **Static Route (Belediye Standart Rota)** | Sabit, önceden belirlenmiş belediye rotası — gerçek zamanlı doluluk, araç kütlesi veya trafik durumu dikkate alınmaz |

**Zaman Aralığı Seçimi:**  
Dashboard üzerinden başlangıç ve bitiş saati seçilir. Her iki algoritma yalnızca bu zaman diliminde FULL veya CRITICAL olan konteynerleri kapsayan rota üretir.

**Manuel Yol Kapatma Akışı:**
1. Operatör haritada bir yol segmentine tıklar → "Bu yolu kapat" butonu
2. `POST /road-blocks` çağrısı → `road_blocks` tablosuna yazılır
3. Optimizasyon motoru bu segmenti rota hesabından dışlar
4. Dashboard güncellenen rotayı anında gösterir
5. Kapatma kaldırılınca yol tekrar rota havuzuna girer

**Ölçüm Kriteri:** EcoHaul, seçilen zaman aralığında Greedy'ye kıyasla ≥ %15 yakıt ve ≥ %15 CO₂ tasarrufu sağlamalı — Kapalı yol senaryosunda rota doğru alternatiften geçmeli

---

### Katman 5 — Veri Analizi ve Yapay Zeka
Tarihsel sensör verisi ve 1 yıllık generic veri seti ile makine öğrenimi modeli eğitilir; konteyner doluluk davranışı tahmin edilir. Sürücüye doğal dil desteği sunan AI Co-Pilot aynı katmanda çalışır.

| Teknoloji | Görev |
|---|---|
| scikit-learn | Doluluk tahmin modeli (Random Forest / LightGBM) |
| pandas | Feature engineering, eğitim verisi hazırlama |
| LLM API | Doğal dil sürücü asistanı (Co-Pilot) |
| Python | Model eğitimi, tahmin servisi |

**Eğitim Verisi:**
- **Gerçek IoT verisi:** 3 fiziksel modülden toplanan doluluk logları
- **Generic veri seti:** 1 yıllık simüle edilmiş doluluk davranışı — farklı bölge profilleri, günlük/haftalık döngüler, mevsimsel varyasyonlar

**Feature Engineering:**

| Özellik | Açıklama |
|---|---|
| `hour_of_day` | Günün saati (0–23) |
| `day_of_week` | Haftanın günü (0–6) |
| `is_weekend` | Hafta sonu ikili değişken |
| `hours_since_last_empty` | Son boşaltımdan bu yana geçen süre |
| `region_encoded` | Bölge (label encoding) |
| `rolling_fill_rate` | Son 3 ölçümün dolma hız trendi |

**Model Çıktısı:** "Bu konteyner yaklaşık X saat içinde CRITICAL seviyeye ulaşacak" → Dashboard'da turuncu uyarı ikonu

**AI Co-Pilot — Veri Sorgulama ve Karar Destek Arayüzü (Text-to-SQL):**  
Sürücü yalnızca operasyonel sorgular için bu arayüzü kullanır (Örn: *"En yakın kritik konteyner nerede?"*, *"Bu bölgede kaç FULL konteyner var?"*). Sistem soruyu **Text-to-SQL** ile veritabanı sorgusuna çevirir ve yapılandırılmış yanıt üretir. Bu, kural tabanlı ve denetlenebilir bir karar destek mekanizmasıdır; sürücüye güvenli operasyonel bilgi sunar.  
XAI: *"Neden bu rotaya gidiyoruz?"* sorusuna F = m × a formülü referanslı açıklama üretilir.

**Ölçüm Kriteri:** Doluluk tahmin doğruluğu ≥ %75 — Co-Pilot intent sınıflandırma doğruluğu ≥ %85

---

### Katman 6 — Dashboard ve Simülasyon
Tüm sistem verisi tek arayüzde görselleştirilir. **İki bağımsız harita** yan yana çalışır — biri Greedy, biri EcoHaul simülasyonunu gösterir. Operatör kutulara tıklayarak manuel event oluşturabilir; sistem bu eventleri rota geçmişiyle doğrular.

| Teknoloji | Görev |
|---|---|
| React 18 | Component tabanlı kullanıcı arayüzü |
| Vite 5 | Geliştirme sunucusu ve build aracı |
| react-leaflet 4 | GIS harita, CircleMarker, Polyline, trafik katmanları |
| axios | FastAPI'ye HTTP istekleri |
| Zustand | Global state — zaman aralığı, katman görünürlükleri, KPI, yol durumu |

**İkili Harita Yapısı:**

| Harita A — Greedy Simülasyonu | Harita B — EcoHaul Simülasyonu |
|---|---|
| Greedy algoritması rotası (kırmızı çizgi) | EcoHaul Mass-Aware rotası (mavi çizgi) |
| Kamyon konumu simüle edilir | Kamyon konumu simüle edilir |
| Toplanan konteynerler yeşile döner | Toplanan konteynerler yeşile döner |
| Aynı zaman aralığı, aynı konteyner seti | Aynı zaman aralığı, aynı konteyner seti |

**Tıklanabilir Konteyner — Event Sistemi:**
- Haritada herhangi bir konteynere tıklandığında bir panel açılır
- Panel: doluluk geçmişi grafiği, son heartbeat zamanı, bölge bilgisi
- "Random Event Oluştur" butonu: simülasyon sırasında o konteynere rastgele doluluk değişimi enjekte eder
- Boşaltım doğrulama: Bir konteyner EMPTY durumuna geçtiğinde sistem o konteynerin **kamyon rotası segmentinde olup olmadığını** kontrol eder
  - ✅ Rota üzerindeyse → Geçerli boşaltım, `status = OK` olarak güncellenir
  - ⚠️ Rota dışındaysa → `UNAUTHORIZED_EMPTY` anomalisi loglanır, operatöre uyarı gösterilir

**KPI Karşılaştırma Paneli:**  
Her iki simülasyon tamamlandıktan sonra (seçilen zaman aralığı sonunda) yan yana KPI tablosu gösterilir.

| KPI Metriği | Static Route | Greedy | EcoHaul |
|---|---|---|---|
| Toplam Mesafe (km) | — | — | — |
| Tahmini Yakıt (L) | — | — | — |
| CO₂ Emisyonu (kg) | — | — | — |
| Rota Süresi (dk) | — | — | — |
| Ziyaret Edilen Konteyner | — | — | — |
| Enerji Verimliliği (kg atık/L) | — | — | — |
| Enerji Verimliliği (Ton-Kilometre başına yakıt) | — | — | — |

**Diğer Harita Özellikleri:**
- Renk kodu: Yeşil (EMPTY) / Sarı (FULL) / Kırmızı (CRITICAL) / Gri (çevrimdışı) / Turuncu (tahmin uyarısı)
- Kapalı yollar kırmızı kesik çizgi ile gösterilir
- Google Maps trafik durumu overlay olarak haritaya yansıtılır
- Tahmin katmanı — dolmak üzere olan konteynerler turuncu işaretlenir

**Ölçüm Kriteri:** Harita yükleme süresi ≤ 2 saniye — 3.425 marker akıcı render — Manuel yol kapatma → rota güncellemesi ≤ 3 saniye — Boşaltım doğrulama kontrolü gerçek zamanlı

---

## IoT Katmanı

Sistemde **3 fiziksel ESP32 modülü** gerçek çöp kutularına entegre edilir. Kalan 3.422 konteyner için `iot_simulator.py` ile generic veri seti tabanlı simülasyon çalışır.

| Teknoloji | Görev |
|---|---|
| ESP32 Mikrodenetleyici | Sensör okuma, Wi-Fi üzerinden API'ye veri gönderme |
| HC-SR04 Ultrasonik Sensör | Konteyner içi mesafe ölçümü (cm cinsinden) |
| MicroPython | ESP32 firmware |
| FastAPI `/update-fill` | Enum sınıflandırılmış doluluk verisi alımı + Implicit Heartbeat |
| `iot_simulator.py` | 3.422 sanal konteyner için zaman profilli generic simülasyon |

**Veri Akışı — Olay Tabanlı Örnekleme (Deep Sleep Destekli):**
```
[Saat başı uyanma]
  → HC-SR04: 30 sn boyunca 10 ölçüm al
  → Median Filter: medyan değeri hesapla (gürültü / karton kutu engeli filtrele)
  → ESP32: enum dönüşümü (EMPTY / FULL / CRITICAL)
  → POST /update-fill  ← Implicit Heartbeat (ayrı /heartbeat sinyali yok)
  → FastAPI → PostgreSQL telemetry
  → Deep Sleep moduna dön (sonraki saate kadar)
```

**Hata Toleransı ve Bağlantı Yönetimi:**
- **Exponential Backoff:** HTTP 200 yanıtı gelmemesi durumunda ESP32, 3 kez artan aralıklarla (1 sn → 2 sn → 4 sn) yeniden deneme yapar
- **Yerel Bellek (SPIFFS/LittleFS):** Tüm denemeler başarısız olursa veri kaybedilmez; ölçüm zaman damgasıyla birlikte cihaz üzerindeki flash belleğe yazılır ve bağlantı sağlandığında sıra bekler
- **Hardware Watchdog Timer (WDT):** Ağ kilitlenmelerini önlemek için donanımsal WDT etkinleştirilmiştir; bağlantı girişimi 20 saniyeyi aşarsa cihaz otomatik olarak yeniden başlayarak operasyona devam eder
- **Edge Processing:** Ham ultrasonik verideki gürültü backend yükünü azaltmak amacıyla doğrudan ESP32 üzerinde Median Filter ile elenir; yalnızca filtrelenmiş medyan değer API'ye gönderilir

**Generic Simülasyon Profili (iot_simulator.py):**

| Zaman Dilimi | Dolma Olasılığı |
|---|---|
| 00:00 – 06:00 | %2 (gece) |
| 06:00 – 09:00 | %15 (sabah yoğunluğu) |
| 09:00 – 18:00 | %8 (gündüz normal) |
| 18:00 – 22:00 | %20 (akşam yoğunluğu) |
| 22:00 – 00:00 | %5 (gece geç) |

**Ölçüm Kriteri:** Sensör → API gecikmesi ≤ 500 ms — Heartbeat kayıp tespiti ≤ 2 dakika — 3 fiziksel modül ≥ %95 uptime

---

## Genel Teknoloji Yığını

| Katman | Teknoloji |
|---|---|
| Backend | Python, FastAPI, Uvicorn |
| Veritabanı | PostgreSQL 16, PostGIS |
| IoT (Fiziksel) | ESP32, HC-SR04, MicroPython |
| IoT (Simülasyon) | Python `iot_simulator.py`, generic 1 yıllık veri seti |
| Veri İşleme | pandas, pyproj |
| Harita & Trafik | Google Maps Directions API, Google Maps Roads API, react-leaflet |
| Yapay Zeka | scikit-learn (Random Forest / LightGBM), LLM API |
| Frontend | React 18, Vite 5, react-leaflet 4, axios, Zustand |
| Test | pytest, httpx, pytest-asyncio |

---

## Başarı Kriterleri Özeti

| Kriter | Hedef |
|---|---|
| Yakıt Tasarrufu (EcoHaul vs Greedy) | ≥ %15 |
| CO₂ Emisyonu Azaltımı | ≥ %15 |
| Anomali Tespit Doğruluğu | ≥ %90 |
| Doluluk Tahmin Doğruluğu | ≥ %75 |
| Co-Pilot Intent Doğruluğu | ≥ %85 |
| API Yanıt Süresi | ≤ 200 ms |
| Harita Yükleme Süresi | ≤ 2 saniye |
| Boşaltım Doğrulama Hızı | Gerçek zamanlı |
| IoT Fiziksel Modül Uptime | ≥ %95 |

---

*EcoHaul AI — CSE-492 Bitirme Projesi — Mart 2026*
