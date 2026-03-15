# EcoHaul AI — Test ve Demo Rehberi
## CSE-492 Bitirme Projesi · Mart 2026

**Hedef:** IoT alanında uzman hocaya sistemin her katmanını kanıtlamak.  
**Demo formatı:** Canlı sunum (15–20 dk) + OBS yedek video kaydı  
**Hibrit yapı:** ~300 kutunun bir kısmı gerçek ESP32 + JSN-SR04T,  
kalanı `iot_simulator.py` ile yazılımsal simülasyon.

---

## Demo Akışı (15–20 Dakika)

| # | Adım | Süre | Ne Gösteriyor |
|---|---|---|---|
| 1 | Sistem başlatma | 2 dk | Mimari güvenilirliği |
| 2 | Fiziksel sensör canlı demo | 3 dk | Gerçek IoT donanımı |
| 3 | Offline tespiti (WiFi kes) | 2 dk | Heartbeat mekanizması |
| 4 | Anomali: seviye atlama | 2 dk | Akıllı anomali motoru |
| 5 | Algoritma karşılaştırması | 3 dk | Mass-Aware vs Greedy KPI |
| 6 | Co-Pilot XAI | 3 dk | AI + F=m×a açıklaması |
| 7 | pytest canlı çalıştırma | 2 dk | Otomatik test kanıtı |

---

## BÖLÜM 1 — Fiziksel Sensör Doğruluk Testleri

### Temel Formüller

$$distance_{cm} = \frac{t_{echo}[\mu s] \times 0.0343}{2}$$

$$fill\% = \frac{BIN\_HEIGHT - distance_{cm}}{BIN\_HEIGHT} \times 100$$

### Test Tablosu

| # | Test Adı | Nasıl Yapılır | Beklenen Sonuç | Demo'da Gösterim |
|---|---|---|---|---|
| T-H1 | **Mesafe doğruluğu** | Cetvel ile 30 / 50 / 70 cm mesafeye nesne koy | Serial: `~30 cm ± 3 cm` | Serial monitor ekrana yansıtılır |
| T-H2 | **Sınır: LOW → MEDIUM** | Konteynerin tam %33 doluluk noktasına nesne koy | `fill_level = "MEDIUM"` → harita sarıya döner | Canlı harita renk değişimi |
| T-H3 | **Sınır: MEDIUM → HIGH** | %66 doluluk noktasına nesne koy | `fill_level = "HIGH"` → harita kırmızıya döner, alert | Canlı alert pop-up |
| T-H4 | **Medyan filtresi gürültü direnci** | Ölçüm sırasında elinle kısa süre önünü kapat | Tek aykırı ölçüm `fill_level`'ı değiştirmiyor | Serial'de 5 ölçüm + medyan görünür |
| T-H5 | **Sensör arıza tespiti** | ECHO pinini yerinden çek | Serial: `"Sensör okuma hatası"` — HTTP gönderilmiyor | Haritada kutu eski renginde kalıyor |
| T-H6 | **Aşırı doluluk (overflow)** | Sensöre 3 cm mesafeye nesne koy | `fill_pct > 100%` → yine `HIGH` gönderilir, hata değil | `event_log`'da `OVERFLOW_RISK` |

### Neden Önemli?

JSN-SR04T ile HC-SR04 arasındaki tercih gerekçesi: **IP65 su geçirmez gövde** —
açık hava çöp kutularında nem ve yağmura dayanıklılık kritiktir.
HC-SR04 tahtası tamamen açıktır; konteyner içi buharlanmada hızla arıza verir.

---

## BÖLÜM 2 — Firmware & Deep Sleep Testleri

### Temel Tasarım Kararı — RTC Bellek

Deep sleep sırasında SRAM silinir. `RTC_DATA_ATTR` ile son `fill_level`
RTC belleğe yazılır:

```
SRAM silinse de  →  RTC_DATA_ATTR char last_fill_level[10] = "LOW"  →  hayatta kalır
```

**Eğer yazmasaydık:** Her boot `LOW` ile kıyaslanırdı → `LOW→HIGH` gibi yanlış
`FILL_SKIP_ANOMALY` eventleri tetiklenirdi.

### Test Tablosu

