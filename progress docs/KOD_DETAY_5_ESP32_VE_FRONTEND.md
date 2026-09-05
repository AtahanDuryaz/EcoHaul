# Kod Detaylı Açıklama — Bölüm 5: ESP32 Firmware, Router ve Frontend

> Bu son bölüm: gerçek donanım (ESP32 + HC-SR04 ultrasonik sensör), simülasyon REST router'ı
> ve tüm React frontend'i kapsar.

← Önceki: [Bölüm 4 — Simülasyon Motoru](KOD_DETAY_4_SIMULASYON_MOTORU.md)

---

# BÖLÜM 5A — Simülasyon Router (`routers/simulation.py`)

Simülasyon motorunu web'e açan ince REST katmanı.

```python
router = APIRouter(prefix="/api/simulation", tags=["simulation"])


@router.post("/start")
async def start_simulation():
    await engine.start()
    return {"status": "running", "speed_multiplier": engine.speed_multiplier}


@router.post("/stop")
async def stop_simulation():
    await engine.stop()
    return {"status": "stopped"}


@router.post("/reset")
async def reset_simulation():
    was_running = engine.is_running
    await engine.stop()
    engine.reset()
    if was_running:
        await engine.start()
    return {"status": "reset"}
```

- `APIRouter(prefix="/api/simulation")` → tüm endpoint'lere ortak önek ekler.
- `start`/`stop` → motoru başlat/durdur (Bölüm 4.5'teki async metodları çağırır).
- **`reset` → ŞURASI İNCE.** Önce çalışıyor muydu kaydeder (`was_running`), durdurur, sıfırlar,
  **eğer çalışıyorduysa yeniden başlatır**. Yani kullanıcı çalışan simülasyonu sıfırlarsa,
  sıfırdan ama yine çalışır halde devam eder.

```python
@router.patch("/speed")
async def set_speed(multiplier: int = Body(..., embed=True)):
    valid = list(SPEED_OPTIONS.values())
    if multiplier not in valid:
        return {"error": f"Geçersiz hız. Kullanılabilir: {valid}"}
    engine.speed_multiplier = multiplier
    return {"speed_multiplier": multiplier}
```

Hız değiştirir. `Body(..., embed=True)` → JSON gövdesinden `{"multiplier": 60}` bekler.
Geçersiz hızı reddeder (sadece `SPEED_OPTIONS`'taki değerler).

```python
@router.get("/live-state")
def get_live_state():
    return engine.state_snapshot()


@router.get("/live-kpis")
def get_live_kpis():
    return engine.kpis_snapshot()


@router.get("/anomalies")
def get_anomalies():
    return list(reversed(engine.recent_anomalies))
```

GET endpoint'leri doğrudan motorun snapshot'larını döner. `reversed(recent_anomalies)` → en
yeni anomali başta gelsin diye ters çevirir.

```python
@router.get("/export-csv")
def export_fill_history():
    history = engine.fill_history
    if not history:
        return {"message": "Henüz kayıt yok. Simülasyonu çalıştırın."}

    fieldnames = ["sim_time", "world", "bin_id", "event",
                  "fill_pct", "fill_label", "distance_label", "fill_rate"]
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(history)
    output.seek(0)

    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=fill_history.csv"},
    )
```

**`fill_history`'yi CSV olarak indirir.** `io.StringIO()` → bellekte sanal dosya. `csv.DictWriter`
→ sözlük listesini CSV'ye yazar. `StreamingResponse` + `Content-Disposition: attachment` →
tarayıcı bunu **dosya indirme** olarak algılar. Rapor/analiz için ham veri çıkışı.

---

# BÖLÜM 5B — ESP32 Firmware (`ESP32-Sensor.ino`)

Gerçek donanım: ESP32 mikrodenetleyici + HC-SR04 ultrasonik mesafe sensörü. Kovanın üstüne
monte edilir, içine ses dalgası gönderip çöp seviyesini ölçer.

## 5B.1 Geometri Sabitleri

```cpp
const int TRIG_PIN = 15;
const int ECHO_PIN = 14;

const float BIN_HEIGHT_CM   = 100.0f; // gerçek yüksekliği sonra ölçüp değiştir
const float SENSOR_OFFSET_CM = 3.0f;  // sensör ile referans seviye arası offset

const int NUM_SAMPLES = 10;                   // median için örnek sayısı
const uint64_t SLEEP_INTERVAL_SECONDS = 3600; // 1 saat
const int HEARTBEAT_WAKE_INTERVAL = 8;        // 8 uyanma = 8 saat
```

- `TRIG_PIN`/`ECHO_PIN` → HC-SR04'ün tetikleme ve yankı pinleri.
- **`BIN_HEIGHT_CM` ve `SENSOR_OFFSET_CM` → backend ile birebir aynı** (`simulation_engine.py`
  SENSOR_BIN_HEIGHT_CM / SENSOR_OFFSET_CM). Bu eşleşme şart — yoksa firmware ve simülasyon
  farklı yüzde hesaplar.
- `SLEEP_INTERVAL_SECONDS = 3600` → her 1 saatte bir uyanıp ölçüm yapar (pil tasarrufu).
- `HEARTBEAT_WAKE_INTERVAL = 8` → 8 uyanmada bir (8 saat) zorunlu "hayattayım" sinyali.

## 5B.2 RTC Kalıcı State

```cpp
RTC_DATA_ATTR int rtc_lastLevelInt = -1;  // -1 = ilk boot
RTC_DATA_ATTR int rtc_wakeCounter  = 0;   // heartbeat için sayaç
```

**`RTC_DATA_ATTR` → ŞURASI ÖNEMLİ.** ESP32 deep-sleep'e girdiğinde RAM silinir ama RTC
belleği korunur. Bu değişkenler uyku boyunca **hayatta kalır**. `rtc_lastLevelInt` → son
gönderilen seviye (değişti mi diye karşılaştırmak için). `rtc_wakeCounter` → kaç kez uyandı
(heartbeat zamanı geldi mi diye).

## 5B.3 Mesafe Ölçümü

```cpp
float measureDistanceOnce(uint32_t timeoutMicros = 30000UL) {
  digitalWrite(TRIG_PIN, LOW);
  delayMicroseconds(2);
  digitalWrite(TRIG_PIN, HIGH);
  delayMicroseconds(10);
  digitalWrite(TRIG_PIN, LOW);

  unsigned long duration = pulseIn(ECHO_PIN, HIGH, timeoutMicros);
  if (duration == 0) {
    return NAN; // timeout
  }

  float distanceCm = (duration / 2.0f) * 0.0343f;

  if (distanceCm < 2.0f || distanceCm > 400.0f) {
    return NAN;
  }
  return distanceCm;
}
```

**HC-SR04 çalışma prensibi:**
- TRIG pinine **10 mikrosaniye HIGH** sinyal → sensör ses dalgası gönderir.
- `pulseIn(ECHO_PIN, HIGH)` → yankının dönmesi kaç mikrosaniye sürdü, ölçer.
- **`distanceCm = (duration / 2.0) * 0.0343` → ŞURASI FİZİK.** Ses hızı ~343 m/s = 0.0343 cm/µs.
  Dalga gidip geldiği için süre **ikiye bölünür** (tek yön mesafesi).
- `NAN` dönüşleri → timeout veya geçersiz aralık (2-400 cm dışı) = hatalı ölçüm.

## 5B.4 Medyan Filtre

```cpp
float measureMedianDistance(int numSamples = NUM_SAMPLES, ...) {
  float samples[NUM_SAMPLES];
  int validCount = 0;

  for (int i = 0; i < numSamples; ++i) {
    float d = measureDistanceOnce(timeoutMicros);
    if (!isnan(d)) {
      samples[validCount++] = d;
    }
    delay(50);
  }

  if (validCount == 0) return NAN;

  qsort(samples, validCount, sizeof(float), compareFloat);

  float median;
  if (validCount % 2 == 1) {
    median = samples[validCount / 2];
  } else {
    int mid = validCount / 2;
    median = (samples[mid - 1] + samples[mid]) / 2.0f;
  }
  return median;
}
```

**Neden medyan?** Tek bir ölçüm gürültülü olabilir (yansıma, parazit). 10 ölçüm alıp
**medyanını** (ortanca) kullanmak, aykırı değerlere **ortalamadan daha dayanıklıdır**. `qsort`
ile sıralar, ortadaki değeri alır. Geçersiz (NAN) ölçümler atlanır.

## 5B.5 Mesafe → Doluluk → Enum

```cpp
float computeFillPercentage(float measuredDistanceCm) {
  if (isnan(measuredDistanceCm)) return NAN;

  float effectiveDistance = measuredDistanceCm - SENSOR_OFFSET_CM;
  if (effectiveDistance < 0.0f) effectiveDistance = 0.0f;

  float filledHeight = BIN_HEIGHT_CM - effectiveDistance;
  if (filledHeight < 0.0f)        filledHeight = 0.0f;
  if (filledHeight > BIN_HEIGHT_CM) filledHeight = BIN_HEIGHT_CM;

  float fillPct = (filledHeight / BIN_HEIGHT_CM) * 100.0f;
  ...
  return fillPct;
}


FillLevel distanceToFillLevel(float measuredDistanceCm) {
  if (isnan(measuredDistanceCm)) return FillLevel::SENSOR_ERROR;
  float fillPct = computeFillPercentage(measuredDistanceCm);
  if (isnan(fillPct)) return FillLevel::SENSOR_ERROR;

  if (fillPct < 60.0f)      return FillLevel::EMPTY;
  else if (fillPct < 90.0f) return FillLevel::FULL;
  else                      return FillLevel::CRITICAL_FULL;
}
```

**Doluluk hesabı — backend'in `inject_sensor_reading` ile birebir aynı formül:**
- Sensör tepede; ölçtüğü mesafe **boşluk**. Mesafe küçükse çöp yüksek (dolu).
- `effectiveDistance = mesafe - OFFSET` → sensör montaj boşluğu çıkarılır.
- `filledHeight = BIN_HEIGHT - effectiveDistance` → çöpün yüksekliği.
- `fillPct = filledHeight / BIN_HEIGHT * 100`.

**Enum eşikleri:** <%60 EMPTY, %60-90 FULL, ≥%90 CRITICAL_FULL. Ölçüm alınamadıysa SENSOR_ERROR.

## 5B.6 Backend'e Gönderim

```cpp
bool sendStateChange(float medianDistance, FillLevel level) {
  String url = String(BACKEND_BASE_URL) + "/api/devices/" + BIN_ID + "/state-change";

  String body = "{";
  body += "\"enum_state\":\"";
  body += fillLevelToString(level);
  body += "\"";

  if (!isnan(medianDistance)) {
    body += ",\"median_distance_cm\":";
    body += String(medianDistance, 2);
  }
  body += "}";

  return postJson(url, body);
}
```

JSON gövdeyi **manuel string birleştirmeyle** kurar (ESP32'de ağır JSON kütüphanesi kullanmamak
için). `BIN_ID` (örn. "WMS1872") URL'e gömülür. Bu, backend'in `POST /api/devices/{bin_id}/state-change`
endpoint'ine (Bölüm 1.4) ulaşır.

## 5B.7 Akıllı Gönderim Mantığı (setup)

```cpp
void setup() {
  ...
  float medianDistance = measureMedianDistance();
  FillLevel currentLevel = distanceToFillLevel(medianDistance);

  int currentLevelInt = (int)currentLevel;
  bool firstBoot      = (rtc_lastLevelInt == -1);
  bool levelChanged   = (!firstBoot && currentLevelInt != rtc_lastLevelInt);
  bool forceHeartbeat = (rtc_wakeCounter >= HEARTBEAT_WAKE_INTERVAL);

  bool needWifi = firstBoot || levelChanged || forceHeartbeat;

  if (needWifi) {
    if (connectWiFi()) {
      bool ok = true;
      if (firstBoot || levelChanged) {
        ok = sendStateChange(medianDistance, currentLevel);
      } else if (forceHeartbeat) {
        ok = sendHeartbeat(currentLevel);
      }
      if (ok) rtc_wakeCounter = 0;
      else    rtc_wakeCounter++;
      WiFi.disconnect(true);
      WiFi.mode(WIFI_OFF);
    } else {
      rtc_wakeCounter++;
    }
  } else {
    rtc_wakeCounter++;
  }

  rtc_lastLevelInt = currentLevelInt;
  goToDeepSleep();
}
```

**Bu, ESP32'nin pil ömrünü uzatan zekası — ŞURASI ÖNEMLİ.** WiFi en çok pil tüketen işlem,
o yüzden **sadece gerektiğinde** açılır:
- **`firstBoot`** → ilk açılış, mutlaka gönder.
- **`levelChanged`** → seviye değişti (EMPTY→FULL gibi), gönder.
- **`forceHeartbeat`** → 8 saat geçti, "hayattayım" de.
- **Hiçbiri yoksa** → WiFi açma, sadece sayacı artır, uyumaya dön.

`if (ok) rtc_wakeCounter = 0` → başarılı gönderimde sayaç sıfırlanır. Başarısızsa artar
(bir dahaki uyanışta tekrar dener). En sonda `goToDeepSleep()` → 1 saat uyku.

```cpp
void loop() {
  // Kullanılmıyor; deep sleep sonrası reset ile tekrar setup() çalışır.
}
```

**`loop()` boş — ilginç ama doğru.** Deep-sleep'ten uyanış aslında bir **reset** gibidir;
`setup()` baştan çalışır. Klasik Arduino `loop()` döngüsü hiç kullanılmaz.

---

# BÖLÜM 5C — Frontend

React + Vite + Leaflet (harita). Üç ana sayfa: ana harita, simülasyon paneli, anomali geçmişi.

## 5C.1 API Katmanı (`services/api.js`)

```js
import axios from 'axios'

const api = axios.create({
  baseURL: import.meta.env.VITE_API_URL || 'http://localhost:8000'
})

// ── Bin / Anomali ──
export const getBins      = ()            => api.get('/api/bins')
export const getSummary   = ()            => api.get('/api/bins/summary')
export const getAnomalies = (limit = 50)  => api.get('/api/anomalies', { params: { limit } })

// ── Canlı Simülasyon ──
export const startSim     = ()            => api.post('/api/simulation/start')
export const getLiveState = ()            => api.get('/api/simulation/live-state')
export const getLiveKPIs  = ()            => api.get('/api/simulation/live-kpis')
```

**Tüm HTTP çağrılarının tek noktası.** `axios.create` ile bir instance kurulur; `baseURL`
env'den (yoksa localhost). **Faydası:** Endpoint string'leri burada toplanır. Bir endpoint
değişirse tek yerden düzeltilir. Bileşenler bu fonksiyonları import edip kullanır, ham URL
yazmaz.

## 5C.2 Ana Harita (`App.jsx`)

```jsx
useEffect(() => {
  const load = async () => {
    try {
      setLoading(true)
      const [binsResponse, summaryResponse] = await Promise.all([getBins(), getSummary()])
      setBins(binsResponse.data)
      setSummary(summaryResponse.data)
    } catch {
      setError('Veri yüklenemedi. Backend bağlantısını kontrol et.')
    } finally {
      setLoading(false)
    }
  }
  load()
}, [])
```

**`useEffect(..., [])` → ŞURASI ÖNEMLİ.** Boş bağımlılık dizisi `[]` → bu effect **sadece
sayfa ilk yüklendiğinde bir kez** çalışır. `Promise.all([getBins(), getSummary()])` → iki
isteği **paralel** atar (sıralı beklemekten hızlı). `try/catch/finally` → hata olursa mesaj
göster, her durumda loading'i kapat.

```jsx
const handlePlanRoute = async () => {
  const priorityBins = bins.filter((b) => b.status === 'CRITICAL_FULL' || b.status === 'FULL')
  if (priorityBins.length === 0) { setRouteError('...'); return }
  ...
  const waypoints = priorityBins.slice(0, 49).map((b) => ({ lat: b.lat, lon: b.lon }))
  const result = await fetchRoutePreview({ start: DUBLIN_DEPOT, waypoints })

  // GeoJSON coordinates are [lon, lat]; Leaflet needs [lat, lon]
  const coords = result.geometry.coordinates.map(([lon, lat]) => [lat, lon])
  setRouteSegments([{ id: 'collection-route', coordinates: coords, color: '#2563eb' }])
}
```

**Rota planlama.** Sadece dolu kovaları seçer (`filter`), ilk 49'unu rota servisine gönderir.
- **`const coords = ...map(([lon, lat]) => [lat, lon])` → ŞURASI KLASİK BİR TUZAK.** GeoJSON
  standardı koordinatları **[boylam, enlem]** sırasıyla verir; Leaflet ise **[enlem, boylam]**
  bekler. Bu satır sırayı çevirir. Çevrilmezse harita yanlış yere çizer — coğrafi uygulamalarda
  en sık hatalardan biri.

## 5C.3 Harita Bileşeni (`MapView.jsx`)

```jsx
const iconsByStatus = useMemo(() => ({
  OFFLINE:       L.divIcon({ className: 'bin-marker-gray', ... }),
  EMPTY:         L.divIcon({ className: 'bin-marker-empty', ... }),
  FULL:          L.divIcon({ className: 'bin-marker-full', ... }),
  CRITICAL_FULL: L.divIcon({ className: 'bin-marker-critical', ... })
}), [])

const getIconForBin = (bin) => {
  const status = bin.status || 'OFFLINE'
  return iconsByStatus[status] || iconsByStatus.OFFLINE
}
```

**`useMemo(..., [])` → performans optimizasyonu.** İkonlar pahalı nesneler; her render'da
yeniden oluşturulmasın diye **bir kez** hesaplanıp önbelleğe alınır. Durum → ikon eşlemesi:
her kova statüsüne göre farklı renkte marker.

```jsx
<MarkerClusterGroup chunkedLoading>
  {bins.map((bin) => (
    <Marker key={bin.bin_id} position={[bin.lat, bin.lon]} icon={getIconForBin(bin)}
      eventHandlers={{
        mouseover: (event) => event.target.openPopup(),
        mouseout: (event) => event.target.closePopup()
      }}>
      <Popup><BinPopup bin={bin} /></Popup>
    </Marker>
  ))}
</MarkerClusterGroup>
```

**`MarkerClusterGroup chunkedLoading` → ŞURASI ÖNEMLİ.** Dublin'de yüzlerce kova var. Hepsini
tek tek çizmek haritayı yavaşlatır. Kümeleme (clustering), yakın marker'ları zoom seviyesine
göre **gruplar** → performans. `chunkedLoading` → marker'ları parça parça yükler (UI donmaz).
`mouseover/mouseout` → fareyle üstüne gelince popup açılır.

## 5C.4 Simülasyon Paneli (`SimulationPage.jsx`)

En karmaşık frontend bileşeni — iki dünyayı yan yana gösterir, canlı veri çeker.

### Renk mantığı

```jsx
function fillColor(status, fillPct) {
  if (status === 'OFFLINE')       return '#6b7280'  // gri
  if (status === 'SENSOR_ERROR')  return '#a855f7'  // mor
  if (status === 'CRITICAL_FULL') return '#ef4444'  // kırmızı
  if (status === 'FULL')          return '#f97316'  // turuncu
  if (fillPct >= 30)              return '#eab308'  // sarı
  return '#22c55e'                                  // yeşil
}
```

Kova durumuna **ve** doluluğa göre renk. Önce özel durumlar (offline/sensör/kritik/full),
sonra doluluk yüzdesi (≥30 sarı, altı yeşil). Kullanıcı haritaya bakınca tek bakışta durumu
anlar.

### Polling — canlı veri akışı

```jsx
const POLL_STATE_MS   = 1_000
const POLL_KPIS_MS    = 2_000
const POLL_ANOMALY_MS = 3_000

useEffect(() => {
  pollState(); pollKPIs(); pollAnomalies()

  stateTimer.current   = setInterval(pollState,    POLL_STATE_MS)
  kpiTimer.current     = setInterval(pollKPIs,     POLL_KPIS_MS)
  anomalyTimer.current = setInterval(pollAnomalies, POLL_ANOMALY_MS)

  return () => {
    clearInterval(stateTimer.current)
    clearInterval(kpiTimer.current)
    clearInterval(anomalyTimer.current)
  }
}, [pollState, pollKPIs, pollAnomalies])
```

**Bu, canlı panonun motoru — ŞURASI ÇOK ÖNEMLİ.** Backend WebSocket kullanmıyor; bunun yerine
**polling** (düzenli sorgulama):
- Kova/kamyon konumu her **1 saniye** (sık — animasyon akıcı olsun).
- KPI'lar her **2 saniye** (orta).
- Anomaliler her **3 saniye** (seyrek — daha az kritik).
- **Farklı frekanslar → gereksiz ağ trafiğini azaltır.** Her şeyi 1 saniyede çekmek savurganlık.
- **`return () => clearInterval(...)` → KRİTİK.** Bu cleanup fonksiyonu, kullanıcı sayfadan
  çıkınca tüm interval'ları durdurur. Olmazsa "memory leak" + arka planda sonsuz istek kalır.

```jsx
const pollState = useCallback(async () => {
  try {
    const { data } = await getLiveState()
    setAlgoBins(data.algo_bins   || [])
    setFixedBins(data.fixed_bins  || [])
    setAlgoTrucks(data.algo_trucks  || [])
    setFixedTrucks(data.fixed_trucks || [])
    setVirtualClock(data.virtual_clock)
    setIsRunning(data.is_running)
    if (data.depot_lat) setDepotLat(data.depot_lat)
    if (data.depot_lon) setDepotLon(data.depot_lon)
  } catch { /* bağlantı hatası sessizce geçilir */ }
}, [])
```

`state_snapshot` (Bölüm 4.15) yanıtını React state'lerine dağıtır. `useCallback(..., [])` →
fonksiyon kimliğini sabit tutar (gereksiz yeniden oluşmasın, interval'lar kararlı kalsın).
`catch {}` → poll hatası sessizce geçilir (geçici bağlantı kopması paniğe değmez).

### Verimlilik hesabı

```jsx
const loadPerKm = kpis && kpis.distance_km > 0
  ? Math.round((kpis.load_collected / kpis.distance_km) * 10) / 10 : null
const overflowHours = kpis ? kpis.overflow_events : null
const effRate = loadPerKm !== null
  ? Math.min(100, Math.round(loadPerKm / 0.8)) : kpis ? 0 : null
```

**`loadPerKm = toplanan_yük / toplam_km` → sistem verimliliği.** Kodun yorumunda (orijinal
dosyada) açıklandığı gibi: verimlilik ve taşma **farklı boyutlar**, birbirine karıştırılmamalı.
Taşma ayrı (kırmızı) gösterilir, verimlilik skorunu düşürmez — akademik doğruluk. `effRate` →
80 yük/km'yi %100 referans alarak 0-100 skor üretir.

### İki dünya yan yana

```jsx
<ColPanel title="ALGORİTMA KPI" accent="algo"  kpis={algoKPIs}  trucks={algoTrucks}  bins={algoBins}  ... />
<div className="opc-divider" />
<ColPanel title="SABİT ROTA"   accent="fixed" kpis={fixedKPIs} trucks={fixedTrucks} bins={fixedBins} ... />
```

**Aynı `ColPanel` bileşeni iki kez kullanılır** — biri algo (yeşil), biri fixed (turuncu).
Kod tekrarı yok, görsel simetri tam. Kullanıcı iki sistemi yan yana karşılaştırır. Üstte
`SavingsStrip` farkı (tasarrufu) gösterir.

### Kamyon ikonu

```jsx
function makeTruckIcon(routeType, status) {
  const color  = routeType === 'algo' ? '#22c55e' : '#f59e0b'
  const emoji  = status === 'servicing' ? '🗑' : '🚛'
  return L.divIcon({
    html: `<div style="background:${color};...">${emoji}</div>`,
    ...
  })
}
```

Kamyon ikonu duruma göre değişir: yolda 🚛, boşaltırken 🗑. Renk dünyaya göre (algo yeşil,
fixed turuncu). Kullanıcı haritada kamyonların ne yaptığını canlı görür.

---

# Tüm Sistemin Özeti — Veri Yolculuğu

```
1. ESP32 (her saat uyanır)
   measureMedianDistance() → distanceToFillLevel() → sendStateChange()
        │  POST /api/devices/WMS1872/state-change  {"enum_state":"FULL","median_distance_cm":35.2}
        ▼
2. FastAPI main.py → post_state_change → bins_service.log_state_change
        ├─ telemetry tablosuna ham ölçüm
        ├─ bins tablosuna güncel durum
        ├─ anomaly_service: 4 kural kontrolü → event_log
        └─ engine.inject_sensor_reading → canlı simülasyona enjekte
        ▼
3. Simülasyon motoru (_loop her 0.2 sn)
        ├─ _job_fill: kovalar dolar (effective_fill_rate)
        ├─ _job_dispatch_algo: DPET 4 katman → dpet_dispatch
        ├─ _job_dispatch_fixed: sabit rotalar
        └─ _advance_trucks: kamyonlar hareket eder (state machine)
        ▼
4. React frontend (polling)
        ├─ getLiveState (1 sn) → harita: kovalar + kamyonlar
        ├─ getLiveKPIs (2 sn) → KPI panosu + tasarruf
        └─ getSimAnomalies (3 sn) → anomali logu
```

Bu beş bölüm, EcoHaul'un **tüm kod tabanını** uçtan uca açıklar: gerçek sensörden veritabanına,
algoritmadan canlı panoya kadar.

← İlk bölüme dön: [Bölüm 1 — API ve Veritabanı](KOD_DETAY_1_API_VE_VERITABANI.md)