| # | Test Adı | Nasıl Yapılır | Beklenen Sonuç |
|---|---|---|---|
| T-F1 | **RTC bellek kalıcılığı** | `MEDIUM` gönder → güç kes → geri ver | Boot #2: `last_fill_level="MEDIUM"` — `/update-fill` tekrar gönderilmiyor |
| T-F2 | **Deep sleep timing** | İki boot arasını saat ile ölç | `~60 sn ± 2 sn` |
| T-F3 | **Fill-change-only POST** | 3 boot boyunca aynı fill seviyesini koru | Serial: `"update-fill atlandı"` — PostgreSQL'de yeni satır YOK |
| T-F4 | **WiFi retry (yanlış şifre)** | Yanlış SSID gir | 3 deneme → `"Bağlantı BAŞARISIZ"` → 5 dk deep sleep |
| T-F5 | **Exponential backoff** | Backend'i durdur (`uvicorn` kapat) | Serial: `Deneme 1` → 2 sn → `Deneme 2` → 4 sn → deep sleep |

### Hibrit Mod Doğrulama

```sql
-- ESP32'den gelen gerçek veri ile simülatörden gelen veriyi ayırt et
SELECT bin_id, fill_level, recorded_at,
       CASE WHEN bin_id = 'WMS4505' THEN 'ESP32 (Gerçek)'
            ELSE 'Simülatör'
       END AS kaynak
FROM telemetry
ORDER BY recorded_at DESC
LIMIT 20;
```

---

## BÖLÜM 3 — 9 Anomali Senaryosu (Tam Geçiş Matrisi)

### Kamyon Tespiti — PostGIS ile

```sql
-- 100m yarıçapında kamyon var mı?
SELECT COUNT(*) FROM truck_telemetry
WHERE ST_DWithin(
    ST_MakePoint(lon, lat)::geography,
    (SELECT geom::geography FROM bins WHERE bin_id = $1),
    100
)
AND sim_timestamp > NOW() - INTERVAL '15 minutes';
```

### 9 Senaryo

| # | Geçiş | Kamyon? | `event_type` | pytest Test Adı |
|---|---|---|---|---|
| T-A1 | LOW → MEDIUM | — | *(event yok — normal)* | `test_normal_transition` |
| T-A2 | MEDIUM → HIGH | — | `OVERFLOW_RISK` | `test_overflow_risk` |
| T-A3 | LOW → HIGH | — | `FILL_SKIP_ANOMALY` | `test_fill_skip_anomaly` |
| T-A4 | HIGH → LOW | ✅ 100m içinde | `COLLECTION_COMPLETE` | `test_collection_with_truck` |
| T-A5 | HIGH → LOW | ❌ | `SUSPICIOUS_EMPTYING` | `test_suspicious_no_truck` |
| T-A6 | HIGH → MEDIUM | ✅ | `COLLECTION_COMPLETE` | `test_partial_collection` |
| T-A7 | HIGH → MEDIUM | ❌ | `SUSPICIOUS_EMPTYING` | `test_suspicious_partial` |
| T-A8 | MEDIUM → LOW | ✅ | `COLLECTION_COMPLETE` | `test_medium_collected` |
| T-A9 | MEDIUM → LOW | ❌ | `SUSPICIOUS_EMPTYING` | `test_medium_suspicious` |

### Demo'da Nasıl Gösterilir?

```bash
# Testleri hoca önünde çalıştır
pytest tests/test_phase2.py -v
```

```
Beklenen çıktı:
  tests/test_phase2.py::test_normal_transition         PASSED
  tests/test_phase2.py::test_overflow_risk             PASSED
  tests/test_phase2.py::test_fill_skip_anomaly         PASSED
  tests/test_phase2.py::test_collection_with_truck     PASSED
  tests/test_phase2.py::test_suspicious_no_truck       PASSED
  tests/test_phase2.py::test_partial_collection        PASSED
  tests/test_phase2.py::test_suspicious_partial        PASSED
  tests/test_phase2.py::test_medium_collected          PASSED
  tests/test_phase2.py::test_medium_suspicious         PASSED
  9/9 PASSED ✓
```

```sql
-- Canlı event log sorgusu
SELECT bin_id, event_type,
       detail->>'previous_fill' AS onceki,
       detail->>'new_fill'      AS sonraki,
       created_at
FROM event_log
ORDER BY created_at DESC
LIMIT 10;
```

---

## BÖLÜM 4 — Heartbeat & Offline Tespit Mekanizması

### Matematik — Neden 60 Saniye?

$$T_{offline} = T_{tick} \times 3 = 30 \text{ sn} \times 3 = 90 \text{ sn}$$

$$T_{ESP32\_sleep} = 60 \text{ sn} < 90 \text{ sn} \implies \text{1 paket kaybında BIN\_OFFLINE tetiklenmez}$$

**Sonuç:** 1 paket kaybı olursa miss sayacı 1'e çıkar ama 3'e ulaşmaz → sistem
ağ paket kaybına toleranslı tasarlanmıştır.

```
t=0      t=60     t=120    t=150
│        │        │        │
[Ping]  [Ping]  [KAYIP]  [Ping]   ← ESP32 (her 60 sn)
o────────o────────o────────o       ← Backend tick (her 30 sn)
miss=0   miss=0   miss=1   miss=0  ← ONLINE kalır ✓
```

### Test Tablosu

| # | Test Adı | Nasıl Yapılır | Beklenen Sonuç |
|---|---|---|---|
| T-B1 | **3-loop miss → BIN_OFFLINE** | ESP32'yi veya o bin_id'nin simülatörünü durdur | 90 sn sonra `bins.is_active = FALSE`, `event_log`'da `BIN_OFFLINE` |
| T-B2 | **1–2 miss toleransı** | Ağı 60 sn kes, geri ver | Miss sayacı 1–2'ye çıkar ama `is_active = TRUE` kalır |
| T-B3 | **Write optimizasyonu** | Zaten `TRUE` olan kutuya heartbeat gönder | DB write YOK (`TRUE→TRUE` değişim değil) |
| T-B4 | **BIN_ONLINE eventi** | Offline kutuya heartbeat gelince | `is_active = FALSE → TRUE` + `event_log`'da `BIN_ONLINE` |

### Canlı Demo Adımları

```
1. ESP32'nin WiFi SSID'sini yanlış yap (veya router'ı kapat)
2. Dashboard'u izle
3. ~90 saniye sonra ilgili kutu griye döner
4. PostgreSQL'de göster:
```

```sql
SELECT * FROM event_log
WHERE event_type = 'BIN_OFFLINE'
ORDER BY created_at DESC LIMIT 3;
```

```
5. WiFi'yi geri ver → ~60 sn sonra kutu tekrar renkleniyor
6. PostgreSQL'de göster:
```

```sql
SELECT * FROM event_log
WHERE event_type = 'BIN_ONLINE'
ORDER BY created_at DESC LIMIT 1;
```

---

## BÖLÜM 5 — API Entegrasyon ve Performans Testleri

### Test Tablosu

| # | Test Adı | pytest / SQL | Başarı Kriteri |
|---|---|---|---|
| T-I1 | **`/update-fill` → PostgreSQL kayıt** | `test_fill_update_postgresql` | `telemetry` tablosunda yeni satır var |
| T-I2 | **`/heartbeat` → `is_active` güncelleme** | `test_heartbeat_updates_active` | `bins.is_active = TRUE` |
| T-I3 | **Geçersiz fill_level → 422** | `test_invalid_fill_level_422` | HTTP 422 |
| T-I4 | **Bilinmeyen bin_id → 404** | `test_unknown_bin_id_404` | HTTP 404 |
| T-I5 | **50 eşzamanlı POST** | `test_concurrent_50_posts` | 0 hata, race condition yok |
| T-I6 | **GET /bins latency** | `test_get_bins_latency` | ≤ 200ms (PostGIS GiST index) |

### 300 Bin Hibrit Yük Testi

```python
# asyncio ile 300 eşzamanlı heartbeat simülasyonu
import asyncio, httpx

async def send_heartbeat(bin_id):
    async with httpx.AsyncClient() as client:
        await client.post("http://localhost:8000/heartbeat",
                          json={"bin_id": bin_id}, timeout=5)

async def main():
    bin_ids = [f"WMS{4000+i}" for i in range(299)] + ["WMS4505"]  # Son kutu gerçek ESP32
    await asyncio.gather(*[send_heartbeat(b) for b in bin_ids])
    print("300 heartbeat gönderildi")

asyncio.run(main())
```

**Beklenen:** Backend 300 eşzamanlı isteği < 500ms içinde işler.

---

## BÖLÜM 6 — Mass-Aware Rotalama Algoritması Testleri

### Temel Formül

$$C_{ij} = (m_{base} + m_{current}) \times d_{ij} \times \alpha_{ij}$$

$$\alpha_{ij} = 1 + \max\left(0, \frac{\Delta elevation}{100}\right) \times 0.15$$

**Fiziksel anlam:** Dolu araç uzağa giderse enerji katlanarak artar.
EcoHaul boşken uzağa gider, dolarken depoya yaklaşır.

### Test Tablosu

| # | Test Adı | Ne Kontrol Ediyor | Beklenen Sonuç |
|---|---|---|---|
| T-R1 | **Yüklü araç maliyeti > Boş araç** | `test_mass_cost_increases_with_load` | 8000 kg yüklü maliyet > 0 kg yüklü maliyet |
| T-R2 | **EcoHaul Greedy'den az yakıt** | `test_ecohaul_beats_greedy_fuel` | Deterministik 20-bin seti ile EcoHaul ≥ %15 tasarruf |
| T-R3 | **Tüm HIGH bin'ler rotada** | `test_route_covers_all_high_bins` | Çıktı rotada her `HIGH` bin_id mevcut |
| T-R4 | **Yokuş yukarı cezası** | `test_elevation_alpha_uphill` | `α > 1.0` |
| T-R5 | **Yokuş aşağı ceza yok** | `test_elevation_alpha_downhill` | `α = 1.0` |
| T-R6 | **Kapasite dolunca depoya dön** | `test_depot_return_on_capacity` | `m_current ≥ capacity_kg` → sonraki nokta depo koordinatı |

### Demo'da KPI Karşılaştırması

```bash
curl http://localhost:8000/routes/compare
```

```json
{
  "bin_count": 47,
  "ecohaul": {
    "total_distance_km": 42.3,
    "estimated_fuel_liters": 18.2,
    "co2_kg": 48.8,
    "duration_min": 138
  },
  "greedy": {
    "total_distance_km": 51.7,
    "estimated_fuel_liters": 24.8,
    "co2_kg": 66.5,
    "duration_min": 165
  },
  "savings": {
    "fuel_percent": 26.6,
    "co2_kg": 17.7,
    "time_min": 27
  }
}
```

---

## BÖLÜM 7 — Doluluk Tahmin Modeli Testleri

### Model Mimarisi

- **Algoritma:** `RandomForestRegressor` (scikit-learn)
- **Çıktı:** `hours_until_high` — kaç saat içinde HIGH'a ulaşacak (regresyon)
- **Hedef:** MAE ≤ 2 saat

### Feature'lar

| Feature | Tip | Açıklama |
|---|---|---|
| `hour_of_day` | int 0–23 | Ölçüm saati |
| `day_of_week` | int 0–6 | Haftanın günü |
| `is_weekend` | bool | Hafta sonu mu? |
| `hours_since_last_empty` | float | Son `LOW`'dan bu yana geçen saat |
| `region_encoded` | int | Bölge etiketi (LabelEncoder) |
| `rolling_fill_rate` | int 0–3 | Son 3 ölçümde kaç kez dolma oldu |

### Test Tablosu

| # | Test Adı | Başarı Kriteri |
|---|---|---|
| T-P1 | **Model doğruluğu** | MAE ≤ 2 saat (test seti) |
| T-P2 | **`GET /predictions` endpoint** | 200 OK, liste boş değil |
| T-P3 | **Tahmin sıralaması mantıklı** | `rolling_fill_rate = 3` olan bin → daha kısa `hours_until_high` |
| T-P4 | **Dashboard overlay** | 0–2 saatlik kutular büyük turuncu halka; 2–6 saat küçük |

```bash
curl http://localhost:8000/predictions | python -m json.tool
```

---

## BÖLÜM 8 — Co-Pilot & XAI Testleri

### 5 Intent Senaryosu

| # | Kullanıcı Cümlesi | Intent | Sistem Aksiyonu |
|---|---|---|---|
| T-C1 | *"Neden bu yola gidiyoruz?"* | `EXPLAIN_ROUTE` | F=m×a formülüyle bölge seçim gerekçesi |
| T-C2 | *"O'Connell kapalı"* | `ROAD_BLOCKED` | ORS'e `avoid_polygon` gönder → yeni rota |
| T-C3 | *"Kaç tane dolu kutu var?"* | `STATUS_QUERY` | `SELECT COUNT(*) WHERE fill_level='HIGH'` cevabı |
| T-C4 | *"Bugün kaç yakıt harcadık?"* | `KPI_QUERY` | PostgreSQL'den günlük maliyet toplamı |
| T-C5 | *"En yakın boşaltma istasyonu nerede?"* | `FACILITY_QUERY` | PostGIS yakın nokta sorgusu |

### XAI Açıklama Örneği (Demo'da Ekranda Gözükecek)

```
"Ballybough bölgesine önce gidiyoruz çünkü:
  1. 2 HIGH seviye kutu — acil toplama gerekiyor.
  2. Araç şu an boş (0 kg yük) → F = m × a formülüne göre
     uzağa gitmenin enerji maliyeti en düşük bu noktada.
  3. Bölge yüksekte → boşken çıkmak, doluyken çıkmaktan
     %23 daha az enerji tüketiyor."
```

```bash
pytest tests/ -k "copilot" -v
# test_copilot_intent_explain    PASSED
# test_copilot_road_blocked      PASSED
# test_xai_formula_reference     PASSED
```

---

## BÖLÜM 9 — Güç Tüketimi Doğrulama

### Teorik Hesap

| Durum | Akım | Süre | Enerji |
|---|---|---|---|
| Boot + WiFi bağlantı | ~220 mA | 1 sn | ~61 µAh |
| Ultrasonik ölçüm + HTTP TX | ~200 mA | 2 sn | ~111 µAh |
| Deep sleep | ~10 µA | 57 sn | ~0.16 µAh |
| **Toplam / döngü** | — | **60 sn** | **~0.172 mAh** |

$$\text{Günlük tüketim} = \frac{60}{60} \times 60 \times 0.172 \approx 10.33 \text{ mAh/gün}$$

$$\text{Pil ömrü} = \frac{2200 \text{ mAh}}{10.33 \text{ mAh/gün}} \approx 213 \text{ gün} \approx 7 \text{ ay}$$

### Fiziksel Ölçüm Testleri

| # | Test | Araç | Beklenen |
|---|---|---|---|
| T-PW1 | **Aktif akım** | USB ammetre / mültimetre (VIN hattına seri bağla) | WiFi TX sırasında `~160–220 mA` |
| T-PW2 | **Deep sleep akımı** | Mültimetre µA modu | `~10 µA` |
| T-PW3 | **Gerçek pil ömrü tahmini** | Ölçülen değerlerle formül tekrar hesapla | Teorik ≈ gerçek ±%20 |

---

## BÖLÜM 10 — Sistem ve Ölçek Testleri

| # | Test | pytest Komutu | Başarı Kriteri |
|---|---|---|---|
| T-S1 | **GET /bins latency** | `test_get_bins_latency` | ≤ 200ms |
| T-S2 | **50 eşzamanlı POST** | `test_concurrent_fill_updates` | 0 veri kaybı |
| T-S3 | **ORS routing süresi** | `test_ors_response_time` | 47 durak ≤ 2 sn |
| T-S4 | **30 gün simülasyon tutarlılığı** | `test_30_day_sim_consistency` | Tüm sayılar tutarlı |
| T-S5 | **Hibrit 300 bin eşzamanlı heartbeat** | `python tests/load_test_heartbeat.py` | < 500ms, 0 hata |

---

## Tam pytest Komutu (Demo Sırasında Çalıştır)

```bash
pytest tests/ -v --tb=short
```

```
======================== test session starts ========================
tests/test_phase1.py::test_coordinate_bounds         PASSED
tests/test_phase1.py::test_bin_count                 PASSED
tests/test_phase1.py::test_postgis_geometry          PASSED
tests/test_phase1.py::test_fill_level_default        PASSED
tests/test_phase1.py::test_get_bins_200              PASSED
tests/test_phase2.py::test_fill_skip_anomaly         PASSED
tests/test_phase2.py::test_overflow_risk             PASSED
tests/test_phase2.py::test_normal_transition         PASSED
tests/test_phase2.py::test_collection_with_truck     PASSED
tests/test_phase2.py::test_suspicious_no_truck       PASSED
tests/test_phase2.py::test_3_loop_miss_offline       PASSED
tests/test_phase2.py::test_miss_counter_reset        PASSED
tests/test_phase3.py::test_mass_cost_increases       PASSED
tests/test_phase3.py::test_ecohaul_beats_greedy      PASSED
tests/test_phase3.py::test_route_covers_all_high     PASSED
tests/test_phase3.py::test_elevation_alpha_uphill    PASSED
tests/test_phase3.py::test_elevation_alpha_downhill  PASSED
tests/test_phase3.py::test_depot_return_on_capacity  PASSED
...
======================== 36+ passed in ~8s ========================
```

---

## Kritik PostgreSQL Sorguları (Demo'da Canlı Göster)

```sql
-- 1. Son 5 dakikada gelen veriler (hibrit: ESP32 + simülatör karışık)
SELECT bin_id, fill_level, status, recorded_at
FROM telemetry
WHERE recorded_at > NOW() - INTERVAL '5 minutes'
ORDER BY recorded_at DESC;

-- 2. Anomali log'ları (event tipi + önceki/sonraki durum)
SELECT bin_id, event_type,
       detail->>'previous_fill' AS onceki,
       detail->>'new_fill'      AS sonraki,
       created_at
FROM event_log
ORDER BY created_at DESC
LIMIT 10;

-- 3. Anlık HIGH bin sayısı
SELECT COUNT(*) AS high_bin_sayisi
FROM bins
WHERE fill_level = 'HIGH' AND is_active = TRUE;

-- 4. Offline kutular
SELECT bin_id, region
FROM bins
WHERE is_active = FALSE;

-- 5. Bölgeye göre doluluk dağılımı
SELECT region, fill_level, COUNT(*) AS adet
FROM bins
WHERE is_active = TRUE
GROUP BY region, fill_level
ORDER BY region, fill_level;
```

---

## E2E Demo Checklist (Sunum Öncesi Kontrol)

| # | Kontrol | Kriter |
|---|---|---|
| E1 | Sistem başlatma | `uvicorn` + `npm run dev` hatasız ayakta |
| E2 | Harita yüklenme | ≤ 2 sn |
| E3 | 3.425 bin görünüyor | Yeşil CircleMarker'lar |
| E4 | Popup çalışıyor | `bin_id`, `region`, `fill_level` |
| E5 | ESP32 Serial monitor | Mesafe ölçümü görünüyor |
| E6 | Fiziksel sensör → harita | Konteynere nesne koyunca renk değişiyor |
| E7 | Simülatör aktif | Bin'ler dolmaya başlıyor |
| E8 | İlk HIGH bin | Kırmızı flash + alert |
| E9 | Offline demo | 90 sn → gri ikon |
| E10 | `FILL_SKIP_ANOMALY` | `event_log`'da görünüyor |
| E11 | EcoHaul rotası | Mavi polyline, gerçek yol |
| E12 | Greedy rotası | Kırmızı polyline, farklı |
| E13 | KPI panel | ≥ %15 yakıt tasarrufu |
| E14 | Kamyon animasyonu | Polyline üzerinde smooth hareket |
| E15 | Tahmin overlay | Dolacak bin'ler turuncu halka |
| E16 | Co-Pilot XAI | "F=m×a" geçen Türkçe açıklama |
| E17 | Yol kapatma | Yeni rota + kırmızı polygon |
| E18 | pytest çalıştır | Tüm testler yeşil |
| E19 | OBS kayıt hazır | Yedek video aktif |
| E20 | Pil / güç | Demo makinesi prizde veya tam şarjlı |

---

## Öne Çıkarılacak IoT Tasarım Kararları

| Karar | Gerekçe |
|---|---|
| **JSN-SR04T** (HC-SR04 değil) | IP65 su geçirmez — açık hava koşullarında zorunlu |
| **Medyan filtresi** (ortalama değil) | Tek aykırı ölçüm `fill_level`'ı değiştirmiyor |
| **60 sn deep sleep** (90 sn limitinin altında) | $T_{sleep} < T_{tick} \times 3$ → 1 paket kaybında `OFFLINE` tetiklenmiyor |
| **RTC `last_fill_level`** | Her boot'ta yanlış anomali üretilmesini önler |
| **Değişim yoksa POST atla** | Gereksiz ağ trafiği ve DB write yok |
| **Conditional write (heartbeat)** | `TRUE→TRUE` DB write yok → %99+ write optimizasyonu |
| **PostGIS `ST_DWithin`** | Kamyon tespiti için 100m coğrafi sorgu |
| **Exponential backoff** | Geçici ağ hatalarında agresif retry yerine nazik geri çekilme |
